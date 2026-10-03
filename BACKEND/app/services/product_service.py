"""
Product service for handling product and version operations.

Authorization model: every write/read of a product goes through
``get_accessible_product`` so a user can only touch their own products
(ADMIN users can touch all). Version content is copied forward when a new
version is created, and each version keeps a canonical snapshot plus a
SHA-256 content hash.
"""
from typing import List, Optional

from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Claim,
    Evidence,
    Formulation,
    Ingredient,
    Product,
    ProductVersion,
    TargetMarket,
)
from app.schemas.product_schemas import ProductCreate, ProductUpdate
from app.services.audit_service import AuditService
from app.services.version_snapshot import refresh_version_snapshot
from app.utils.authorization import get_accessible_product, is_admin


class ProductService:
    """Service for product operations."""

    # ============================================
    # Products
    # ============================================

    @staticmethod
    def create_product(
        db: Session,
        product_data: ProductCreate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Product:
        """
        Create a product together with its initial version (version 1).

        The initial version is created as part of the same transaction as the
        product so we never persist a product without a version.
        """
        product = Product(
            name=product_data.name,
            description=product_data.description,
            category=product_data.category,
            created_by=user_id,
        )

        try:
            db.add(product)
            db.flush()  # assign product.id without ending the transaction

            version = ProductVersion(
                product_id=product.id,
                version_number=1,
                change_reason="Initial version",
                created_by=user_id,
            )
            db.add(version)
            db.flush()

            product.current_version_id = version.id
            db.commit()
            db.refresh(product)
            db.refresh(version)

            # Snapshot the (empty) initial content so content_hash is real
            refresh_version_snapshot(db, version)

            AuditService.log_action(
                db=db,
                user_id=user_id,
                action="create_product",
                resource="product",
                resource_id=product.id,
                details={
                    "name": product.name,
                    "category": product.category.value if product.category else None,
                    "initial_version_id": version.id,
                },
                request=request,
            )

            return product

        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="Failed to create product due to a data conflict",
            ) from exc

    @staticmethod
    def get_product(db: Session, product_id: int, user_id: Optional[int] = None) -> Optional[Product]:
        """
        Get a product by ID.

        When ``user_id`` is supplied the ownership rule is enforced (raises 404
        for products the user may not access).
        """
        if user_id is not None:
            return get_accessible_product(db, product_id, user_id)

        return (
            db.query(Product)
            .filter(Product.id == product_id, Product.is_active == True)  # noqa: E712
            .first()
        )

    @staticmethod
    def get_products(
        db: Session,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Product]:
        """
        List active products visible to a user.

        Regular users see their own products; ADMIN users see all products.
        """
        query = db.query(Product).filter(Product.is_active == True)  # noqa: E712

        if not is_admin(db, user_id):
            query = query.filter(Product.created_by == user_id)

        return query.order_by(Product.created_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def update_product(
        db: Session,
        product_id: int,
        product_data: ProductUpdate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Product:
        """Update product metadata (name/description/category), not version content."""
        product = get_accessible_product(db, product_id, user_id)

        update_data = product_data.model_dump(exclude_unset=True)
        previous = {field: getattr(product, field) for field in update_data}

        for field, value in update_data.items():
            setattr(product, field, value)

        try:
            db.commit()
            db.refresh(product)

            AuditService.log_action(
                db=db,
                user_id=user_id,
                action="update_product",
                resource="product",
                resource_id=product.id,
                details={
                    "changed_fields": list(update_data.keys()),
                    "previous": {k: str(v) for k, v in previous.items()},
                },
                request=request,
            )

            return product

        except Exception as exc:  # noqa: BLE001 - surfaced as a controlled 400
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="Failed to update product",
            ) from exc

    @staticmethod
    def delete_product(
        db: Session,
        product_id: int,
        user_id: int,
        request: Optional[Request] = None,
    ) -> bool:
        """Soft delete a product (is_active = False)."""
        product = get_accessible_product(db, product_id, user_id)

        product.is_active = False
        db.commit()

        AuditService.log_action(
            db=db,
            user_id=user_id,
            action="delete_product",
            resource="product",
            resource_id=product.id,
            request=request,
        )

        return True

    # ============================================
    # Versions
    # ============================================

    @staticmethod
    def create_version(
        db: Session,
        product_id: int,
        change_reason: Optional[str],
        user_id: int,
        request: Optional[Request] = None,
        copy_from_version_id: Optional[int] = None,
        start_empty: bool = False,
    ) -> ProductVersion:
        """
        Create a new version of a product.

        By default the new version inherits a copy of the product's current
        version content, so "change one thing and create version 2" works the
        way users expect. Pass ``start_empty=True`` to start from a blank
        version, or ``copy_from_version_id`` to branch from a specific version.
        """
        product = get_accessible_product(db, product_id, user_id)

        source_version: Optional[ProductVersion] = None
        if not start_empty:
            source_version = ProductService._resolve_source_version(
                db, product, copy_from_version_id
            )

        latest_version = (
            db.query(ProductVersion)
            .filter(ProductVersion.product_id == product_id)
            .order_by(ProductVersion.version_number.desc())
            .first()
        )
        new_version_number = (latest_version.version_number + 1) if latest_version else 1

        version = ProductVersion(
            product_id=product_id,
            version_number=new_version_number,
            change_reason=change_reason,
            created_by=user_id,
        )

        try:
            db.add(version)
            db.flush()

            if source_version is not None:
                ProductService._copy_version_content(db, source_version, version)
                db.flush()

            product.current_version_id = version.id
            db.commit()
            db.refresh(version)

            refresh_version_snapshot(db, version)

            AuditService.log_action(
                db=db,
                user_id=user_id,
                action="create_product_version",
                resource="product_version",
                resource_id=version.id,
                details={
                    "product_id": product_id,
                    "version_number": new_version_number,
                    "change_reason": change_reason,
                    "copied_from_version_id": source_version.id if source_version else None,
                    "content_hash": version.content_hash,
                },
                request=request,
            )

            return version

        except Exception as exc:  # noqa: BLE001 - surfaced as a controlled 400
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="Failed to create version",
            ) from exc

    @staticmethod
    def update_version(
        db: Session,
        product_id: int,
        version_id: int,
        change_reason: Optional[str],
        user_id: int,
        request: Optional[Request] = None,
    ) -> ProductVersion:
        """
        Update version metadata.

        Only ``change_reason`` is mutable. Version *content* is edited through
        the ingredient/formulation/claim/evidence endpoints (Phase 3), each of
        which refreshes the snapshot and content hash.
        """
        get_accessible_product(db, product_id, user_id)
        version = ProductService.get_version(db, version_id, product_id)

        version.change_reason = change_reason
        db.commit()
        db.refresh(version)

        refresh_version_snapshot(db, version)

        AuditService.log_action(
            db=db,
            user_id=user_id,
            action="update_product_version",
            resource="product_version",
            resource_id=version.id,
            details={"product_id": product_id, "change_reason": change_reason},
            request=request,
        )

        return version

    @staticmethod
    def get_versions(
        db: Session,
        product_id: int,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> List[ProductVersion]:
        """Get all versions of a product the user may access."""
        get_accessible_product(db, product_id, user_id)

        return (
            db.query(ProductVersion)
            .filter(ProductVersion.product_id == product_id)
            .order_by(ProductVersion.version_number.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_version(
        db: Session,
        version_id: int,
        product_id: Optional[int] = None,
    ) -> ProductVersion:
        """
        Get a specific product version.

        When ``product_id`` is given the version must belong to that product,
        which is what stops ``/products/1/versions/99`` from leaking data.
        """
        query = db.query(ProductVersion).filter(ProductVersion.id == version_id)

        if product_id is not None:
            query = query.filter(ProductVersion.product_id == product_id)

        version = query.first()

        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")

        return version

    # ============================================
    # Internal helpers
    # ============================================

    @staticmethod
    def _resolve_source_version(
        db: Session,
        product: Product,
        copy_from_version_id: Optional[int],
    ) -> Optional[ProductVersion]:
        """Pick the version whose content a new version should inherit."""
        if copy_from_version_id is not None:
            return ProductService.get_version(db, copy_from_version_id, product.id)

        if product.current_version_id is None:
            return None

        return ProductService.get_version(db, product.current_version_id, product.id)

    @staticmethod
    def _copy_version_content(
        db: Session,
        source: ProductVersion,
        target: ProductVersion,
    ) -> None:
        """
        Deep-copy a version's content into another version.

        This is why two versions are independent: mutating version 2 never
        touches version 1.
        """
        for item in source.ingredients:
            db.add(
                Ingredient(
                    product_version_id=target.id,
                    common_name=item.common_name,
                    botanical_name=item.botanical_name,
                    sanskrit_name=item.sanskrit_name,
                    plant_part=item.plant_part,
                    quantity=item.quantity,
                    quantity_unit=item.quantity_unit,
                    preparation_method=item.preparation_method,
                    source_type=item.source_type,
                    source_location=item.source_location,
                    source_documentation=item.source_documentation,
                    provenance=item.provenance,
                )
            )

        if source.formulation is not None:
            src = source.formulation
            db.add(
                Formulation(
                    product_version_id=target.id,
                    process_description=src.process_description,
                    extraction_method=src.extraction_method,
                    solvent=src.solvent,
                    temperature=src.temperature,
                    temperature_unit=src.temperature_unit,
                    pressure=src.pressure,
                    pressure_unit=src.pressure_unit,
                    duration=src.duration,
                    duration_unit=src.duration_unit,
                    concentration=src.concentration,
                    other_parameters=src.other_parameters,
                )
            )

        for item in source.claims:
            db.add(
                Claim(
                    product_version_id=target.id,
                    claim_text=item.claim_text,
                    claim_type=item.claim_type,
                    evidence_status=item.evidence_status,
                    evidence_notes=item.evidence_notes,
                    risk_level=item.risk_level,
                    review_status=item.review_status,
                    provenance=item.provenance,
                )
            )

        for item in source.evidence:
            db.add(
                Evidence(
                    product_version_id=target.id,
                    title=item.title,
                    evidence_type=item.evidence_type,
                    file_path=item.file_path,
                    source_url=item.source_url,
                    doi=item.doi,
                    publication_date=item.publication_date,
                    language=item.language,
                    authors=item.authors,
                    verification_status=item.verification_status,
                    document_hash=item.document_hash,
                    provenance=item.provenance,
                )
            )

        for item in source.target_markets:
            db.add(
                TargetMarket(
                    product_version_id=target.id,
                    country=item.country,
                    region=item.region,
                    regulatory_status=item.regulatory_status,
                    notes=item.notes,
                )
            )
