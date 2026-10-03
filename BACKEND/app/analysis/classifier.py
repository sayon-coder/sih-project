"""
Preliminary product classification (Phase 5).

Answers "which broad regime might this product fall under?" as a *preliminary*
signal for a human reviewer. It is deliberately not authoritative: the master
prompt requires that classification never be presented as a legal or regulatory
determination.

Only facts already stored on the version are sent to the model, and the returned
category is validated against the platform's own ``ProductCategory`` enum, so the
model cannot introduce a category the system does not understand.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional, Sequence

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.analysis.prompts import CLASSIFICATION_SYSTEM_PROMPT
from app.analysis.schemas import (
    UNRESOLVED_PATHWAYS,
    ClassificationLLMOutput,
    PreliminaryClassification,
)
from app.llm.provider import get_llm_provider
from app.models import (
    Claim,
    Evidence,
    Formulation,
    Ingredient,
    Product,
    ProductCategory,
    ProductVersion,
    TargetMarket,
)

logger = logging.getLogger(__name__)

#: The categories we accept back from the model.
ALLOWED_CATEGORIES = {category.value for category in ProductCategory}

#: The five information requirements the spec lists while a classification is
#: UNRESOLVED - exactly these, in this order (spec item 4). A resolved run
#: instead reports only what is genuinely absent (``evaluate_classification_gaps``).
UNRESOLVED_MISSING_INFORMATION = [
    "intended use",
    "dosage form",
    "complete ingredient list",
    "exact label claims",
    "manufacturing/licensing details",
]


def _claim_type(claim: Claim) -> Optional[str]:
    value = claim.claim_type
    return value.value if hasattr(value, "value") else value


def evaluate_classification_gaps(
    ingredients: Sequence[Ingredient],
    claims: Sequence[Claim],
) -> tuple[List[str], bool]:
    """
    Deterministically decide whether enough is recorded for a preliminary
    category (spec item 4).

    Returns ``(missing_information, resolved)``:

    * ``missing_information`` is always built in the spec's canonical order
      (intended use, dosage form, complete ingredient list, exact label claims,
      manufacturing/licensing details) and only ever lists what is genuinely
      absent - nothing is inferred;
    * ``resolved`` is True only when a clear therapeutic intended use, a dosage
      form, a complete ingredient list and at least one claim are all recorded.
      While False the classification must be reported as ``UNRESOLVED`` with
      candidate pathways instead of a single main conclusion.

    Manufacturing/licensing details are never modelled as a field on any
    record, so they remain listed as missing even for a resolved run - the
    classification is preliminary either way.
    """
    therapeutic = any(_claim_type(claim) == "therapeutic" for claim in claims)
    dosage_form = any(
        (ing.preparation_method or "").strip() for ing in ingredients
    )
    complete_ingredients = bool(ingredients) and all(
        (ing.botanical_name or "").strip() for ing in ingredients
    )
    exact_claims = bool(claims)

    missing: List[str] = []
    if not therapeutic:
        missing.append("intended use")
    if not dosage_form:
        missing.append("dosage form")
    if not complete_ingredients:
        missing.append("complete ingredient list")
    if not exact_claims:
        missing.append("exact label claims")
    missing.append("manufacturing/licensing details")

    resolved = therapeutic and dosage_form and complete_ingredients and exact_claims
    return missing, resolved


def _build_prompt(
    product: Product,
    version: ProductVersion,
    ingredients: Sequence[Ingredient],
    formulation: Optional[Formulation],
    claims: Sequence[Claim],
    markets: Sequence[TargetMarket],
    evidence: Sequence[Evidence],
) -> str:
    """Assemble the classification prompt from stored product data only."""
    parts: List[str] = []

    parts.append("=== PRODUCT ===")
    parts.append(f"name: {product.name}")
    parts.append(f"description: {product.description or '(none provided)'}")
    parts.append(f"category_on_record: {product.category.value if hasattr(product.category, 'value') else product.category or '(none)'}")
    parts.append(f"version_number: {version.version_number}")
    parts.append("")

    parts.append("=== INGREDIENTS ===")
    if ingredients:
        for ing in ingredients:
            source = ing.source_type.value if hasattr(ing.source_type, "value") else ing.source_type
            parts.append(
                f"- {ing.common_name} | botanical={ing.botanical_name or 'N/A'} | "
                f"part={ing.plant_part or 'N/A'} | qty={ing.quantity or 'N/A'}{ing.quantity_unit or ''} | "
                f"preparation={ing.preparation_method or 'N/A'} | source={source or 'N/A'}"
            )
    else:
        parts.append("(no ingredients recorded)")
    parts.append("")

    parts.append("=== FORMULATION ===")
    if formulation:
        parts.append(
            f"process={formulation.process_description or 'N/A'} | "
            f"extraction={formulation.extraction_method or 'N/A'} | "
            f"solvent={formulation.solvent or 'N/A'}"
        )
    else:
        parts.append("(no formulation recorded)")
    parts.append("")

    parts.append("=== CLAIMS ===")
    if claims:
        for claim in claims:
            claim_type = claim.claim_type.value if hasattr(claim.claim_type, "value") else claim.claim_type
            parts.append(f"- [{claim_type or 'unspecified'}] {claim.claim_text}")
    else:
        parts.append("(no claims recorded)")
    parts.append("")

    parts.append("=== EVIDENCE DECLARED ===")
    if evidence:
        for ev in evidence:
            parts.append(f"- {ev.title}")
    else:
        parts.append("(no evidence recorded)")
    parts.append("")

    parts.append("=== TARGET MARKETS ===")
    if markets:
        for market in markets:
            parts.append(f"- {market.country} / {market.region or 'N/A'} (status={market.regulatory_status or 'N/A'})")
    else:
        parts.append("(no target markets recorded)")
    parts.append("")

    parts.append("Respond with valid JSON only.")
    return "\n".join(parts)


def classify_product(
    db: Session,
    product: Product,
    version: ProductVersion,
    ingredients: Sequence[Ingredient],
    formulation: Optional[Formulation],
    claims: Sequence[Claim],
    markets: Sequence[TargetMarket],
    evidence: Sequence[Evidence],
) -> PreliminaryClassification:
    """
    Produce a preliminary classification for a product version.

    Raises:
        ValueError: when the model's output cannot be parsed or names a category
            the platform does not recognise. Callers surface this as a controlled
            failure rather than guessing a category.
    """
    llm = get_llm_provider()
    raw = llm.generate(
        system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
        user_prompt=_build_prompt(product, version, ingredients, formulation, claims, markets, evidence),
    )

    try:
        parsed = ClassificationLLMOutput(**json.loads(raw))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ValueError(f"The AI returned malformed classification output: {exc}") from exc

    category = (parsed.preliminary_category or "").strip().lower()
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(
            f"The AI returned an unrecognised product category '{parsed.preliminary_category}'."
        )

    alternatives = [
        value.strip().lower()
        for value in parsed.alternative_categories
        if value.strip().lower() in ALLOWED_CATEGORIES and value.strip().lower() != category
    ]

    # Per-category IP and ABS posture fallbacks (SIH requirement A2).
    # Used when the model does not produce the posture field.
    _POSTURE_DEFAULTS = {
        "classical_traditional": (
            "Faces the Section 3(p) patenting bar; defended through the Traditional Knowledge "
            "Digital Library (TKDL). ABS duties under the Biological Diversity Act apply if "
            "biological resources are accessed. GI, TM and design routes may still be available."
        ),
        "proprietary_ayurvedic": (
            "Patent protection possible for novel technical aspects; trademark and design routes "
            "applicable. ABS and NBA prior-intimation duties apply for biological resources."
        ),
        "new_drug": (
            "Genuine patent potential for novel formulations or processes; must generate safety "
            "and effectiveness data. ABS duties apply. International filing possible via PCT."
        ),
        "possible_medicinal": (
            "Genuine patent potential for novel formulations or processes; must generate safety "
            "and effectiveness data. ABS duties apply. International filing possible via PCT."
        ),
        "phytopharmaceutical": (
            "Phytopharmaceuticals have genuine patent potential under the 2015 Drugs & Cosmetics "
            "Rules, but must meet efficacy and safety standards. ABS and NBA duties apply for "
            "plant-sourced ingredients. TRIPS-compliant protection possible via PCT."
        ),
        "ayurveda_aahara": (
            "Regulated under FSSAI Ayurveda-Aahar Regulations 2022. Patent routes narrow; "
            "GI and TM protection applicable. ABS duties apply for biological-resource ingredients."
        ),
        "possible_cosmetic": (
            "Regulated under Cosmetics Rules 2020. TM and Design protection applicable; "
            "trade-secret protection for formulation process. ABS duties if biological resources used."
        ),
    }
    ip_abs_posture = (parsed.ip_and_abs_posture or "").strip() or _POSTURE_DEFAULTS.get(category, "")

    # Deterministic gate (spec item 4): while intended use, dosage form,
    # ingredients or claims are incomplete the model's single category must not
    # be the main conclusion - the status leads, with candidate pathways.
    gaps, resolved = evaluate_classification_gaps(ingredients, claims)
    missing = gaps + [
        item for item in parsed.missing_information
        if item.strip().lower() not in {g.strip().lower() for g in gaps}
    ]

    if resolved:
        return PreliminaryClassification(
            status="PRELIMINARY",
            category=category,
            confidence=(parsed.confidence if parsed.confidence in {"low", "medium", "high"} else "low").upper(),
            rationale=parsed.rationale,
            ip_and_abs_posture=ip_abs_posture,
            alternative_categories=alternatives,
            missing_information=missing,
            review_required=True,
        )

    # While unresolved the classification reports the spec's five information
    # requirements (deterministic - the model cannot shrink or grow them), so
    # the card always shows exactly what must be provided before a category can
    # be established, and updates to genuinely-absent gaps once resolved.
    return PreliminaryClassification(
        status="UNRESOLVED",
        category=category,
        confidence="LOW",
        rationale=parsed.rationale,
        ip_and_abs_posture=ip_abs_posture,
        alternative_categories=alternatives,
        possible_categories=list(UNRESOLVED_PATHWAYS),
        missing_information=list(UNRESOLVED_MISSING_INFORMATION),
        review_required=True,
    )
