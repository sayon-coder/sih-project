"""
Authorization helpers.

Central place for "who may touch this resource" checks. Keeping them here means
every router enforces the same rule instead of re-implementing ownership logic.

Rule: a product is visible to the user who created it, and to ADMIN users.
Missing and forbidden resources both raise 404 so the API does not leak the
existence of other users' products.
"""
from typing import Set

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product, ProductVersion, Role, RoleName, User, UserRole
from app.utils.jwt_handler import verify_token


def get_current_user_model(
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency that returns the active User database instance."""
    user_id = int(token_payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_user_role_names(db: Session, user_id: int) -> Set[str]:
    """Return the set of role names assigned to a user (e.g. {"RESEARCHER"})."""
    rows = (
        db.query(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id)
        .all()
    )

    names: Set[str] = set()
    for (role_name,) in rows:
        names.add(role_name.value if isinstance(role_name, RoleName) else str(role_name))
    return names


def is_admin(db: Session, user_id: int) -> bool:
    """True when the user holds the ADMIN role."""
    return RoleName.ADMIN.value in get_user_role_names(db, user_id)


def get_accessible_product(db: Session, product_id: int, user_id: int) -> Product:
    """
    Fetch an active product the user is allowed to access.

    Raises:
        HTTPException: 404 when the product does not exist, is soft-deleted,
            or belongs to another user (unless the caller is an ADMIN).
    """
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.is_active == True)  # noqa: E712
        .first()
    )

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    if product.created_by != user_id and not is_admin(db, user_id):
        # Deliberately 404, not 403: do not reveal that the id exists.
        raise HTTPException(status_code=404, detail="Product not found")

    return product


def get_accessible_version(
    db: Session,
    product_id: int,
    version_id: int,
    user_id: int,
) -> ProductVersion:
    """
    Fetch a version that belongs to a product the user may access.

    Checking the product first and then constraining the version query to that
    product is what makes the nested browse-and-edit routes safe: a version id
    from someone else's product can never be reached by pairing it with a
    product id you own.

    Raises:
        HTTPException: 404 when the product is inaccessible, or when the version
            does not exist or belongs to a different product.
    """
    get_accessible_product(db, product_id, user_id)

    version = (
        db.query(ProductVersion)
        .filter(
            ProductVersion.id == version_id,
            ProductVersion.product_id == product_id,
        )
        .first()
    )

    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    return version


def require_admin(
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
) -> dict:
    """FastAPI dependency that allows only ADMIN users (403 otherwise)."""
    user_id = int(token_payload["sub"])
    if not is_admin(db, user_id):
        raise HTTPException(status_code=403, detail="Admin access required")
    return token_payload
