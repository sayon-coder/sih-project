"""
Shared loader for a product version's content.

Several analysis services need the same thing: every ingredient, the formulation,
claims, evidence and target markets attached to one version, in a stable order.
Keeping one implementation means a comparison and a screening always see exactly
the same content.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models import Claim, Evidence, Formulation, Ingredient, ProductVersion, TargetMarket


def load_version_content(db: Session, version: ProductVersion) -> Dict[str, Any]:
    """Return the version's content as a dict of ordered lists (plus the formulation)."""
    return {
        "ingredients": db.query(Ingredient)
        .filter(Ingredient.product_version_id == version.id)
        .order_by(Ingredient.id.asc())
        .all(),
        "formulation": db.query(Formulation)
        .filter(Formulation.product_version_id == version.id)
        .first(),
        "claims": db.query(Claim)
        .filter(Claim.product_version_id == version.id)
        .order_by(Claim.id.asc())
        .all(),
        "evidence": db.query(Evidence)
        .filter(Evidence.product_version_id == version.id)
        .order_by(Evidence.id.asc())
        .all(),
        "markets": db.query(TargetMarket)
        .filter(TargetMarket.product_version_id == version.id)
        .order_by(TargetMarket.id.asc())
        .all(),
    }
