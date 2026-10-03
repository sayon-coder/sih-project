"""
Patent screening (Phase 6).

Pipeline:

    product version
      -> deterministic technical-feature extraction (master prompt section 18)
      -> comparison against a frozen demonstration corpus
      -> matching / different / unknown features + a similarity indicator
      -> PatentScreeningResult (records + aggregate comparison)

**Deterministic and corpus-bound.** No model is asked to invent patent content.
The extracted features are exactly the ones the user recorded, the records come
from the frozen demo corpus (clearly labelled), and the comparison is a
field-by-field match. This is what makes it honest: the output can never contain
a fabricated patent number or a hallucinated source.

**What it never does.** It does not determine patentability, novelty, validity,
infringement or priority, and it says so on every response. The similarity
indicator measures *feature overlap in the demo corpus*, nothing more.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.analysis.ip_schemas import (
    PatentComparisonResult,
    PatentFeatureComparison,
    PatentRecordResult,
    PatentScreeningResult,
    SignalExplanation,
    TechnicalFeature,
    VERIFICATION_VERIFIED,
    human_jurisdiction,
    record_verification_fields,
)
from app.analysis.ip_routes import build_missing_information
from app.analysis.prompts import ANALYSIS_DISCLAIMER, PATENT_DISCLAIMER
from app.data.patent_demo_corpus import CORPUS_VERSION, DEMO_CORPUS_NOTE, get_demo_records
from app.models import Claim, Evidence, Formulation, Ingredient, ProductVersion, TargetMarket

#: How many candidate records to keep for one screening.
MAX_RECORDS = 5

#: Similarity bands and their thresholds (fraction of patent features matched).
BAND_HIGH = 0.6
BAND_MEDIUM = 0.35

#: The master prompt's careful labels.
LABEL_OVERLAP = "Possible Technical Overlap"
LABEL_POTENTIALLY_RELEVANT = "Potentially Relevant"
LABEL_FURTHER_REVIEW = "Further Review Recommended"


def _norm(value: str) -> str:
    """Normalise a feature value for comparison (case/punctuation insensitive)."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _enum_value(value) -> Optional[str]:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


# ============================================
# Feature extraction
# ============================================

def extract_technical_features(
    ingredients: Sequence[Ingredient],
    formulation: Optional[Formulation],
    claims: Sequence[Claim],
) -> List[TechnicalFeature]:
    """
    Extract the technical features the master prompt asks for, from stored data.

    Only fields that are actually present become features; a missing field is a
    gap (reported in ``missing_information``), not a guessed value.
    """
    features: List[TechnicalFeature] = []
    seen: set = set()

    def add(feature_type: str, value: Optional[str], source: str) -> None:
        if value is None:
            return
        value = str(value).strip()
        if not value:
            return
        key = (feature_type, _norm(value))
        if key in seen:
            return
        seen.add(key)
        features.append(TechnicalFeature(feature_type=feature_type, value=value, source=source))

    for ing in ingredients:
        src = f"ingredient:{ing.id}"
        add("botanical_species", ing.botanical_name, src)
        add("plant_part", ing.plant_part, src)
        add("delivery_form", ing.preparation_method, src)

    if formulation is not None:
        src = f"formulation:{formulation.id}" if formulation.id else "formulation"
        add("extraction_method", formulation.extraction_method, src)
        add("solvent", formulation.solvent, src)
        if formulation.temperature is not None:
            unit = formulation.temperature_unit or "C"
            add("temperature", f"{_fmt_number(formulation.temperature)} {unit}", src)
        if formulation.pressure is not None:
            unit = formulation.pressure_unit or ""
            add("pressure", f"{_fmt_number(formulation.pressure)} {unit}".strip(), src)
        if formulation.duration is not None:
            unit = formulation.duration_unit or ""
            add("duration", f"{_fmt_number(formulation.duration)} {unit}".strip(), src)
        if formulation.concentration is not None:
            add("standardization", f"{_fmt_number(formulation.concentration)}", src)

    for claim in claims:
        src = f"claim:{claim.id}"
        claim_type = _enum_value(claim.claim_type)
        text = (claim.claim_text or "").strip()
        if not text:
            continue
        if claim_type in {"therapeutic", "wellness", "structure_function"}:
            add("technical_effect", _truncate(text, 300), src)
        else:
            add("intended_use", _truncate(text, 300), src)

    return features


def _fmt_number(value) -> str:
    """Format a Decimal/float without a trailing '.0'."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ============================================
# Comparison
# ============================================

def compare_record_features(
    patent_features: Sequence[Dict[str, str]],
    user_features: Sequence[TechnicalFeature],
) -> Tuple[List[PatentFeatureComparison], float, str]:
    """
    Compare one record's features with the version's features.

    Returns ``(comparisons, similarity, band)`` where similarity is the fraction
    of the record's features that the version matches.
    """
    user_by_type: Dict[str, List[str]] = {}
    for feature in user_features:
        user_by_type.setdefault(feature.feature_type, []).append(feature.value)

    comparisons: List[PatentFeatureComparison] = []
    matches = 0

    for pf in patent_features:
        ftype = pf.get("feature_type", "")
        pvalue = pf.get("feature_value", "")
        user_values = user_by_type.get(ftype, [])

        matched_value = next(
            (uv for uv in user_values if _norm(uv) == _norm(pvalue)),
            None,
        )
        if matched_value is not None:
            verdict = "match"
            matches += 1
            user_value: Optional[str] = matched_value
        elif user_values:
            verdict = "different"
            user_value = user_values[0]
        else:
            verdict = "unknown"
            user_value = None

        comparisons.append(
            PatentFeatureComparison(
                feature_type=ftype,
                patent_value=pvalue,
                user_value=user_value,
                verdict=verdict,
            )
        )

    total = len(patent_features) or 1
    similarity = matches / total
    return comparisons, similarity, band_for(similarity)


def band_for(similarity: float) -> str:
    """Map a similarity fraction onto none / low / medium / high."""
    if similarity >= BAND_HIGH:
        return "high"
    if similarity >= BAND_MEDIUM:
        return "medium"
    if similarity > 0:
        return "low"
    return "none"


def label_for(band: str) -> str:
    """Map a similarity band onto one of the master prompt's careful labels."""
    if band == "high":
        return LABEL_OVERLAP
    if band == "medium":
        return LABEL_POTENTIALLY_RELEVANT
    return LABEL_FURTHER_REVIEW


def _uncertainty(comparisons: Sequence[PatentFeatureComparison]) -> str:
    unknown = sum(1 for c in comparisons if c.verdict == "unknown")
    if unknown:
        return (
            f"{unknown} feature(s) of this record could not be compared because the "
            "version does not record that information. The similarity indicator "
            "measures feature overlap only and is not an assessment of patent "
            "relevance, validity or infringement."
        )
    return (
        "The similarity indicator measures feature overlap only and is not an "
        "assessment of patent relevance, validity or infringement."
    )


def _aggregate(
    records: Sequence[PatentRecordResult],
) -> Tuple[List[str], List[str], List[str], str]:
    """Aggregate matching / different / unknown feature strings and the best band."""
    matching: List[str] = []
    different: List[str] = []
    unknown: List[str] = []
    best_rank = 0
    ranks = {"none": 0, "low": 1, "medium": 2, "high": 3}

    for record in records:
        for comparison in record.features:
            label = f"{comparison.feature_type}: {comparison.patent_value}"
            if comparison.verdict == "match":
                if label not in matching:
                    matching.append(label)
            elif comparison.verdict == "different":
                entry = f"{label} (version records: {comparison.user_value})"
                if entry not in different:
                    different.append(entry)
            else:
                if label not in unknown:
                    unknown.append(label)
        best_rank = max(best_rank, ranks.get(record.similarity_band, 0))

    indicator = next(band for band, rank in ranks.items() if rank == best_rank)
    return matching, different, unknown, indicator


# ============================================
# Screening entry points
# ============================================

def _build_record_results(
    user_features: Sequence[TechnicalFeature],
    corpus: Sequence[Dict],
) -> List[PatentRecordResult]:
    """Compare every corpus record and keep the ones with at least one match."""
    results: List[PatentRecordResult] = []

    for record in corpus:
        comparisons, similarity, band = compare_record_features(record["features"], user_features)
        if not any(c.verdict == "match" for c in comparisons):
            continue

        verification = record_verification_fields(
            record.get("record_source", "DEMO_CORPUS"),
            bool(record.get("is_demo", True)),
            record.get("verification_status"),
        )
        results.append(
            PatentRecordResult(
                id=0,  # assigned when persisted
                record_id=record["record_id"],
                patent_number=record.get("patent_number"),
                title=record["title"],
                assignee=record.get("assignee"),
                # Show a human jurisdiction ("India"), never a raw code ("IN")
                # that could recombine into the banned "AVAILABLE IN" label.
                jurisdiction=human_jurisdiction(record.get("jurisdiction")),
                publication_date=record.get("publication_date"),
                abstract=record.get("abstract"),
                source_url=record.get("source_url"),
                source_passage=record.get("source_passage"),
                record_source=record.get("record_source", "DEMO_CORPUS"),
                is_demo=record.get("is_demo", True),
                corpus_version=CORPUS_VERSION,
                verification_status=verification["verification_status"],
                record_label=verification["record_label"],
                relevance_label=label_for(band),
                similarity=round(similarity, 4),
                similarity_band=band,
                uncertainty=_uncertainty(comparisons),
                features=comparisons,
            )
        )

    results.sort(key=lambda r: r.similarity, reverse=True)
    return results[:MAX_RECORDS]


def _screening_warnings(records: Sequence[PatentRecordResult]) -> List[str]:
    warnings = [DEMO_CORPUS_NOTE, PATENT_DISCLAIMER]
    if not records:
        warnings.append(
            "No record in the demonstration corpus shared a technical feature with "
            "this version. That is not evidence that no relevant patent exists - it "
            "may simply reflect the small demonstration corpus."
        )
    else:
        if all(record.is_demo for record in records):
            warnings.append(
                "All identified records are demonstration data. Replace them with a "
                "live search before drawing any conclusion."
            )
    warnings.append(ANALYSIS_DISCLAIMER)
    return warnings


def _patent_explanation(
    indicator: str,
    record_count: int,
    missing_information: Sequence[str],
) -> "SignalExplanation":
    """Build the patent-screening "Why this result?" block (spec item 9)."""
    missing = list(missing_information)
    extra = "Verification against an official patent database (a live search is never performed here)."
    if extra not in missing:
        missing.append(extra)
    return SignalExplanation(
        signal=f"Similarity indicator: {indicator}",
        why=(
            f"The recorded technical features overlap with {record_count} record(s) in "
            "the frozen demonstration corpus."
            if record_count
            else "No record in the frozen demonstration corpus shares a technical "
            "feature with this version."
        ),
        missing=missing[:8],
        limit=PATENT_DISCLAIMER,
    )


def _corpus_flags(records: Sequence[PatentRecordResult]) -> Dict[str, Any]:
    """Response-level corpus provenance (spec item 6).

    ``corpus_type`` stays DEMO_CORPUS while any identified record is synthetic;
    ``records_verified`` is True only when every record is a verified public
    record. A live search is never performed, so that flag is always False.
    """
    all_verified = bool(records) and all(
        r.verification_status == VERIFICATION_VERIFIED for r in records
    )
    return {
        "corpus_type": "VERIFIED_PUBLIC_RECORD" if all_verified else "DEMO_CORPUS",
        "live_search_performed": False,
        "records_verified": all_verified,
    }


def screen_patents(
    version: ProductVersion,
    ingredients: Sequence[Ingredient],
    formulation: Optional[Formulation],
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    markets: Sequence[TargetMarket],
) -> PatentScreeningResult:
    """
    Extract features and screen a version against the frozen demonstration corpus.

    Returns a result whose records have ``id == 0``; the service persists them and
    fills in real ids.
    """
    features = extract_technical_features(ingredients, formulation, claims)
    records = _build_record_results(features, get_demo_records())
    matching, different, unknown, indicator = _aggregate(records)
    missing_information = build_missing_information(
        ingredients, formulation, claims, evidence, markets
    )

    return PatentScreeningResult(
        product_id=version.product_id,
        product_version_id=version.id,
        retrieval_mode="DEMO_CORPUS",
        search_is_live=False,
        corpus_version=CORPUS_VERSION,
        **_corpus_flags(records),
        technical_features=features,
        records=records,
        record_count=len(records),
        matching_features=matching,
        different_features=different,
        unknown_features=unknown,
        similarity_indicator=indicator,
        missing_information=missing_information,
        explanation=_patent_explanation(indicator, len(records), missing_information),
        warnings=_screening_warnings(records),
    )


def build_patent_comparison(
    version: ProductVersion,
    ingredients: Sequence[Ingredient],
    formulation: Optional[Formulation],
    claims: Sequence[Claim],
    records: Sequence[PatentRecordResult],
) -> PatentComparisonResult:
    """
    Re-compare a version's current features against already-identified records.

    Used by ``POST .../patents/compare`` so a user can re-run the comparison after
    editing the version, without creating new records.
    """
    features = extract_technical_features(ingredients, formulation, claims)
    matching, different, unknown, indicator = _aggregate(records)

    warnings = [PATENT_DISCLAIMER]
    if any(record.is_demo for record in records):
        warnings.insert(0, DEMO_CORPUS_NOTE)
    if not records:
        warnings.append(
            "No patents have been screened for this version yet, so there is nothing "
            "to compare against."
        )
    warnings.append(
        "This comparison reflects the version's current recorded features. If the "
        "content changed since the records were identified, re-run the screening."
    )
    warnings.append(ANALYSIS_DISCLAIMER)

    return PatentComparisonResult(
        product_id=version.product_id,
        product_version_id=version.id,
        **_corpus_flags(records),
        technical_features=features,
        records=list(records),
        record_count=len(records),
        matching_features=matching,
        different_features=different,
        unknown_features=unknown,
        similarity_indicator=indicator,
        warnings=warnings,
    )
