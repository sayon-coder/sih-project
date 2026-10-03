"""
Formulation change-impact simulator (Phase 7).

Compares two versions of a product and reports the differences that matter, plus
the questions a reviewer should ask. It is the platform's "what changed, and what
does that change touch?" step.

**Deterministic and verifiable.** Every difference is a named field comparison
between two stored versions - nothing is inferred by a model and nothing is
invented. Where a category cannot be compared (e.g. classification when neither
version has a recorded analysis), the report says so explicitly rather than
silently omitting it. Public-disclosure history is compared from the recorded
disclosure events (Phase 8).

**Cautious wording only.** A difference is never a conclusion. The report ranks
each difference (informational / review recommended / significant) and raises
questions; it does not determine legal, patent, regulatory or medical outcomes.

The analysis deliberately reuses the Phase 6 engines, so a change to a botanical,
a process or a claim flows through to the patent signal and the biodiversity/TK
status in the same report.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.analysis.change_impact_schemas import (
    SCREENING_PROVENANCE,
    SIGNIFICANCE_INFORMATIONAL,
    SIGNIFICANCE_REVIEW,
    SIGNIFICANCE_SIGNIFICANT,
    ChangeImpactResult,
    FieldChange,
    ImpactReviewQuestion,
    NotCompared,
)
from app.analysis.patent_screening import screen_patents
from app.analysis.prompts import ANALYSIS_DISCLAIMER, CHANGE_IMPACT_DISCLAIMER
from app.analysis.screening import screen_biodiversity, screen_traditional_knowledge
from app.models import (
    Claim,
    Evidence,
    Formulation,
    Ingredient,
    Product,
    ProductVersion,
    TargetMarket,
)

# ============================================
# Small helpers
# ============================================

def _norm(value: Any) -> str:
    """Normalise a value for identity comparison (case/punctuation insensitive)."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _enum_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _fmt(value: Any) -> Optional[str]:
    """Render a stored value for the report, dropping empties."""
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    if isinstance(value, str):
        value = value.strip()
        return value or None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


def _quantity(value: Any, unit: Any) -> Optional[str]:
    amount = _fmt(value)
    if amount is None:
        return None
    return f"{amount} {_fmt(unit) or ''}".strip()


# ============================================
# Field comparison primitives
# ============================================

def _compare_field(
    changes: List[FieldChange],
    *,
    category: str,
    field: str,
    subject: Optional[str],
    old_value: Any,
    new_value: Any,
    significance: str = SIGNIFICANCE_INFORMATIONAL,
    note: str = "",
) -> None:
    """Emit a `modified` change when a stored value differs."""
    old = _fmt(old_value)
    new = _fmt(new_value)
    if old == new:
        return
    changes.append(
        FieldChange(
            category=category,
            change_type="modified",
            field=field,
            subject=subject,
            old_value=old,
            new_value=new,
            significance=significance,
            note=note,
        )
    )


def _add(changes: List[FieldChange], category: str, field: str, subject: str, value: Any, note: str = "", significance: str = SIGNIFICANCE_REVIEW) -> None:
    changes.append(
        FieldChange(
            category=category,
            change_type="added",
            field=field,
            subject=subject,
            new_value=_fmt(value),
            significance=significance,
            note=note,
        )
    )


def _remove(changes: List[FieldChange], category: str, field: str, subject: str, value: Any, note: str = "", significance: str = SIGNIFICANCE_REVIEW) -> None:
    changes.append(
        FieldChange(
            category=category,
            change_type="removed",
            field=field,
            subject=subject,
            old_value=_fmt(value),
            significance=significance,
            note=note,
        )
    )


# ============================================
# Comparators
# ============================================

_INGREDIENT_FIELDS = (
    # (field, category, significance, note)
    (
        "botanical_name",
        "botanical",
        SIGNIFICANCE_SIGNIFICANT,
        "A different botanical species is a material composition change; it can affect ABS, "
        "traditional-knowledge and patent signals.",
    ),
    (
        "plant_part",
        "plant_part",
        SIGNIFICANCE_REVIEW,
        "The plant part changes the material used and may affect both the technical signal and "
        "the traditional-use position.",
    ),
    (
        "source_type",
        "cultivation",
        SIGNIFICANCE_SIGNIFICANT,
        "Cultivated/wild status affects access-and-benefit-sharing and sustainability review.",
    ),
    (
        "source_location",
        "origin",
        SIGNIFICANCE_REVIEW,
        "A change of geographic origin can affect access-and-benefit-sharing and GI signals.",
    ),
    (
        "preparation_method",
        "formulation",
        SIGNIFICANCE_REVIEW,
        "The preparation/delivery form changed; check that the product form and claims still align.",
    ),
    (
        "sanskrit_name",
        "botanical",
        SIGNIFICANCE_INFORMATIONAL,
        "A traditional name was added or removed.",
    ),
)


def _compare_ingredients(
    changes: List[FieldChange],
    old_ingredients: Sequence[Ingredient],
    new_ingredients: Sequence[Ingredient],
) -> None:
    """Match ingredients by common name and diff each field."""
    old_by_key = {_norm(ing.common_name): ing for ing in old_ingredients}
    new_by_key = {_norm(ing.common_name): ing for ing in new_ingredients}

    for key in new_by_key.keys() - old_by_key.keys():
        ing = new_by_key[key]
        _add(
            changes,
            "ingredients",
            "ingredient",
            ing.common_name,
            ing.botanical_name or ing.common_name,
            "A new ingredient changes the composition; review claims, evidence and classification.",
            SIGNIFICANCE_SIGNIFICANT,
        )
    for key in old_by_key.keys() - new_by_key.keys():
        ing = old_by_key[key]
        _remove(
            changes,
            "ingredients",
            "ingredient",
            ing.common_name,
            ing.botanical_name or ing.common_name,
            "A removed ingredient can leave claims unsupported; review the affected claims.",
            SIGNIFICANCE_SIGNIFICANT,
        )

    for key in old_by_key.keys() & new_by_key.keys():
        old, new = old_by_key[key], new_by_key[key]
        subject = new.common_name
        for field, category, significance, note in _INGREDIENT_FIELDS:
            _compare_field(
                changes,
                category=category,
                field=field,
                subject=subject,
                old_value=getattr(old, field),
                new_value=getattr(new, field),
                significance=significance,
                note=note,
            )
        _compare_field(
            changes,
            category="quantities",
            field="quantity",
            subject=subject,
            old_value=_quantity(old.quantity, old.quantity_unit),
            new_value=_quantity(new.quantity, new.quantity_unit),
            significance=SIGNIFICANCE_REVIEW,
            note="A quantity change can affect dosing, standardization and claim support.",
        )


_FORMULATION_FIELDS = (
    ("extraction_method", "extraction", SIGNIFICANCE_SIGNIFICANT,
     "A different extraction method changes the technical process and the patent signal."),
    ("solvent", "extraction", SIGNIFICANCE_SIGNIFICANT,
     "A different solvent changes the technical process and may affect residue and safety review."),
    ("temperature", "formulation", SIGNIFICANCE_REVIEW,
     "A processing-temperature change can affect the technical signal and the resulting composition."),
    ("pressure", "formulation", SIGNIFICANCE_REVIEW,
     "A processing-pressure change is part of the technical process."),
    ("duration", "formulation", SIGNIFICANCE_REVIEW,
     "A processing-duration change is part of the technical process."),
    ("concentration", "formulation", SIGNIFICANCE_REVIEW,
     "A concentration/standardization change can affect claim support."),
    ("process_description", "formulation", SIGNIFICANCE_INFORMATIONAL,
     "The process description changed."),
)


def _compare_formulation(
    changes: List[FieldChange],
    old_formulation: Optional[Formulation],
    new_formulation: Optional[Formulation],
) -> None:
    if old_formulation is None and new_formulation is None:
        return
    if old_formulation is None:
        _add(
            changes,
            "formulation",
            "formulation",
            "formulation",
            new_formulation.process_description or new_formulation.extraction_method,
            "A formulation/process was recorded for the new version but not the old one.",
            SIGNIFICANCE_REVIEW,
        )
        return
    if new_formulation is None:
        _remove(
            changes,
            "formulation",
            "formulation",
            "formulation",
            old_formulation.process_description or old_formulation.extraction_method,
            "The formulation/process recorded on the old version was removed.",
            SIGNIFICANCE_REVIEW,
        )
        return

    for field, category, significance, note in _FORMULATION_FIELDS:
        old_value = getattr(old_formulation, field)
        new_value = getattr(new_formulation, field)
        if field == "temperature":
            old_value = f"{_fmt(old_value)} {_fmt(old_formulation.temperature_unit) or ''}".strip() if old_value is not None else None
            new_value = f"{_fmt(new_value)} {_fmt(new_formulation.temperature_unit) or ''}".strip() if new_value is not None else None
        _compare_field(
            changes,
            category=category,
            field=field,
            subject="formulation",
            old_value=old_value,
            new_value=new_value,
            significance=significance,
            note=note,
        )


def _compare_claims(
    changes: List[FieldChange],
    old_claims: Sequence[Claim],
    new_claims: Sequence[Claim],
) -> None:
    old_by_text = {_norm(c.claim_text): c for c in old_claims}
    new_by_text = {_norm(c.claim_text): c for c in new_claims}

    for key in new_by_text.keys() - old_by_text.keys():
        claim = new_by_text[key]
        claim_type = _enum_value(claim.claim_type)
        significance = (
            SIGNIFICANCE_SIGNIFICANT
            if claim_type in {"therapeutic", "structure_function"}
            else SIGNIFICANCE_REVIEW
        )
        note = "A new claim needs supporting evidence."
        if claim_type == "therapeutic":
            note = (
                "A new therapeutic claim is high-risk: it needs substantiation and may change the "
                "product's classification and the regime that applies."
            )
        _add(changes, "claims", "claim", claim.claim_text[:120], claim_type, note, significance)

    for key in old_by_text.keys() - new_by_text.keys():
        claim = old_by_text[key]
        _remove(
            changes,
            "claims",
            "claim",
            claim.claim_text[:120],
            _enum_value(claim.claim_type),
            "Removing a claim can remove the need for its evidence and may change the classification.",
            SIGNIFICANCE_REVIEW,
        )

    for key in old_by_text.keys() & new_by_text.keys():
        old, new = old_by_text[key], new_by_text[key]
        _compare_field(
            changes,
            category="claims",
            field="claim_type",
            subject=new.claim_text[:120],
            old_value=_enum_value(old.claim_type),
            new_value=_enum_value(new.claim_type),
            significance=SIGNIFICANCE_SIGNIFICANT,
            note="A claim-type change can move the claim into a higher-risk category.",
        )
        _compare_field(
            changes,
            category="claims",
            field="evidence_status",
            subject=new.claim_text[:120],
            old_value=_enum_value(old.evidence_status),
            new_value=_enum_value(new.evidence_status),
            significance=SIGNIFICANCE_REVIEW,
            note="The declared evidence status changed; evidence review may be needed.",
        )


def _compare_evidence(
    changes: List[FieldChange],
    old_evidence: Sequence[Evidence],
    new_evidence: Sequence[Evidence],
) -> None:
    old_by_title = {_norm(e.title): e for e in old_evidence}
    new_by_title = {_norm(e.title): e for e in new_evidence}

    for key in new_by_title.keys() - old_by_title.keys():
        ev = new_by_title[key]
        _add(
            changes,
            "evidence",
            "evidence",
            ev.title,
            _enum_value(ev.evidence_type),
            "New evidence was attached; check whether it actually supports the claims it is cited for.",
        )
    for key in old_by_title.keys() - new_by_title.keys():
        ev = old_by_title[key]
        _remove(
            changes,
            "evidence",
            "evidence",
            ev.title,
            _enum_value(ev.evidence_type),
            "Evidence was removed; any claim relying on it may no longer be supported.",
        )
    for key in old_by_title.keys() & new_by_title.keys():
        old, new = old_by_title[key], new_by_title[key]
        _compare_field(
            changes,
            category="evidence",
            field="verification_status",
            subject=new.title,
            old_value=_enum_value(old.verification_status),
            new_value=_enum_value(new.verification_status),
            significance=SIGNIFICANCE_INFORMATIONAL,
            note="The evidence verification status changed.",
        )


def _compare_markets(
    changes: List[FieldChange],
    old_markets: Sequence[TargetMarket],
    new_markets: Sequence[TargetMarket],
) -> None:
    old_by_country = {_norm(m.country): m for m in old_markets}
    new_by_country = {_norm(m.country): m for m in new_markets}

    for key in new_by_country.keys() - old_by_country.keys():
        market = new_by_country[key]
        _add(
            changes,
            "markets",
            "target_market",
            market.country,
            market.region or market.country,
            "A new target market has its own regulatory, labelling and claim requirements.",
            SIGNIFICANCE_SIGNIFICANT,
        )
    for key in old_by_country.keys() - new_by_country.keys():
        market = old_by_country[key]
        _remove(
            changes,
            "markets",
            "target_market",
            market.country,
            market.region or market.country,
            "A target market was removed.",
            SIGNIFICANCE_INFORMATIONAL,
        )
    for key in old_by_country.keys() & new_by_country.keys():
        old, new = old_by_country[key], new_by_country[key]
        _compare_field(
            changes,
            category="markets",
            field="regulatory_status",
            subject=new.country,
            old_value=old.regulatory_status,
            new_value=new.regulatory_status,
            significance=SIGNIFICANCE_REVIEW,
            note="The recorded regulatory status for this market changed.",
        )


def _compare_disclosures(
    changes: List[FieldChange],
    old_types: Sequence[str],
    new_types: Sequence[str],
) -> None:
    """Compare recorded public-disclosure events between two versions.

    Disclosure rows are pinned to one version each, so the comparison is a
    set diff of recorded event types plus a count check. A newly recorded
    event is significant: disclosure timing can affect patent options, and
    the report must surface that for review (never as a legal conclusion).
    """
    old_set = {_norm(t) for t in old_types}
    new_set = {_norm(t) for t in new_types}
    for key in sorted(new_set - old_set):
        _add(
            changes,
            "public_disclosure",
            "disclosure_event",
            key,
            key,
            "A disclosure event was recorded for the new version; disclosure "
            "timing can affect patent options and deserves review before any "
            "filing or further disclosure.",
            SIGNIFICANCE_SIGNIFICANT,
        )
    for key in sorted(old_set - new_set):
        _remove(
            changes,
            "public_disclosure",
            "disclosure_event",
            key,
            key,
            "A disclosure event recorded for the old version has no matching "
            "event on the new version.",
            SIGNIFICANCE_INFORMATIONAL,
        )


def _compare_patent_signals(
    changes: List[FieldChange],
    old_version: ProductVersion,
    new_version: ProductVersion,
    old_content: Dict[str, Any],
    new_content: Dict[str, Any],
) -> None:
    """Reuse the Phase 6 engine: compare the technical features of both versions."""
    old_screen = screen_patents(
        old_version,
        old_content["ingredients"],
        old_content["formulation"],
        old_content["claims"],
        old_content["evidence"],
        old_content["markets"],
    )
    new_screen = screen_patents(
        new_version,
        new_content["ingredients"],
        new_content["formulation"],
        new_content["claims"],
        new_content["evidence"],
        new_content["markets"],
    )

    old_features: Set[Tuple[str, str]] = {
        (f.feature_type, _norm(f.value)) for f in old_screen.technical_features
    }
    new_features: Set[Tuple[str, str]] = {
        (f.feature_type, _norm(f.value)) for f in new_screen.technical_features
    }

    for feature_type, value_key in sorted(new_features - old_features):
        display = next(
            (f.value for f in new_screen.technical_features
             if f.feature_type == feature_type and _norm(f.value) == value_key),
            value_key,
        )
        _add(
            changes,
            "patent_signals",
            feature_type,
            f"{feature_type}: {display}",
            display,
            "A new technical feature was introduced; re-run patent screening for the new version.",
        )
    for feature_type, value_key in sorted(old_features - new_features):
        display = next(
            (f.value for f in old_screen.technical_features
             if f.feature_type == feature_type and _norm(f.value) == value_key),
            value_key,
        )
        _remove(
            changes,
            "patent_signals",
            feature_type,
            f"{feature_type}: {display}",
            display,
            "A technical feature was removed; the previous patent screening may no longer apply.",
        )

    _compare_field(
        changes,
        category="patent_signals",
        field="patent screening similarity indicator (demonstration corpus)",
        subject="formulation",
        old_value=old_screen.similarity_indicator,
        new_value=new_screen.similarity_indicator,
        significance=SIGNIFICANCE_REVIEW,
        note=(
            "The overlap with the demonstration corpus changed. This is a feature-overlap "
            "indicator, not a patentability finding; re-run the screening and review with an agent."
        ),
    )


def _compare_biodiversity_tk(
    changes: List[FieldChange],
    old_version: ProductVersion,
    new_version: ProductVersion,
    old_content: Dict[str, Any],
    new_content: Dict[str, Any],
) -> None:
    """Compare the Phase 6 biodiversity/ABS and TK status of the two versions."""

    def _screens(version: ProductVersion, content: Dict[str, Any]):
        bio = screen_biodiversity(
            version,
            content["ingredients"],
            content["formulation"],
            content["claims"],
            content["evidence"],
            content["markets"],
            db=None,
        )
        tk = screen_traditional_knowledge(
            version,
            content["ingredients"],
            content["formulation"],
            content["claims"],
            content["evidence"],
            content["markets"],
            db=None,
        )
        return bio, tk

    old_bio, old_tk = _screens(old_version, old_content)
    new_bio, new_tk = _screens(new_version, new_content)

    _compare_field(
        changes,
        category="biodiversity_tk",
        field="biodiversity/ABS status",
        subject="screening",
        old_value=old_bio.status,
        new_value=new_bio.status,
        significance=SIGNIFICANCE_REVIEW,
        note=(
            "The biodiversity/ABS screening status changed. It is a preliminary indication, "
            "not an official determination of legal requirements."
        ),
    )
    _compare_field(
        changes,
        category="biodiversity_tk",
        field="traditional-knowledge status",
        subject="screening",
        old_value=old_tk.status,
        new_value=new_tk.status,
        significance=SIGNIFICANCE_REVIEW,
        note=(
            "The traditional-knowledge screening status changed. Restricted sources such as the "
            "TKDL are not accessed or reproduced."
        ),
    )


def _compare_classification(
    changes: List[FieldChange],
    not_compared: List[NotCompared],
    old_classification: Optional[str],
    new_classification: Optional[str],
) -> bool:
    """Compare recorded preliminary classifications, if either version has one."""
    if old_classification is None and new_classification is None:
        not_compared.append(
            NotCompared(
                category="classification",
                reason=(
                    "Neither version has a recorded preliminary classification. Run a "
                    "comprehensive analysis on each version to compare them."
                ),
            )
        )
        return False
    if old_classification is None or new_classification is None:
        not_compared.append(
            NotCompared(
                category="classification",
                reason=(
                    "Only one version has a recorded preliminary classification, so the two "
                    "cannot be compared. Run a comprehensive analysis on both versions."
                ),
            )
        )
        return False

    before = len(changes)
    _compare_field(
        changes,
        category="classification",
        field="preliminary classification",
        subject="product",
        old_value=old_classification,
        new_value=new_classification,
        significance=SIGNIFICANCE_SIGNIFICANT,
        note=(
            "The preliminary classification changed. Classification is preliminary and requires "
            "confirmation; a change may alter which regime applies."
        ),
    )
    return len(changes) > before


# ============================================
# Review questions
# ============================================

_QUESTION_BANK: Dict[str, Tuple[str, str]] = {
    "ingredients": (
        "Do the added or removed ingredients change the product's composition, intended use or classification?",
        "A composition change can affect claims, evidence and the applicable regime.",
    ),
    "botanical": (
        "Have the botanical resources changed, and is lawful access documented for any new one?",
        "A different species or plant part can affect access-and-benefit-sharing and the technical signal.",
    ),
    "plant_part": (
        "Does the change of plant part affect the material, its constituents or the traditional-use position?",
        "Different plant parts can carry different constituents and different knowledge status.",
    ),
    "quantities": (
        "Does the quantity change affect dosing, standardization or the claims made about the product?",
        "A quantity change can invalidate claim support or alter standardization.",
    ),
    "origin": (
        "Has the geographic origin changed, and does that affect access-and-benefit-sharing or GI signals?",
        "Origin is central to biodiversity/ABS and geographical-indication considerations.",
    ),
    "cultivation": (
        "Was cultivated/wild sourcing changed, and has lawful access and sustainability been reviewed?",
        "Wild harvest can raise additional access-and-benefit-sharing and sustainability questions.",
    ),
    "formulation": (
        "Does the formulation or process change require new evidence, a new classification, or re-screening?",
        "Process changes can move both the patent signal and the regulatory position.",
    ),
    "extraction": (
        "Does the extraction or solvent change affect the technical signal, residues or claim support?",
        "The extraction process is often the core technical feature and can be safety-relevant.",
    ),
    "claims": (
        "Do the changed claims need new evidence, and are they acceptable in each target market?",
        "Claims drive evidence requirements and market acceptability.",
    ),
    "evidence": (
        "Is the evidence still adequate for the claims after the change to the evidence list?",
        "Removing evidence can leave a claim unsupported; adding evidence does not automatically support it.",
    ),
    "markets": (
        "Do the target-market changes introduce different regulatory, labelling or claim requirements?",
        "Each market applies its own rules to the same product.",
    ),
    "public_disclosure": (
        "Have any of these changes been, or will they be, publicly disclosed, and when?",
        "The timing of a public disclosure can affect patent options; this platform does not decide that.",
    ),
    "patent_signals": (
        "Should patent screening be re-run for the new version before any filing or disclosure?",
        "A feature change can alter the earlier comparison; screening is preliminary and never a patentability finding.",
    ),
    "biodiversity_tk": (
        "Should the biodiversity/ABS and traditional-knowledge screenings be re-run and reviewed after this change?",
        "A change of resource, origin or sourcing can move both screenings.",
    ),
    "classification": (
        "Should the preliminary classification be re-run for the new version?",
        "Classification is preliminary and can move when the composition or claims change.",
    ),
    "expert_review": (
        "Which of the significant changes should an expert review before the new version is used or disclosed?",
        "Significant changes are exactly where human review adds the most value.",
    ),
}


def _review_questions(categories: Sequence[str], expert_review: bool) -> List[ImpactReviewQuestion]:
    ordered = list(dict.fromkeys(categories))
    questions = []
    for category in ordered:
        entry = _QUESTION_BANK.get(category)
        if entry:
            questions.append(
                ImpactReviewQuestion(category=category, question=entry[0], rationale=entry[1])
            )
    # Always surface the disclosure-timing and expert-review questions: they are
    # the two the master prompt most cares about for a change.
    for category in ("public_disclosure", "expert_review"):
        if category not in ordered and category in _QUESTION_BANK:
            question, rationale = _QUESTION_BANK[category]
            questions.append(ImpactReviewQuestion(category=category, question=question, rationale=rationale))
    return questions


# ============================================
# Entry point
# ============================================

#: Which human review areas a changed category pulls in (spec item 10).
#: Ordered so the reported ``affected_areas`` follow the spec's wording.
_AREA_ORDER = [
    "Biodiversity/source-documentation review",
    "Traditional-knowledge review",
    "Claim-risk review",
    "Product-category review",
    "Evidence requirements",
    "International/Germany review",
    "International target-market review",
    "Disclosure-timing review",
    "Expert review",
]

_CATEGORY_AREAS = {
    "cultivation": ["Biodiversity/source-documentation review"],
    "origin": ["Biodiversity/source-documentation review"],
    "botanical": [
        "Biodiversity/source-documentation review",
        "Traditional-knowledge review",
    ],
    "plant_part": [
        "Biodiversity/source-documentation review",
        "Traditional-knowledge review",
    ],
    "biodiversity_tk": [
        "Biodiversity/source-documentation review",
        "Traditional-knowledge review",
    ],
    "claims": ["Claim-risk review", "Evidence requirements"],
    "evidence": ["Evidence requirements"],
    "quantities": ["Evidence requirements"],
    "formulation": ["Product-category review"],
    "extraction": ["Product-category review"],
    "classification": ["Product-category review"],
    "public_disclosure": ["Disclosure-timing review"],
    # patent_signals is not its own review area: it feeds "Patent screening"
    # re-assessment below, and the review questions already cover it.
}

#: Screens/analyses worth re-running after each changed category (spec item 10).
_CATEGORY_REASSESSMENTS = {
    "cultivation": ["Biodiversity/ABS screening"],
    "origin": ["Biodiversity/ABS screening"],
    "botanical": ["Biodiversity/ABS screening", "Traditional-knowledge screening"],
    "plant_part": ["Traditional-knowledge screening"],
    "biodiversity_tk": ["Biodiversity/ABS screening", "Traditional-knowledge screening"],
    "claims": ["Claim analysis"],
    "evidence": ["Claim analysis"],
    "formulation": ["Patent screening"],
    "extraction": ["Patent screening"],
    "patent_signals": ["Patent screening"],
    "classification": ["Preliminary classification"],
    "markets": ["Target-market regulatory review"],
    "public_disclosure": ["Public-disclosure review"],
}

_REASSESSMENT_ORDER = [
    "Biodiversity/ABS screening",
    "Traditional-knowledge screening",
    "Claim analysis",
    "Patent screening",
    "Preliminary classification",
    "Target-market regulatory review",
    "Public-disclosure review",
]


def _affected_areas(
    changes: Sequence[FieldChange], expert_review_recommended: bool
) -> List[str]:
    """Derive the human review areas these changes pull in (spec item 10)."""
    areas: set = set()
    for change in changes:
        areas.update(_CATEGORY_AREAS.get(change.category, []))
        if change.category == "markets":
            moved = f"{change.old_value or ''} {change.new_value or ''}".lower()
            areas.add(
                "International/Germany review" if "germany" in moved
                else "International target-market review"
            )
    if expert_review_recommended:
        areas.add("Expert review")

    ordered = [area for area in _AREA_ORDER if area in areas]
    ordered.extend(sorted(areas - set(_AREA_ORDER)))  # future categories, stable order
    return ordered


def _reassessment_recommended(changes: Sequence[FieldChange]) -> List[str]:
    """Derive the screens worth re-running after these changes (spec item 10)."""
    wanted: set = set()
    for change in changes:
        wanted.update(_CATEGORY_REASSESSMENTS.get(change.category, []))
    return [item for item in _REASSESSMENT_ORDER if item in wanted]


def _change_missing_information(changes: Sequence[FieldChange]) -> List[str]:
    """
    What is still needed to assess these changes (spec item 10).

    Derived only from the changes themselves - never invents a requirement the
    changes do not imply, and never states that approval is required.
    """
    missing: List[str] = []
    categories = {change.category for change in changes}

    if "cultivation" in categories:
        turned_wild = any(
            change.category == "cultivation"
            and (change.new_value or "").strip().lower() == "wild"
            for change in changes
        )
        missing.append(
            "Source documentation for wild-collected material (collection permission "
            "and supplier details)."
            if turned_wild
            else "Source documentation for the changed cultivated/wild status."
        )
    if "origin" in categories:
        missing.append("Source documentation for the changed geographic origin.")
    if "claims" in categories:
        added = [
            change.new_value
            for change in changes
            if change.category == "claims" and change.change_type == "added" and change.new_value
        ]
        if added:
            missing.append(
                "Evidence supporting the added claim text: " + "; ".join(dict.fromkeys(added)) + "."
            )
        if any(change.change_type == "removed" for change in changes if change.category == "claims"):
            missing.append("Confirmation of which claims remain intended for the new version.")
    if "formulation" in categories or "extraction" in categories:
        missing.append(
            "Formulation and process details for the new version (solvent, pressure, "
            "duration, concentration and standardisation)."
        )
    if "evidence" in categories:
        missing.append("Updated evidence set covering the changed claims.")
    if "quantities" in categories:
        missing.append("Dosing and standardisation details for the changed quantities.")
    if "markets" in categories:
        if any(
            "germany" in f"{change.old_value or ''} {change.new_value or ''}".lower()
            for change in changes
            if change.category == "markets"
        ):
            missing.append("German regulatory pathway classification for this product.")
        missing.append("Labelling and claim requirements for each changed target market.")
    if "classification" in categories:
        missing.append("Product information needed to re-establish the preliminary classification.")
    return missing


def build_change_impact(
    product: Product,
    old_version: ProductVersion,
    new_version: ProductVersion,
    old_content: Dict[str, Any],
    new_content: Dict[str, Any],
    old_classification: Optional[str] = None,
    new_classification: Optional[str] = None,
    old_disclosure_types: Optional[Sequence[str]] = None,
    new_disclosure_types: Optional[Sequence[str]] = None,
) -> ChangeImpactResult:
    """Build the change-impact report for a pair of versions."""
    changes: List[FieldChange] = []
    not_compared: List[NotCompared] = []

    _compare_ingredients(changes, old_content["ingredients"], new_content["ingredients"])
    _compare_formulation(changes, old_content["formulation"], new_content["formulation"])
    _compare_claims(changes, old_content["claims"], new_content["claims"])
    _compare_evidence(changes, old_content["evidence"], new_content["evidence"])
    _compare_markets(changes, old_content["markets"], new_content["markets"])
    _compare_patent_signals(changes, old_version, new_version, old_content, new_content)
    _compare_biodiversity_tk(changes, old_version, new_version, old_content, new_content)
    _compare_classification(changes, not_compared, old_classification, new_classification)
    _compare_disclosures(changes, old_disclosure_types or [], new_disclosure_types or [])

    # Order the report by significance, then category, so the important lines lead.
    rank = {
        SIGNIFICANCE_SIGNIFICANT: 0,
        SIGNIFICANCE_REVIEW: 1,
        SIGNIFICANCE_INFORMATIONAL: 2,
    }
    changes.sort(key=lambda c: (rank.get(c.significance, 3), c.category, c.field, c.subject or ""))

    categories_changed = list(dict.fromkeys(c.category for c in changes))

    significant = [c for c in changes if c.significance == SIGNIFICANCE_SIGNIFICANT]
    significant_changes = [
        f"{c.category}: {c.field}"
        + (f" ({c.subject})" if c.subject else "")
        + f" - {c.old_value or 'none'} -> {c.new_value or 'none'}"
        for c in significant
    ]

    expert_review_reasons: List[str] = []
    if any(c.category == "cultivation" for c in significant):
        expert_review_reasons.append(
            "Cultivated/wild sourcing changed, which affects access-and-benefit-sharing review."
        )
    if any(c.category == "botanical" for c in changes):
        expert_review_reasons.append(
            "A botanical resource was added, removed or reidentified; biometric and ABS review may be needed."
        )
    if any(c.category in {"extraction", "formulation"} and c.significance == SIGNIFICANCE_SIGNIFICANT for c in changes):
        expert_review_reasons.append(
            "The extraction process changed, which affects the technical (patent) signal."
        )
    if any(c.category == "claims" and c.change_type == "added" and c.significance == SIGNIFICANCE_SIGNIFICANT for c in changes):
        expert_review_reasons.append(
            "A high-risk (therapeutic/structure-function) claim was added and needs substantiation."
        )
    if any(c.category == "markets" and c.change_type == "added" for c in changes):
        expert_review_reasons.append(
            "A new target market was added, which brings its own requirements."
        )
    if any(c.category == "classification" for c in changes):
        expert_review_reasons.append(
            "The preliminary classification changed."
        )
    if any(c.category == "public_disclosure" for c in changes):
        expert_review_reasons.append(
            "Disclosure history differs between the versions; disclosure timing "
            "deserves review before any filing or further disclosure."
        )

    expert_review_recommended = bool(expert_review_reasons)

    if not changes:
        summary = (
            f"No content differences were found between v{old_version.version_number} and "
            f"v{new_version.version_number}."
        )
    else:
        summary = (
            f"Compared v{old_version.version_number} -> v{new_version.version_number}: "
            f"{len(changes)} difference(s) across {len(categories_changed)} categor"
            f"{'y' if len(categories_changed) == 1 else 'ies'} "
            f"({', '.join(categories_changed)}). "
            + (f"{len(significant)} significant." if significant else "No significant changes.")
        )

    warnings = [CHANGE_IMPACT_DISCLAIMER, ANALYSIS_DISCLAIMER]
    if not_compared:
        warnings.append(
            "Some categories could not be compared and are listed in `not_compared` rather "
            "than being silently omitted: "
            + "; ".join(f"{n.category} ({n.reason})" for n in not_compared)
        )
    if expert_review_recommended:
        warnings.append(
            "This comparison recommends expert review. A human decision is required before the "
            "new version is relied on, filed or disclosed."
        )

    return ChangeImpactResult(
        product_id=product.id,
        old_version_id=old_version.id,
        new_version_id=new_version.id,
        old_version_number=old_version.version_number,
        new_version_number=new_version.version_number,
        old_content_hash=old_version.content_hash,
        new_content_hash=new_version.content_hash,
        identical=not changes,
        summary=summary,
        changes=changes,
        change_count=len(changes),
        categories_changed=categories_changed,
        affected_areas=_affected_areas(changes, expert_review_recommended),
        reassessment_recommended=_reassessment_recommended(changes),
        missing_information=_change_missing_information(changes),
        significant_changes=significant_changes,
        expert_review_recommended=expert_review_recommended,
        expert_review_reasons=expert_review_reasons,
        review_questions=_review_questions(categories_changed, expert_review_recommended),
        not_compared=not_compared,
        warnings=warnings,
        provenance=SCREENING_PROVENANCE,
    )
