"""
Biodiversity/ABS and traditional-knowledge screening (Phase 6).

Both screenings are deterministic and review-oriented. They collect what is
actually recorded, name the gaps, and return one of the four statuses the master
prompt allows:

    NO_IMMEDIATE_CONSIDERATION_IDENTIFIED
    ADDITIONAL_INFORMATION_NEEDED
    POTENTIALLY_RELEVANT
    REVIEW_RECOMMENDED

Neither screening ever declares that government approval is required or not
required, or that legal compliance has been achieved.

**Restricted sources are never reproduced.** Traditional-knowledge screening
consults only publicly available material (via the Phase 4 corpus) and always
reports the restricted/unavailable registry entries - notably the TKDL - as
restricted, so a reader knows to consult them directly through the authorised
channel.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.analysis.ip_routes import build_missing_information
from app.analysis.ip_schemas import (
    ScreeningResult,
    ScreeningSource,
    SignalExplanation,
    human_jurisdiction,
)
from app.analysis.prompts import (
    ANALYSIS_DISCLAIMER,
    BIODIVERSITY_DISCLAIMER,
    TRADITIONAL_KNOWLEDGE_DISCLAIMER,
)
from app.data.traditional_knowledge_sources import (
    ACCESS_PUBLIC,
    ACCESS_RESTRICTED,
    RESTRICTED_AVAILABILITY,
    SOURCES_VERSION,
    VERIFICATION_VERIFIED,
    get_traditional_knowledge_sources,
)
from app.models import Claim, Evidence, Formulation, Ingredient, ProductVersion, TargetMarket
from app.rag.retrieval import hybrid_retrieve
from app.rag.schemas import MetadataFilter

logger = logging.getLogger(__name__)

#: How many corpus passages to attach as sources for a screening.
SOURCE_PASSAGES = 4

#: Human-readable status labels returned alongside the machine status.
STATUS_LABELS = {
    "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED": "No immediate consideration identified",
    "ADDITIONAL_INFORMATION_NEEDED": "Additional information needed",
    "POTENTIALLY_RELEVANT": "Potentially relevant",
    "REVIEW_RECOMMENDED": "Review recommended",
}

#: Light aliases mapping document source types onto the spec vocabulary (item 7).
_SOURCE_TYPE_ALIASES = {
    "scientific_paper": "scientific_article",
    "paper": "scientific_article",
    "journal": "scientific_article",
    "scientific": "scientific_article",
    "science": "scientific_article",
    "law": "statute",
    "act": "statute",
    "regulation": "rule",
    "rules": "rule",
    "guidance": "official_guidance",
    "monograph": "official_guidance",
    "pharmacopoeia": "official_guidance",
    "traditional_text": "classical_text",
    "classical": "classical_text",
    "text": "classical_text",
    "patent_document": "patent",
    "patents": "patent",
}

#: Issuing authority per controlled source type (spec item 7).
_AUTHORITIES = {
    "classical_text": "Classical Ayurvedic compendia",
    "statute": "Legislature",
    "rule": "Regulator",
    "patent": "Patent office",
    "scientific_article": "Scientific publisher",
    "official_guidance": "Issuing authority",
}


def _enum_value(value) -> Optional[str]:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _status(status: str) -> tuple[str, str]:
    return status, STATUS_LABELS.get(status, status)


def _norm_source_type(value: Optional[str]) -> str:
    """Normalise a document's source type onto the spec vocabulary (item 7).

    Unknown values pass through unchanged - nothing is invented.
    """
    if not value:
        return ""
    low = value.strip().lower()
    return _SOURCE_TYPE_ALIASES.get(low, value)


def _authority_for(source_type: str) -> Optional[str]:
    """The issuing authority for a controlled source type, or None."""
    return _AUTHORITIES.get(source_type)


# ============================================
# Shared collection
# ============================================

def _collect(
    ingredients: Sequence[Ingredient],
    claims: Sequence[Claim],
    markets: Sequence[TargetMarket],
) -> Dict[str, Any]:
    """Collect the fields both screenings reason over."""
    botanicals = [ing.botanical_name for ing in ingredients if ing.botanical_name]
    plant_parts = [ing.plant_part for ing in ingredients if ing.plant_part]
    origins = [ing.source_location for ing in ingredients if ing.source_location]
    source_docs = [ing.source_documentation for ing in ingredients if ing.source_documentation]
    sanskrit = [ing.sanskrit_name for ing in ingredients if ing.sanskrit_name]
    cultivated_wild = {
        (ing.common_name or f"ingredient:{ing.id}"): (_enum_value(ing.source_type) or "unknown")
        for ing in ingredients
    }
    traditional_claims = [
        c.claim_text for c in claims if _enum_value(c.claim_type) == "traditional_use"
    ]
    countries = [market.country for market in markets if market.country]

    return {
        "biological_resource_present": bool(botanicals),
        "botanical_species": botanicals,
        "plant_parts": plant_parts,
        "origins": origins,
        "geographic_origin": origins[0] if origins else None,
        "cultivated_wild_status": cultivated_wild,
        "source_documentation": source_docs,
        "tk_involvement": bool(traditional_claims or sanskrit),
        "associated_knowledge": sanskrit + traditional_claims,
        "research_or_commercial_use": [
            _enum_value(c.claim_type) or "unspecified" for c in claims
        ],
        "target_markets": countries,
    }


def _registry_sources() -> List[ScreeningSource]:
    """
    Expose the source registry with explicit metadata (spec item 7).

    ``kind``/``availability`` stay for backward compatibility; ``authority``,
    ``access_status``, ``verification_status``, a human ``jurisdiction`` and the
    controlled ``source_type`` are what the UI now shows.
    """
    sources: List[ScreeningSource] = []
    for entry in get_traditional_knowledge_sources():
        restricted = (
            entry.get("kind") == "restricted"
            or entry.get("availability") == RESTRICTED_AVAILABILITY
        )
        sources.append(
            ScreeningSource(
                title=entry["title"],
                source_type=entry.get("source_type") or entry["kind"],
                availability=entry["availability"],
                jurisdiction=human_jurisdiction(entry.get("jurisdiction")),
                url=entry.get("url"),
                note=entry.get("note", "") or entry.get("description", ""),
                authority=entry.get("authority"),
                access_status=entry.get("access_status")
                or (ACCESS_RESTRICTED if restricted else ACCESS_PUBLIC),
                verification_status=entry.get("verification_status") or VERIFICATION_VERIFIED,
                source_url=entry.get("url"),
                retrieved_at=None,
            )
        )
    return sources


def _corpus_sources(
    db: Optional[Session],
    query: str,
    user_id: Optional[int],
) -> tuple[List[ScreeningSource], Optional[str]]:
    """
    Attach real corpus passages as sources.

    Retrieval can fail (for example when the embedding model is not cached); a
    failure degrades to "no corpus sources" with an explicit warning rather than
    blocking the screening. Only genuinely retrieved passages become sources -
    the platform never invents one.
    """
    if db is None or not query.strip():
        return [], None

    try:
        chunks = hybrid_retrieve(
            db=db,
            query=query,
            filters=MetadataFilter(),
            user_id=user_id,
            top_k_final=SOURCE_PASSAGES,
        )
    except Exception as exc:  # noqa: BLE001 - screening must not fail on retrieval
        logger.warning("Screening source retrieval failed: %s", exc)
        return [], (
            "The accessible corpus could not be searched for supporting sources "
            f"({exc}). This screening therefore lists no corpus passages; the "
            "status and questions are based only on the recorded product data."
        )

    sources: List[ScreeningSource] = []
    retrieved_at = datetime.now(timezone.utc).isoformat()
    for chunk in chunks:
        norm_type = _norm_source_type(chunk.source_type)
        sources.append(
            ScreeningSource(
                title=chunk.title,
                source_type=norm_type,
                availability="available",
                jurisdiction=human_jurisdiction(chunk.jurisdiction),
                url=chunk.source_url,
                note="Passage retrieved from the accessible corpus.",
                chunk_id=chunk.chunk_id,
                authority=_authority_for(norm_type),
                access_status=ACCESS_PUBLIC,
                verification_status="PENDING_REVIEW",
                source_url=chunk.source_url,
                retrieved_at=retrieved_at,
            )
        )
    return sources, None


# ============================================
# Biodiversity / ABS
# ============================================

#: What an access-and-benefit-sharing assessment would still need (spec item 9).
ABS_MISSING_ITEMS = [
    "Applicant category",
    "Exact source arrangement",
    "Activity",
    "Cultivation documentation",
    "Associated knowledge",
    "Possible exemptions",
]


def _biodiversity_explanation(
    status: str,
    status_label: str,
    collected: Dict[str, Any],
    missing_information: List[str],
) -> SignalExplanation:
    """Build the biodiversity "Why this result?" block (spec item 9)."""
    origins = [str(o) for o in (collected.get("origins") or []) if o]
    indian = any("india" in origin.lower() for origin in origins)

    if status == "POTENTIALLY_RELEVANT":
        why = (
            "An Indian biological resource was recorded with a stated source location."
            if indian
            else "A biological resource with a stated source location was recorded."
        )
        missing = list(ABS_MISSING_ITEMS)
    elif status == "REVIEW_RECOMMENDED":
        why = "Wild-harvested biological material is recorded with a stated source location."
        missing = list(ABS_MISSING_ITEMS)
    elif status == "ADDITIONAL_INFORMATION_NEEDED":
        why = (
            "Information required for this screening (the ingredient list, source "
            "location and/or cultivated-wild status) is incomplete."
        )
        missing = list(missing_information) or [
            "Source location and cultivated/wild status for every ingredient"
        ]
    else:  # NO_IMMEDIATE_CONSIDERATION_IDENTIFIED
        why = "No biological resource (botanical species) is recorded for this version."
        missing = list(missing_information)

    for entry in missing_information:
        if entry not in missing:
            missing.append(entry)

    return SignalExplanation(
        signal=status_label,
        why=why,
        missing=missing[:8],
        limit="This is not an official determination of approval or legal obligation.",
    )


def _tk_explanation(
    status_label: str,
    considerations: List[str],
    missing_information: List[str],
) -> SignalExplanation:
    """Build the traditional-knowledge "Why this result?" block (spec item 9)."""
    missing = list(missing_information)
    extra = "A traditional-use source document establishing where the use is documented."
    if extra not in missing:
        missing.append(extra)
    return SignalExplanation(
        signal=status_label,
        why=(
            considerations[0]
            if considerations
            else "The status was derived from the information recorded on this version."
        ),
        missing=missing[:8],
        limit=TRADITIONAL_KNOWLEDGE_DISCLAIMER,
    )


def screen_biodiversity(
    version: ProductVersion,
    ingredients: Sequence[Ingredient],
    formulation: Optional[Formulation],
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    markets: Sequence[TargetMarket],
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
    include_sources: bool = False,
) -> ScreeningResult:
    """
    Screen a version for access-and-benefit-sharing considerations.

    Corpus retrieval is opt-in (``include_sources``). It is the only part of the
    screening that needs the embedding model, so leaving it off keeps the default
    screening fast and deterministic while still allowing a grounded run.
    """
    collected = _collect(ingredients, claims, markets)
    botanicals: List[str] = collected["botanical_species"]
    wild = [
        ing.botanical_name
        for ing in ingredients
        if ing.botanical_name and _enum_value(ing.source_type) == "wild"
    ]
    missing_origin = any(not ing.source_location for ing in ingredients if ing)
    missing_status = any(ing.source_type is None for ing in ingredients if ing)
    foreign_markets = [c for c in collected["target_markets"] if c.strip().lower() != "india"]

    considerations: List[str] = []
    review_questions: List[str] = []
    missing_information = build_missing_information(ingredients, formulation, claims, evidence, markets)

    if not ingredients:
        status = "ADDITIONAL_INFORMATION_NEEDED"
        considerations.append(
            "No ingredients are recorded, so it cannot be determined whether a "
            "biological resource is used."
        )
    elif not botanicals:
        status = "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED"
        considerations.append(
            "No biological resource (botanical species) is recorded for this version, "
            "so no access-and-benefit-sharing consideration was identified from the "
            "available data."
        )
    elif wild:
        status = "REVIEW_RECOMMENDED"
        considerations.append(
            "Wild-harvested biological material is recorded. Access to wild material "
            "can raise both benefit-sharing and sustainability questions."
        )
    elif missing_origin or missing_status:
        status = "ADDITIONAL_INFORMATION_NEEDED"
        considerations.append(
            "A biological resource is recorded but its origin and/or cultivated-wild "
            "status is incomplete, so the access-and-benefit-sharing position cannot "
            "be assessed."
        )
    else:
        status = "POTENTIALLY_RELEVANT"
        considerations.append(
            "A biological resource with a recorded origin is used. Accessing a "
            "biological resource can engage access-and-benefit-sharing considerations "
            "in the source country."
        )

    if botanicals:
        considerations.append(
            "Biological resource(s): " + ", ".join(sorted(set(botanicals))) + "."
        )
    if foreign_markets:
        considerations.append(
            "The product is declared for target market(s) outside India ("
            + ", ".join(sorted(set(foreign_markets)))
            + "), which may engage those jurisdictions' own access-and-benefit-sharing "
            "regimes."
        )

    considerations.append(
        "This is preliminary screening. Whether any approval or benefit-sharing "
        "obligation applies is not determined by this platform."
    )

    review_questions = [
        "Where exactly was each biological resource obtained (country, state, supplier)?",
        "Under what arrangement was it obtained (cultivated supply, collection permit, traditional source)?",
        "Is documentation of lawful access available for each resource?",
        "Does access-and-benefit-sharing apply in the source country, and to this use?",
    ]
    if foreign_markets:
        review_questions.append(
            "Which access-and-benefit-sharing rules apply in the target markets outside India?"
        )

    if include_sources:
        query = (
            " ".join(sorted(set(botanicals))) + " access benefit sharing biological resource"
            if botanicals
            else ""
        )
        corpus_sources, retrieval_warning = _corpus_sources(db, query, user_id)
    else:
        corpus_sources, retrieval_warning = [], None
    collected["corpus_sources_requested"] = include_sources
    sources = _registry_sources() + corpus_sources

    warnings = [BIODIVERSITY_DISCLAIMER, ANALYSIS_DISCLAIMER]
    if retrieval_warning:
        warnings.append(retrieval_warning)

    result_status, label = _status(status)
    return ScreeningResult(
        kind="biodiversity_screening",
        screening_type="biodiversity",
        product_id=version.product_id,
        product_version_id=version.id,
        status=result_status,
        status_label=label,
        potential_considerations=considerations,
        missing_information=missing_information,
        review_questions=review_questions,
        sources=sources,
        collected=collected,
        explanation=_biodiversity_explanation(result_status, label, collected, missing_information),
        warnings=warnings,
    )


# ============================================
# Traditional knowledge
# ============================================

def screen_traditional_knowledge(
    version: ProductVersion,
    ingredients: Sequence[Ingredient],
    formulation: Optional[Formulation],
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    markets: Sequence[TargetMarket],
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
    include_sources: bool = False,
) -> ScreeningResult:
    """
    Screen a version for traditional-knowledge considerations.

    The status is derived from the recorded data alone; corpus retrieval
    (``include_sources``) can additionally establish whether a traditional use is
    already publicly documented.
    """
    collected = _collect(ingredients, claims, markets)
    botanicals: List[str] = collected["botanical_species"]
    traditional_claims = [
        c for c in claims if _enum_value(c.claim_type) == "traditional_use"
    ]
    tk_involvement = collected["tk_involvement"]

    if include_sources:
        query_parts = list(botanicals)
        if collected["associated_knowledge"]:
            query_parts.append(" ".join(str(k) for k in collected["associated_knowledge"]))
        query = " ".join(query_parts) + " traditional use" if query_parts else ""
        corpus_sources, retrieval_warning = _corpus_sources(db, query, user_id)
    else:
        corpus_sources, retrieval_warning = [], None

    # Only a genuine retrieved passage counts as documented traditional use. When
    # the corpus was not searched we report it as unknown rather than false.
    if include_sources:
        publicly_documented: Optional[bool] = len(corpus_sources) > 0
    else:
        publicly_documented = None
    collected["publicly_documented_traditional_use"] = publicly_documented
    collected["corpus_sources_requested"] = include_sources
    collected["corpus_sources_found"] = len(corpus_sources)
    collected["restricted_sources_excluded"] = ["TKDL"]

    considerations: List[str] = []
    missing_information = build_missing_information(ingredients, formulation, claims, evidence, markets)

    if not ingredients and not claims:
        status = "ADDITIONAL_INFORMATION_NEEDED"
        considerations.append(
            "No product information is recorded, so the traditional-knowledge position "
            "cannot be assessed."
        )
    elif not tk_involvement and not botanicals:
        status = "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED"
        considerations.append(
            "No traditional-use claim, traditional name or botanical resource is "
            "recorded, so no traditional-knowledge consideration was identified."
        )
    elif traditional_claims:
        status = "REVIEW_RECOMMENDED"
        considerations.append(
            "One or more claims are declared as traditional use. Claims with a "
            "traditional basis warrant review before disclosure or reliance."
        )
    elif tk_involvement:
        status = "POTENTIALLY_RELEVANT"
        if publicly_documented is True:
            considerations.append(
                "Traditional names or traditional-use information are recorded and "
                "public material was retrieved from the accessible corpus. Whether the "
                "knowledge is already in the public domain is a question for review."
            )
        else:
            considerations.append(
                "Traditional names or traditional-use information are recorded. Whether "
                "the use is already publicly documented was not established here; a "
                "corpus search can be requested to check."
            )
    else:
        status = "ADDITIONAL_INFORMATION_NEEDED"
        considerations.append(
            "Botanical material is recorded but no traditional-use information was "
            "supplied, so the traditional-knowledge position cannot be assessed."
        )

    if botanicals:
        considerations.append(
            "Botanical resource(s): " + ", ".join(sorted(set(botanicals))) + "."
        )
    considerations.append(
        "Restricted sources such as the TKDL are not accessed, searched or "
        "reproduced by this platform. Consult them directly through the authorised "
        "channel if relevant."
    )

    review_questions = [
        "Is any part of this product based on knowledge already published as traditional?",
        "Is the traditional use documented in a publicly available source, and where?",
        "Should the traditional-knowledge position be reviewed before any disclosure or filing?",
        "Should a search of restricted databases (e.g. TKDL) be carried out through its authorised channel?",
    ]

    # Always distinguish public, permitted and restricted sources.
    sources = _registry_sources() + corpus_sources
    restricted_present = any(s.availability == RESTRICTED_AVAILABILITY for s in sources)

    warnings = [TRADITIONAL_KNOWLEDGE_DISCLAIMER, ANALYSIS_DISCLAIMER]
    if restricted_present:
        warnings.append(
            "At least one restricted source (TKDL) is listed as unavailable. It was "
            "not accessed and no content from it appears in this result."
        )
    if retrieval_warning:
        warnings.append(retrieval_warning)

    result_status, label = _status(status)
    result = ScreeningResult(
        kind="tk_screening",
        screening_type="traditional_knowledge",
        product_id=version.product_id,
        product_version_id=version.id,
        status=result_status,
        status_label=label,
        potential_considerations=considerations,
        missing_information=missing_information,
        review_questions=review_questions,
        sources=sources,
        collected=collected,
        explanation=_tk_explanation(label, considerations, missing_information),
        warnings=warnings,
    )
    # Registry provenance travels with the result for auditability.
    result.collected["sources_version"] = SOURCES_VERSION
    return result
