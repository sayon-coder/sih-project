"""
IP route map (Phase 6).

Answers "which IP routes might be worth considering for this product?" as a
preliminary, review-oriented map.

**Deliberately deterministic, not AI.** The master prompt warns: "Do not present
an IP route as legally applicable merely because an AI model suggests it."
Rather than ask a model to guess, every route here is derived by a transparent
rule over the product data the user actually recorded, and each suggestion lists
the ``signals`` that triggered it. A reviewer can therefore see *why* a route was
flagged, and no route is ever presented as applicable - only as worth reviewing.

The vocabulary follows the master prompt: every candidate route carries one of
"Potentially Relevant", "Further Review Recommended", "Not Indicated" or
"Insufficient Information".
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from app.analysis.ip_schemas import (
    IPRouteMapResult,
    IPRouteSuggestion,
    SCREENING_PROVENANCE,
    STATUS_TO_LABEL,
)
from app.analysis.prompts import ANALYSIS_DISCLAIMER, IP_ROUTE_DISCLAIMER, TRADITIONAL_KNOWLEDGE_DISCLAIMER
from app.models import Claim, Evidence, Formulation, Ingredient, Product, ProductVersion, TargetMarket

#: The four careful labels a route may carry.
LABEL_POTENTIALLY_RELEVANT = "Potentially Relevant"
LABEL_FURTHER_REVIEW = "Further Review Recommended"
LABEL_NOT_INDICATED = "Not Indicated"
LABEL_INSUFFICIENT = "Insufficient Information"

#: Display names for each route.
ROUTE_LABELS = {
    "patent": "Patent",
    "trademark": "Trademark",
    "copyright": "Copyright",
    "design": "Design",
    "gi": "Geographical Indication (GI)",
    "trade_secret": "Trade Secret",
    "plant_variety": "Plant Variety",
    "traditional_knowledge": "Traditional Knowledge",
    "biodiversity_abs": "Biodiversity / ABS",
}

#: Every route the platform knows about, in a stable order.
ROUTE_ORDER = (
    "patent",
    "trademark",
    "copyright",
    "design",
    "gi",
    "trade_secret",
    "plant_variety",
    "traditional_knowledge",
    "biodiversity_abs",
)


# ============================================
# Helpers
# ============================================

def _enum_value(value) -> Optional[str]:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _fmt_number(value) -> str:
    """Format a Decimal/float without a trailing '.0' (matches patent extraction)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


def _botanical_names(ingredients: Sequence[Ingredient]) -> List[str]:
    return [ing.botanical_name for ing in ingredients if ing.botanical_name]


def build_missing_information(
    ingredients: Sequence[Ingredient],
    formulation: Optional[Formulation],
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    markets: Sequence[TargetMarket],
) -> List[str]:
    """
    List the gaps that most limit any IP screening of this version.

    Shared by the route map and the biodiversity/TK screens so all three report
    the same gaps rather than three different lists.
    """
    missing: List[str] = []
    if not ingredients:
        missing.append("No ingredients recorded, so botanical routes cannot be assessed.")
    else:
        if any(not ing.botanical_name for ing in ingredients):
            missing.append("One or more ingredients have no botanical name recorded.")
        if any(not ing.source_location for ing in ingredients):
            missing.append("Source/geographic origin is not recorded for one or more ingredients.")
        if any(ing.source_type is None for ing in ingredients):
            missing.append("Cultivated/wild status is unknown for one or more ingredients.")
    if formulation is None or not (
        formulation.extraction_method or formulation.process_description
    ):
        missing.append("No formulation or extraction process recorded, so process-based routes are weak.")
    if not claims:
        missing.append("No claims recorded, so intended use and effect are unclear.")
    if not evidence:
        missing.append("No evidence documents attached to this version.")
    if not markets:
        missing.append("No target markets recorded.")
    return missing


# ============================================
# Route rules
# ============================================

#: The ABS gaps an access-and-benefit-sharing review still needs (spec item 5/9).
ABS_MISSING = [
    "Applicant category",
    "Exact source arrangement",
    "Activity",
    "Cultivation documentation",
    "Associated knowledge",
    "Possible exemptions",
]


def _route(
    key: str,
    status: str,
    *,
    why_flagged: str,
    rationale: str,
    signals: List[str],
    missing_information: List[str],
    next_action: str,
    limitation: str,
    review_questions: List[str],
) -> IPRouteSuggestion:
    """Build one route suggestion; ``label`` always derives from ``status``."""
    return IPRouteSuggestion(
        route=key,
        route_label=ROUTE_LABELS[key],
        label=STATUS_TO_LABEL[status],
        status=status,
        why_flagged=why_flagged,
        missing_information=missing_information,
        next_action=next_action,
        limitation=limitation,
        rationale=rationale,
        signals=signals,
        review_questions=review_questions,
    )


def _patent_route(
    botanicals: List[str], formulation: Optional[Formulation], ingredients: Sequence[Ingredient]
) -> IPRouteSuggestion:
    signals: List[str] = []
    if botanicals:
        signals.append(f"Botanical material recorded: {', '.join(sorted(set(botanicals)))}")
    if formulation is not None:
        if formulation.extraction_method:
            signals.append(f"Extraction method: {formulation.extraction_method}")
        if formulation.solvent:
            signals.append(f"Solvent: {formulation.solvent}")
        if formulation.temperature is not None:
            signals.append(f"Temperature: {_fmt_number(formulation.temperature)} {formulation.temperature_unit or 'C'}".strip())
        if formulation.concentration is not None:
            signals.append(f"Standardisation/concentration: {_fmt_number(formulation.concentration)}")

    process_recorded = formulation is not None and bool(
        (formulation.extraction_method or "").strip()
        or (formulation.process_description or "").strip()
    )
    limitation = "This is not a patentability conclusion."

    if process_recorded:
        return _route(
            "patent",
            "POTENTIALLY_RELEVANT",
            why_flagged="A technical extraction process was recorded.",
            rationale=(
                "A recorded extraction or processing method may describe a technical "
                "process worth reviewing for patent relevance. This platform does not "
                "determine patentability or novelty."
            ),
            signals=signals,
            missing_information=[],
            next_action="Compare the technical features with verified public patent records.",
            limitation=limitation,
            review_questions=[
                "Is there a technical process or composition you consider new, beyond what is publicly known?",
                "Has the process or composition been publicly disclosed already (or is it planned to be)?",
                "Would a registered patent agent consider a provisional specification appropriate before disclosure?",
            ],
        )
    if botanicals:
        rationale = (
            "Botanical material is recorded but no distinct technical process is, so a "
            "process-based patent route is less evident. Composition aspects may still "
            "be worth a review."
        )
        missing = ["A technical process description (extraction or manufacturing method)"]
        why = "Botanical material is recorded but no technical process is."
        next_action = "Record the technical process for this version so a patent review can be scoped."
    else:
        rationale = (
            "No botanical material or technical process was recorded, so no technical "
            "feature could be identified for a patent review."
        )
        missing = [
            "A technical process description (extraction or manufacturing method)",
            "Botanical or other technical material",
        ]
        why = "No technical process or biological material was recorded."
        next_action = "Record the technical process and the material it applies to."

    return _route(
        "patent",
        "ADDITIONAL_INFORMATION_NEEDED",
        why_flagged=why,
        rationale=rationale,
        signals=signals,
        missing_information=missing,
        next_action=next_action,
        limitation=limitation,
        review_questions=[
            "Is there a technical process or composition you consider new, beyond what is publicly known?",
            "Has the process or composition been publicly disclosed already (or is it planned to be)?",
            "Would a registered patent agent consider a provisional specification appropriate before disclosure?",
        ],
    )


def _trademark_route(product: Product, claims: Sequence[Claim]) -> IPRouteSuggestion:
    signals = [f"Product name on record: {product.name}"] if product.name else []
    if claims:
        signals.append(f"{len(claims)} claim(s) describe the product's positioning.")

    limitation = "This is not a trademark registrability or infringement assessment."
    if product.name:
        return _route(
            "trademark",
            "POTENTIALLY_RELEVANT",
            why_flagged="A brand name is recorded for the product.",
            rationale=(
                "A product name is recorded, so a trademark route may be worth "
                "considering for the brand. This platform does not conduct trademark "
                "searches or assess registrability."
            ),
            signals=signals,
            missing_information=[
                "Confirmation that the name is intended for use as a brand in each target market"
            ],
            next_action=(
                "Confirm brand intent and run a trademark search for each target market "
                "with a qualified professional."
            ),
            limitation=limitation,
            review_questions=[
                "Is the product name intended to be used as a brand in the target markets?",
                "Has a trademark search been carried out for those markets?",
            ],
        )

    return _route(
        "trademark",
        "ADDITIONAL_INFORMATION_NEEDED",
        why_flagged="No product name is recorded, so no brand could be assessed.",
        rationale="No product name is recorded, so no brand could be assessed.",
        signals=signals,
        missing_information=["A product/brand name intended for market use"],
        next_action="Record the brand name you intend to use in the target markets.",
        limitation=limitation,
        review_questions=[
            "Is the product name intended to be used as a brand in the target markets?",
            "Has a trademark search been carried out for those markets?",
        ],
    )


def _copyright_route(
    product: Product, formulation: Optional[Formulation], claims: Sequence[Claim]
) -> IPRouteSuggestion:
    signals: List[str] = []
    if product.description:
        signals.append("A product description is recorded.")
    if formulation is not None and formulation.process_description:
        signals.append("A formulation/process description is recorded.")
    if claims:
        signals.append("Claim text is recorded.")

    limitation = "This is not an assessment of copyright ownership or subsistence."
    if signals:
        return _route(
            "copyright",
            "POTENTIALLY_RELEVANT",
            why_flagged=(
                "Original written material (product description, process documentation "
                "or claim text) is recorded."
            ),
            rationale=(
                "Original written material (descriptions, documentation) may attract "
                "copyright. This is a general observation, not an assessment of any "
                "specific work's ownership or subsistence."
            ),
            signals=signals,
            missing_information=[],
            next_action=(
                "Identify the specific original works you own (artwork, software or "
                "written material) and their publication status."
            ),
            limitation=limitation,
            review_questions=[
                "Is written documentation (formulation records, reports) intended for publication or licensing?",
            ],
        )

    return _route(
        "copyright",
        "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED",
        why_flagged="No original artwork, software or written material is recorded.",
        rationale="No original written material is recorded for this version.",
        signals=signals,
        missing_information=["Original artwork, software or written material of your own"],
        next_action="Record any original artwork, software or written material you created.",
        limitation=limitation,
        review_questions=[
            "Is written documentation (formulation records, reports) intended for publication or licensing?",
        ],
    )


def _design_route(ingredients: Sequence[Ingredient], formulation: Optional[Formulation]) -> IPRouteSuggestion:
    forms = [ing.preparation_method for ing in ingredients if ing.preparation_method]
    signals = [f"Delivery/preparation form recorded: {', '.join(sorted(set(forms)))}"] if forms else []

    limitation = "This is not a design registrability assessment."
    if signals:
        why = (
            "A delivery form is recorded, but packaging or visual design was not supplied."
        )
        rationale = (
            "A physical delivery form is recorded. Design protection concerns the "
            "appearance of a product, which this platform has no packaging or visual "
            "design information to assess."
        )
    else:
        why = "No packaging or visual design was supplied."
        rationale = (
            "Design protection concerns the appearance of a product; the platform has "
            "no packaging or visual design information to assess."
        )

    return _route(
        "design",
        "ADDITIONAL_INFORMATION_NEEDED",
        why_flagged=why,
        rationale=rationale,
        signals=signals,
        missing_information=["Packaging or visual design information"],
        next_action="Supply packaging and visual-design details for a design review.",
        limitation=limitation,
        review_questions=[
            "Does the product or its packaging have a distinctive appearance you want to protect?",
        ],
    )


def _gi_route(
    product: Product, ingredients: Sequence[Ingredient], botanicals: List[str]
) -> IPRouteSuggestion:
    origins = [ing.source_location for ing in ingredients if ing.source_location]
    signals = [f"Declared origin: {', '.join(sorted(set(origins)))}"] if origins else []
    if botanicals:
        signals.append(f"Botanical material: {', '.join(sorted(set(botanicals)))}")

    limitation = "This is not a geographical indication eligibility determination."
    missing = ["Existing GI coverage or a documented association between the product and the region"]
    next_action = "Check whether an existing GI covers this resource or region."

    if origins and botanicals:
        why = (
            "Geographic origin and botanical material are recorded, but geographic "
            "origin alone is not sufficient for a geographical indication."
        )
        rationale = (
            "A botanical resource and a specific origin are both recorded. Whether an "
            "existing GI covers this resource, or whether the product is associated "
            "with the region, requires review; origin alone is not sufficient."
        )
    elif origins:
        why = "An origin is recorded, but no botanical resource to tie it to."
        rationale = "An origin is recorded, but no botanical resource to tie it to."
        missing = ["A botanical resource associated with the recorded origin"] + missing
    else:
        why = "No geographic origin is recorded, so a GI route cannot be assessed."
        rationale = "No geographic origin is recorded, so a GI route cannot be assessed."
        missing = ["Geographic origin for the material"] + missing

    return _route(
        "gi",
        "ADDITIONAL_INFORMATION_NEEDED",
        why_flagged=why,
        rationale=rationale,
        signals=signals,
        missing_information=missing,
        next_action=next_action,
        limitation=limitation,
        review_questions=[
            "Is the product associated with a specific place of origin in its marketing?",
            "Does any existing geographical indication cover this resource or region?",
        ],
    )


def _trade_secret_route(formulation: Optional[Formulation]) -> IPRouteSuggestion:
    signals = []
    if formulation is not None:
        if formulation.process_description:
            signals.append("A process description is recorded.")
        if formulation.extraction_method:
            signals.append(f"Extraction method: {formulation.extraction_method}")
        if formulation.solvent:
            signals.append(f"Solvent: {formulation.solvent}")

    limitation = "This is not a determination that trade-secret protection applies."
    if signals:
        return _route(
            "trade_secret",
            "POTENTIALLY_RELEVANT",
            why_flagged="A technical process is recorded that could be kept confidential.",
            rationale=(
                "A process is recorded. Where a process is deliberately kept confidential "
                "rather than published, a trade-secret approach may be worth considering as "
                "an alternative or complement to filing. Confidentiality depends on facts "
                "this platform cannot assess."
            ),
            signals=signals,
            missing_information=[
                "Whether the process is intended to remain confidential",
                "Who has access to the process and under what obligations",
            ],
            next_action=(
                "Confirm the confidentiality intent and review who has access to the "
                "process and under what obligations."
            ),
            limitation=limitation,
            review_questions=[
                "Do you intend to keep this process confidential rather than disclose it?",
                "Are the people with access to the process bound by confidentiality obligations?",
            ],
        )

    return _route(
        "trade_secret",
        "ADDITIONAL_INFORMATION_NEEDED",
        why_flagged="No process is recorded, so there is nothing to consider keeping confidential.",
        rationale="No process is recorded, so there is nothing to consider keeping confidential.",
        signals=signals,
        missing_information=[
            "A technical process description",
            "Whether the process is intended to remain confidential",
        ],
        next_action="Record the process you intend to keep confidential.",
        limitation=limitation,
        review_questions=[
            "Do you intend to keep this process confidential rather than disclose it?",
            "Are the people with access to the process bound by confidentiality obligations?",
        ],
    )


def _plant_variety_route(ingredients: Sequence[Ingredient], botanicals: List[str]) -> IPRouteSuggestion:
    cultivated = [
        ing.botanical_name
        for ing in ingredients
        if ing.botanical_name and _enum_value(ing.source_type) == "cultivated"
    ]
    signals = [f"Cultivated botanical material: {', '.join(sorted(set(cultivated)))}"] if cultivated else []
    if botanicals and not cultivated:
        signals.append(f"Botanical material (cultivation status unrecorded): {', '.join(sorted(set(botanicals)))}")

    limitation = "This is not an assessment of distinctness, uniformity or stability."
    missing = ["A described distinct plant variety (not just a species)"]

    if cultivated:
        status = "ADDITIONAL_INFORMATION_NEEDED"
        why = (
            "Cultivated botanical material is recorded, but no distinct plant variety "
            "is described."
        )
        rationale = (
            "Cultivated botanical material is recorded. A plant-variety route concerns "
            "a specific distinct variety, which is not described on this version; this "
            "platform does not assess distinctness, uniformity or stability."
        )
        next_action = "Describe the specific plant variety, if one underlies this product."
    elif botanicals:
        status = "ADDITIONAL_INFORMATION_NEEDED"
        why = "Botanical material is recorded, but no distinct plant variety is described."
        rationale = (
            "Botanical material is recorded but no distinct plant variety is described "
            "and its cultivated/wild status is unknown, so a plant-variety route cannot "
            "be assessed."
        )
        next_action = "Describe the specific plant variety and its cultivation status."
        missing = missing + ["Cultivated/wild status for the botanical material"]
    else:
        status = "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED"
        why = "No botanical material is recorded."
        rationale = "No botanical material is recorded."
        missing = []
        next_action = "No action needed until botanical material is recorded."

    return _route(
        "plant_variety",
        status,
        why_flagged=why,
        rationale=rationale,
        signals=signals,
        missing_information=missing,
        next_action=next_action,
        limitation=limitation,
        review_questions=[
            "Does a specific, identifiable plant variety (not a species) underlie this product?",
        ],
    )


def _traditional_knowledge_route(
    ingredients: Sequence[Ingredient],
    claims: Sequence[Claim],
    botanicals: List[str],
    evidence: Sequence[Evidence],
) -> IPRouteSuggestion:
    signals: List[str] = []
    traditional_claims = [c for c in claims if _enum_value(c.claim_type) == "traditional_use"]
    if traditional_claims:
        signals.append(f"{len(traditional_claims)} traditional-use claim(s) recorded.")
    sanskrit = [ing.sanskrit_name for ing in ingredients if ing.sanskrit_name]
    if sanskrit:
        signals.append(f"Sanskrit/traditional names recorded: {', '.join(sorted(set(sanskrit)))}")
    if botanicals:
        signals.append(f"Botanical material: {', '.join(sorted(set(botanicals)))}")

    tk_sources = [
        doc
        for doc in evidence
        if _enum_value(doc.evidence_type) in ("traditional_text", "pharmacopoeia")
    ]
    if tk_sources:
        signals.append(
            f"Traditional-use source document(s): {', '.join(sorted(set(doc.title for doc in tk_sources)))}"
        )

    limitation = TRADITIONAL_KNOWLEDGE_DISCLAIMER
    questions = [
        "Is any part of this product based on knowledge that is already publicly documented as traditional?",
        "Should the traditional-knowledge position be reviewed before any disclosure or filing?",
    ]

    if (traditional_claims or sanskrit) and tk_sources:
        return _route(
            "traditional_knowledge",
            "POTENTIALLY_RELEVANT",
            why_flagged=(
                "Traditional-use indicators and a traditional-use source document are "
                "recorded."
            ),
            rationale=(
                "Traditional-use claims, traditional names and a traditional-use source "
                "document are recorded. Whether traditional knowledge affects the "
                "position is a question for review, not something this platform "
                "determines. Restricted databases such as the TKDL are not accessed or "
                "reproduced here."
            ),
            signals=signals,
            missing_information=[],
            next_action=(
                "Review the traditional-use position together with the supplied source "
                "document before any disclosure or filing."
            ),
            limitation=limitation,
            review_questions=questions,
        )

    if traditional_claims or sanskrit:
        return _route(
            "traditional_knowledge",
            "ADDITIONAL_INFORMATION_NEEDED",
            why_flagged=(
                "Traditional-use indicators are recorded, but no traditional-use source "
                "document was supplied."
            ),
            rationale=(
                "Traditional-use claims or traditional names are recorded. Whether "
                "traditional knowledge affects the position is a question for review, not "
                "something this platform determines. Restricted databases such as the TKDL "
                "are not accessed or reproduced here."
            ),
            signals=signals,
            missing_information=[
                "A traditional-use source document (classical text or pharmacopoeia entry)"
            ],
            next_action="Attach a traditional-use source document for review.",
            limitation=limitation,
            review_questions=questions,
        )

    if botanicals:
        return _route(
            "traditional_knowledge",
            "ADDITIONAL_INFORMATION_NEEDED",
            why_flagged=(
                "Botanical material is recorded but no traditional-use information was "
                "supplied."
            ),
            rationale=(
                "Botanical material is recorded but no traditional-use information was "
                "supplied, so the traditional-knowledge position cannot be assessed."
            ),
            signals=signals,
            missing_information=[
                "Traditional-use information or a traditional-use source document"
            ],
            next_action="Supply traditional-use information or a traditional-use source document.",
            limitation=limitation,
            review_questions=questions,
        )

    return _route(
        "traditional_knowledge",
        "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED",
        why_flagged="No botanical or traditional-knowledge indicator is recorded.",
        rationale="No botanical or traditional-knowledge indicator is recorded.",
        signals=signals,
        missing_information=[],
        next_action="No action needed until a traditional-use indicator is recorded.",
        limitation=limitation,
        review_questions=questions,
    )


def _biodiversity_route(ingredients: Sequence[Ingredient], botanicals: List[str]) -> IPRouteSuggestion:
    origins = [ing.source_location for ing in ingredients if ing.source_location]
    wild = [
        ing.botanical_name
        for ing in ingredients
        if ing.botanical_name and _enum_value(ing.source_type) == "wild"
    ]
    signals: List[str] = []
    if botanicals:
        signals.append(f"Biological resource recorded: {', '.join(sorted(set(botanicals)))}")
    if origins:
        signals.append(f"Origin: {', '.join(sorted(set(origins)))}")
    if wild:
        signals.append(f"Wild-harvested material: {', '.join(sorted(set(wild)))}")

    limitation = "This is not an official determination of approval or legal obligation."
    questions = [
        "Where exactly was this biological material obtained, and under what arrangement?",
        "Does the source country's access-and-benefit-sharing regime apply to this use?",
    ]

    if botanicals and origins:
        indian = any("india" in str(origin).lower() for origin in origins)
        return _route(
            "biodiversity_abs",
            "POTENTIALLY_RELEVANT",
            why_flagged=(
                "An Indian biological resource was recorded with a stated source location."
                if indian
                else "A biological resource was recorded with a stated source location."
            ),
            rationale=(
                "A biological resource with a recorded origin may raise access-and-"
                "benefit-sharing considerations. Whether any approval or benefit-sharing "
                "obligation applies is not determined by this platform."
            ),
            signals=signals,
            missing_information=list(ABS_MISSING),
            next_action=(
                "Review access-and-benefit-sharing requirements with the relevant "
                "authority before sourcing or launch."
            ),
            limitation=limitation,
            review_questions=questions,
        )

    if botanicals:
        return _route(
            "biodiversity_abs",
            "ADDITIONAL_INFORMATION_NEEDED",
            why_flagged=(
                "Biological material is recorded but no origin, so access-and-benefit-"
                "sharing considerations cannot be assessed."
            ),
            rationale=(
                "Biological material is recorded but no origin, so access-and-benefit-"
                "sharing considerations cannot be assessed."
            ),
            signals=signals,
            missing_information=["Source location for the biological material"] + list(ABS_MISSING),
            next_action="Record the source location for each biological resource.",
            limitation=limitation,
            review_questions=questions,
        )

    return _route(
        "biodiversity_abs",
        "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED",
        why_flagged="No biological resource is recorded.",
        rationale="No biological resource is recorded.",
        signals=signals,
        missing_information=[],
        next_action="No action needed until a biological resource is recorded.",
        limitation=limitation,
        review_questions=questions,
    )


# ============================================
# Entry point
# ============================================

def build_ip_route_map(
    product: Product,
    version: ProductVersion,
    ingredients: Sequence[Ingredient],
    formulation: Optional[Formulation],
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    markets: Sequence[TargetMarket],
) -> IPRouteMapResult:
    """Build the preliminary IP route map for a product version."""
    botanicals = _botanical_names(ingredients)

    builders = {
        "patent": lambda: _patent_route(botanicals, formulation, ingredients),
        "trademark": lambda: _trademark_route(product, claims),
        "copyright": lambda: _copyright_route(product, formulation, claims),
        "design": lambda: _design_route(ingredients, formulation),
        "gi": lambda: _gi_route(product, ingredients, botanicals),
        "trade_secret": lambda: _trade_secret_route(formulation),
        "plant_variety": lambda: _plant_variety_route(ingredients, botanicals),
        "traditional_knowledge": lambda: _traditional_knowledge_route(
            ingredients, claims, botanicals, evidence
        ),
        "biodiversity_abs": lambda: _biodiversity_route(ingredients, botanicals),
    }

    routes = [builders[route]() for route in ROUTE_ORDER]

    # Apply the shared provenance stamp so no route can claim to be verified.
    for suggestion in routes:
        suggestion.provenance = SCREENING_PROVENANCE

    missing = build_missing_information(ingredients, formulation, claims, evidence, markets)

    warnings = [IP_ROUTE_DISCLAIMER]
    if missing:
        warnings.append(
            "This route map is limited by the missing information listed below; "
            "each gap weakens the reliability of the indications."
        )
    warnings.append(ANALYSIS_DISCLAIMER)

    return IPRouteMapResult(
        product_id=version.product_id,
        product_version_id=version.id,
        routes=routes,
        missing_information=missing,
        warnings=warnings,
    )
