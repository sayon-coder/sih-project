"""
Version content service (Phase 3).

Owns the nested content of a product version: ingredients, formulation, claims,
evidence and target markets. Every route funnels through here so three rules are
enforced in exactly one place:

* **Authorization** - a version is only reachable through a product the caller
  owns (see ``get_accessible_version``), and each child row is verified to belong
  to that version.
* **Provenance** - new rows are stamped ``USER_PROVIDED`` by the server, and
  ``EXPERT_VERIFIED`` rows refuse to be edited or deleted.
* **Integrity** - after every successful edit the version's snapshot and
  SHA-256 ``content_hash`` are recomputed, so the stored hash always matches the
  stored content.
"""
from typing import Any, List, Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models import (
    Claim,
    Evidence,
    Formulation,
    Ingredient,
    ProductVersion,
    TargetMarket,
)
from app.schemas.product_schemas import (
    ClaimCreate,
    ClaimUpdate,
    EvidenceCreate,
    EvidenceUpdate,
    FormulationCreate,
    FormulationUpdate,
    IngredientCreate,
    IngredientUpdate,
    TargetMarketCreate,
    TargetMarketUpdate,
)
from app.services.audit_service import AuditService
from app.services.provenance import (
    apply_user_provenance,
    ensure_mutable,
    resolve_evidence_status,
)
from app.services.version_snapshot import refresh_version_snapshot
from app.utils.authorization import get_accessible_version

#: Honest gap note recorded in ``other_parameters`` when a process exists but
#: none of its parameters have been provided yet (spec item 3: never infer a
#: value - state what is missing). Cleared automatically once a parameter
#: arrives; user-written text is never overwritten.
MISSING_PARAMETERS_NOTE = (
    "Solvent, pressure, duration, concentration and standardisation are not yet provided."
)


class VersionContentService:
    """CRUD for the content nested under a product version."""

    # ============================================
    # Shared helpers
    # ============================================

    @staticmethod
    def _version(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> ProductVersion:
        """Resolve a version the user may edit (404 on anything else)."""
        return get_accessible_version(db, product_id, version_id, user_id)

    @staticmethod
    def _get_child(db: Session, model: Any, version_id: int, child_id: int) -> Any:
        """
        Fetch a child row that belongs to ``version_id``.

        Scoping the lookup by parent id means an id from another version (or
        another user's version) simply does not exist here.
        """
        row = (
            db.query(model)
            .filter(model.id == child_id, model.product_version_id == version_id)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
        return row

    @staticmethod
    def _finalize(
        db: Session,
        version: ProductVersion,
        *,
        user_id: int,
        action: str,
        resource: str,
        resource_id: Optional[int],
        details: Optional[dict] = None,
        request: Optional[Request] = None,
    ) -> ProductVersion:
        """Persist the edit, refresh the snapshot/hash, then write the audit entry."""
        db.commit()
        refresh_version_snapshot(db, version)

        audit_details = dict(details or {})
        audit_details["product_version_id"] = version.id
        audit_details["content_hash"] = version.content_hash

        AuditService.log_action(
            db=db,
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=audit_details,
            request=request,
        )
        return version

    # ============================================
    # Ingredients
    # ============================================

    @staticmethod
    def list_ingredients(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> List[Ingredient]:
        """List ingredients of an accessible version, oldest first."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        return (
            db.query(Ingredient)
            .filter(Ingredient.product_version_id == version.id)
            .order_by(Ingredient.id.asc())
            .all()
        )

    @staticmethod
    def create_ingredient(
        db: Session,
        product_id: int,
        version_id: int,
        data: IngredientCreate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Ingredient:
        """Add an ingredient to a version, marked USER_PROVIDED."""
        version = VersionContentService._version(db, product_id, version_id, user_id)

        ingredient = Ingredient(
            product_version_id=version.id,
            **data.model_dump(exclude_unset=True),
        )
        apply_user_provenance(ingredient)

        db.add(ingredient)
        db.flush()
        ingredient_id = ingredient.id

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="create_ingredient",
            resource="ingredient",
            resource_id=ingredient_id,
            details={"common_name": ingredient.common_name, "provenance": ingredient.provenance},
            request=request,
        )
        db.refresh(ingredient)
        return ingredient

    @staticmethod
    def update_ingredient(
        db: Session,
        product_id: int,
        version_id: int,
        ingredient_id: int,
        data: IngredientUpdate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Ingredient:
        """Update an ingredient's fields (provenance is preserved, not settable)."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        ingredient = VersionContentService._get_child(db, Ingredient, version.id, ingredient_id)
        ensure_mutable(ingredient, resource="ingredient")

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(ingredient, field, value)

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="update_ingredient",
            resource="ingredient",
            resource_id=ingredient.id,
            details={"changed_fields": list(update_data.keys())},
            request=request,
        )
        db.refresh(ingredient)
        return ingredient

    @staticmethod
    def delete_ingredient(
        db: Session,
        product_id: int,
        version_id: int,
        ingredient_id: int,
        user_id: int,
        request: Optional[Request] = None,
    ) -> bool:
        """Remove an ingredient from a version."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        ingredient = VersionContentService._get_child(db, Ingredient, version.id, ingredient_id)
        ensure_mutable(ingredient, resource="ingredient")

        common_name = ingredient.common_name
        db.delete(ingredient)

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="delete_ingredient",
            resource="ingredient",
            resource_id=ingredient_id,
            details={"common_name": common_name},
            request=request,
        )
        return True

    # ============================================
    # Formulation (one per version)
    # ============================================

    @staticmethod
    def get_formulation(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> Optional[Formulation]:
        """Return the version's formulation, or None when not yet entered."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        return (
            db.query(Formulation)
            .filter(Formulation.product_version_id == version.id)
            .first()
        )

    @staticmethod
    def upsert_formulation(
        db: Session,
        product_id: int,
        version_id: int,
        data: FormulationUpdate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Formulation:
        """
        Create or replace the version's formulation.

        PUT semantics: fields omitted from the body are left unchanged.
        """
        version = VersionContentService._version(db, product_id, version_id, user_id)

        formulation = (
            db.query(Formulation)
            .filter(Formulation.product_version_id == version.id)
            .first()
        )

        update_data = data.model_dump(exclude_unset=True)
        # Defence in depth for spec item 3: an empty string is "not provided",
        # so it must be stored as null - never as an empty recorded value.
        for field, value in update_data.items():
            if isinstance(value, str) and not value.strip():
                update_data[field] = None
        created = formulation is None

        if created:
            formulation = Formulation(product_version_id=version.id, **update_data)
            db.add(formulation)
        else:
            for field, value in update_data.items():
                setattr(formulation, field, value)

        # Spec item 3: a recorded process whose parameters are missing carries
        # an explicit "not yet provided" note - a gap statement, never an
        # inferred value. The note clears itself once the parameters arrive.
        params_missing = (
            formulation.solvent is None
            and formulation.pressure is None
            and formulation.duration is None
            and formulation.concentration is None
        )
        process_started = bool(
            (formulation.extraction_method or "").strip()
            or (formulation.process_description or "").strip()
        )
        if params_missing and process_started and not (formulation.other_parameters or "").strip():
            formulation.other_parameters = MISSING_PARAMETERS_NOTE
        elif (
            formulation.other_parameters == MISSING_PARAMETERS_NOTE and not params_missing
        ):
            formulation.other_parameters = None

        db.flush()
        formulation_id = formulation.id

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="create_formulation" if created else "update_formulation",
            resource="formulation",
            resource_id=formulation_id,
            details={"changed_fields": list(update_data.keys())},
            request=request,
        )
        db.refresh(formulation)
        return formulation

    # ============================================
    # Claims
    # ============================================

    @staticmethod
    def list_claims(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> List[Claim]:
        """List claims of an accessible version."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        return (
            db.query(Claim)
            .filter(Claim.product_version_id == version.id)
            .order_by(Claim.id.asc())
            .all()
        )

    @staticmethod
    def create_claim(
        db: Session,
        product_id: int,
        version_id: int,
        data: ClaimCreate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Claim:
        """
        Record a product claim.

        The claim is stored as USER_PROVIDED and its evidence status is limited
        to the user-settable set, so a user cannot assert that their own claim is
        already ``SUPPORTED``.
        """
        version = VersionContentService._version(db, product_id, version_id, user_id)

        payload = data.model_dump(exclude_unset=True)
        declared_status = payload.pop("evidence_status", None)

        claim = Claim(
            product_version_id=version.id,
            evidence_status=resolve_evidence_status(declared_status),
            review_status="pending",
            **payload,
        )
        apply_user_provenance(claim)

        db.add(claim)
        db.flush()
        claim_id = claim.id

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="create_claim",
            resource="claim",
            resource_id=claim_id,
            details={
                "claim_type": claim.claim_type.value if claim.claim_type else None,
                "evidence_status": claim.evidence_status.value
                if hasattr(claim.evidence_status, "value")
                else str(claim.evidence_status),
                "provenance": claim.provenance,
            },
            request=request,
        )
        db.refresh(claim)
        return claim

    @staticmethod
    def update_claim(
        db: Session,
        product_id: int,
        version_id: int,
        claim_id: int,
        data: ClaimUpdate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Claim:
        """Update a claim's text/type/notes. Evidence status is not user-settable."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        claim = VersionContentService._get_child(db, Claim, version.id, claim_id)
        ensure_mutable(claim, resource="claim")

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(claim, field, value)

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="update_claim",
            resource="claim",
            resource_id=claim.id,
            details={"changed_fields": list(update_data.keys())},
            request=request,
        )
        db.refresh(claim)
        return claim

    @staticmethod
    def delete_claim(
        db: Session,
        product_id: int,
        version_id: int,
        claim_id: int,
        user_id: int,
        request: Optional[Request] = None,
    ) -> bool:
        """Delete a claim from a version."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        claim = VersionContentService._get_child(db, Claim, version.id, claim_id)
        ensure_mutable(claim, resource="claim")

        db.delete(claim)

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="delete_claim",
            resource="claim",
            resource_id=claim_id,
            request=request,
        )
        return True

    # ============================================
    # Evidence
    # ============================================

    @staticmethod
    def list_evidence(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> List[Evidence]:
        """List evidence documents attached to a version."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        return (
            db.query(Evidence)
            .filter(Evidence.product_version_id == version.id)
            .order_by(Evidence.id.asc())
            .all()
        )

    @staticmethod
    def get_evidence(
        db: Session, product_id: int, version_id: int, evidence_id: int, user_id: int
    ) -> Evidence:
        """Fetch one evidence document from an accessible version."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        return VersionContentService._get_child(db, Evidence, version.id, evidence_id)

    @staticmethod
    def create_evidence(
        db: Session,
        product_id: int,
        version_id: int,
        data: EvidenceCreate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Evidence:
        """
        Attach an evidence document.

        Provenance starts at USER_PROVIDED and verification at PENDING: a user
        supplying a citation does not make it verified. The ``document_hash`` is
        left empty until the file itself is ingested (Phase 8).
        """
        version = VersionContentService._version(db, product_id, version_id, user_id)

        evidence = Evidence(
            product_version_id=version.id,
            verification_status="pending",
            **data.model_dump(exclude_unset=True),
        )
        apply_user_provenance(evidence)

        db.add(evidence)
        db.flush()
        evidence_id = evidence.id

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="create_evidence",
            resource="evidence",
            resource_id=evidence_id,
            details={"title": evidence.title, "provenance": evidence.provenance},
            request=request,
        )
        db.refresh(evidence)
        return evidence

    @staticmethod
    def update_evidence(
        db: Session,
        product_id: int,
        version_id: int,
        evidence_id: int,
        data: EvidenceUpdate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> Evidence:
        """
        Update an evidence document's metadata.

        ``verification_status`` may only be moved *back* to ``pending`` by a
        user; promoting evidence to ``verified`` belongs to the expert workflow.
        """
        version = VersionContentService._version(db, product_id, version_id, user_id)
        evidence = VersionContentService._get_child(db, Evidence, version.id, evidence_id)
        ensure_mutable(evidence, resource="evidence")

        update_data = data.model_dump(exclude_unset=True)
        requested_status = update_data.get("verification_status")
        if requested_status is not None:
            status_value = (
                requested_status.value
                if hasattr(requested_status, "value")
                else str(requested_status)
            )
            if status_value != "pending":
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "verification_status can only be reset to 'pending' by a user. "
                        "Verification is performed through the expert review workflow."
                    ),
                )

        for field, value in update_data.items():
            setattr(evidence, field, value)

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="update_evidence",
            resource="evidence",
            resource_id=evidence.id,
            details={"changed_fields": list(update_data.keys())},
            request=request,
        )
        db.refresh(evidence)
        return evidence

    # ============================================
    # Target markets
    # ============================================

    @staticmethod
    def list_target_markets(
        db: Session, product_id: int, version_id: int, user_id: int
    ) -> List[TargetMarket]:
        """List the markets a version is intended for."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        return (
            db.query(TargetMarket)
            .filter(TargetMarket.product_version_id == version.id)
            .order_by(TargetMarket.id.asc())
            .all()
        )

    @staticmethod
    def create_target_market(
        db: Session,
        product_id: int,
        version_id: int,
        data: TargetMarketCreate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> TargetMarket:
        """Add a target market to a version."""
        version = VersionContentService._version(db, product_id, version_id, user_id)

        market = TargetMarket(
            product_version_id=version.id,
            **data.model_dump(exclude_unset=True),
        )
        db.add(market)
        db.flush()
        market_id = market.id

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="create_target_market",
            resource="target_market",
            resource_id=market_id,
            details={"country": market.country},
            request=request,
        )
        db.refresh(market)
        return market

    @staticmethod
    def update_target_market(
        db: Session,
        product_id: int,
        version_id: int,
        market_id: int,
        data: TargetMarketUpdate,
        user_id: int,
        request: Optional[Request] = None,
    ) -> TargetMarket:
        """Update a target market entry."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        market = VersionContentService._get_child(db, TargetMarket, version.id, market_id)

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(market, field, value)

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="update_target_market",
            resource="target_market",
            resource_id=market.id,
            details={"changed_fields": list(update_data.keys())},
            request=request,
        )
        db.refresh(market)
        return market

    @staticmethod
    def delete_target_market(
        db: Session,
        product_id: int,
        version_id: int,
        market_id: int,
        user_id: int,
        request: Optional[Request] = None,
    ) -> bool:
        """Remove a target market from a version."""
        version = VersionContentService._version(db, product_id, version_id, user_id)
        market = VersionContentService._get_child(db, TargetMarket, version.id, market_id)

        db.delete(market)

        VersionContentService._finalize(
            db,
            version,
            user_id=user_id,
            action="delete_target_market",
            resource="target_market",
            resource_id=market_id,
            request=request,
        )
        return True
