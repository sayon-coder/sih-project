"""
Claim-to-evidence analyzer (Phase 5).

Pipeline, per the master prompt's structured-AI-output section:

    claims + corpus
      -> hybrid retrieval (one search per claim)
      -> Groq LLM (JSON mode)
      -> Pydantic validation
      -> citation validation (only chunks that were actually retrieved)
      -> evidence-status clamp (the provenance firewall)
      -> ClaimAnalysisResult

Two properties matter more than the model's quality:

* **The model cannot cite anything it was not given.** Metadata for every
  citation is looked up server-side from the retrieved chunk.
* **The model cannot promote a claim.** ``clamp_ai_evidence_status`` caps the
  suggested status at ``partially_supported``; ``supported`` and
  ``expert_verified`` remain reachable only through human review. Claims already
  marked ``EXPERT_VERIFIED`` are returned untouched and flagged as locked.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Sequence

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.analysis.prompts import CLAIM_ANALYSIS_SYSTEM_PROMPT, NO_EVIDENCE_NOTE
from app.analysis.schemas import (
    AnalysisCitation,
    ClaimAnalysisLLMOutput,
    ClaimAnalysisResult,
    ClaimAssessment,
    SignalExplanation,
)
from app.llm.provider import get_llm_provider
from app.llm.schemas import CitationObject
from app.models import Claim, Evidence, ProductVersion
from app.rag.citation import validate_citations
from app.rag.retrieval import hybrid_retrieve
from app.rag.schemas import MetadataFilter, RetrievedChunk
from app.services.provenance import (
    AI_ANALYSIS_PROVENANCE,
    clamp_ai_evidence_status,
    is_expert_verified,
)

logger = logging.getLogger(__name__)

#: How many passages to retrieve per claim before reranking.
PASSAGES_PER_CLAIM = 4

#: Values the model is told to use for risk; anything else falls back to medium.
_ALLOWED_RISK = {"low", "medium", "high"}


def _claim_value(claim: Claim) -> str:
    """Serialise a Claim's evidence_status enum to its string value."""
    status = claim.evidence_status
    return status.value if hasattr(status, "value") else str(status)


def _has_verified_evidence(evidence: Sequence[Evidence]) -> bool:
    """True when at least one evidence document on the version is verified."""
    for doc in evidence:
        status = doc.verification_status
        status = status.value if hasattr(status, "value") else str(status)
        if status == "verified":
            return True
    return False


def _claim_standing(claim: Claim, has_verified_evidence: bool) -> Dict[str, object]:
    """
    Deterministic claim-level standing (spec item 1, requirement 5).

    Computed from stored rows only - independent of anything the model said.
    """
    current = _claim_value(claim)
    if is_expert_verified(claim) or current == "expert_verified":
        return {
            "claim_provenance": claim.provenance or "EXPERT_VERIFIED",
            "evidence_status": "EXPERT_VERIFIED",
            "independent_verification": "EXPERT_VERIFIED",
            "review_required": False,
            "reason": (
                "This claim is EXPERT_VERIFIED by the expert workflow; it is "
                "returned locked and needs no further review."
            ),
        }
    if not has_verified_evidence:
        return {
            "claim_provenance": claim.provenance or "USER_PROVIDED",
            "evidence_status": "USER_PROVIDED_ONLY",
            "independent_verification": "NOT_FOUND",
            "review_required": True,
            "reason": (
                "The claim was entered by the user and no independently verified "
                "supporting evidence was retrieved."
            ),
        }
    return {
        "claim_provenance": claim.provenance or "USER_PROVIDED",
        "evidence_status": "EVIDENCE_ON_RECORD",
        "independent_verification": "EVIDENCE_ON_RECORD",
        "review_required": True,
        "reason": (
            "Verified evidence is recorded on this version; confirm that it "
            "supports this specific claim before relying on it."
        ),
    }


def _claim_explanation(result: "ClaimAnalysisResult") -> "SignalExplanation":
    """Build the claim-review "Why this result?" block (spec item 9)."""
    only_user_provided = all(
        a.evidence_status == "USER_PROVIDED_ONLY" for a in result.assessments
    )
    if only_user_provided:
        why = (
            "The claim result(s) are user-provided and no independent evidence "
            "was attached."
        )
    else:
        why = (
            "Claim standing was computed from the claims and evidence recorded "
            "on this product version."
        )
    missing: List[str] = []
    for assessment in _collect_missing_evidence(result):
        if assessment not in missing:
            missing.append(assessment)
    if only_user_provided:
        missing.append("Independently verified evidence for these claims.")
    return SignalExplanation(
        signal="Claim review required.",
        why=why,
        missing=missing[:6],
        limit=(
            "This review cannot make a claim supported or expert-verified, and it "
            "is not medical, regulatory or legal advice."
        ),
    )


def _collect_missing_evidence(result: "ClaimAnalysisResult") -> List[str]:
    """Flatten the per-claim missing-evidence notes, de-duplicated."""
    out: List[str] = []
    for assessment in result.assessments:
        for entry in assessment.missing_evidence:
            if entry not in out:
                out.append(entry)
    return out


def _retrieve_for_claim(db: Session, claim: Claim, user_id: Optional[int]) -> List[RetrievedChunk]:
    """Retrieve corpus passages relevant to a single claim."""
    try:
        return hybrid_retrieve(
            db=db,
            query=claim.claim_text,
            filters=MetadataFilter(),
            user_id=user_id,
            top_k_final=PASSAGES_PER_CLAIM,
        )
    except Exception as exc:  # retrieval failure must not fail the whole review
        logger.warning("Retrieval failed for claim %s: %s", claim.id, exc)
        return []


def _build_prompt(
    version: ProductVersion,
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    passages: Dict[int, List[RetrievedChunk]],
) -> str:
    """Assemble the user prompt: product data, claims, and per-claim passages."""
    parts: List[str] = []

    parts.append("=== PRODUCT VERSION ===")
    parts.append(f"version_id={version.id} version_number={version.version_number}")
    parts.append("")

    if evidence:
        parts.append("=== EVIDENCE DOCUMENTS DECLARED BY THE USER ===")
        for ev in evidence:
            ev_type = ev.evidence_type.value if hasattr(ev.evidence_type, "value") else ev.evidence_type
            parts.append(
                f"- evidence_id={ev.id} | title=\"{ev.title}\" | type={ev_type} | "
                f"verification_status="
                f"{ev.verification_status.value if hasattr(ev.verification_status, 'value') else ev.verification_status}"
            )
        parts.append("")

    parts.append("=== CLAIMS TO REVIEW ===")
    for claim in claims:
        claim_type = claim.claim_type.value if hasattr(claim.claim_type, "value") else claim.claim_type
        parts.append(f"claim_id={claim.id} | type={claim_type or 'unspecified'}")
        parts.append(f"claim_text: {claim.claim_text}")
        if claim.evidence_notes:
            parts.append(f"declarant_notes: {claim.evidence_notes}")

        claim_passages = passages.get(claim.id) or []
        if claim_passages:
            parts.append("--- passages retrieved for this claim ---")
            for chunk in claim_passages:
                parts.append(
                    f"chunk_id={chunk.chunk_id} | document_id={chunk.document_id} | "
                    f"title=\"{chunk.title}\" | type={chunk.source_type} | "
                    f"jurisdiction={chunk.jurisdiction or 'N/A'}"
                )
                parts.append(chunk.text)
        else:
            parts.append("--- no passages were found in the corpus for this claim ---")
        parts.append("")

    parts.append(
        "Return one assessment object per claim_id above. "
        "Respond with valid JSON only."
    )
    return "\n".join(parts)


def _resolve_citations(
    chunk_ids: Sequence[int],
    passages: Sequence[RetrievedChunk],
) -> tuple[List[AnalysisCitation], bool]:
    """
    Turn model-supplied chunk ids into citations with server-side metadata.

    Reuses the Phase 4 validator so a chunk id that was not retrieved for this
    claim is dropped rather than trusted. Returns (citations, had_invalid_ids).
    """
    if not chunk_ids:
        return [], False

    by_id = {c.chunk_id: c for c in passages}
    wanted = [cid for cid in chunk_ids if cid in by_id]

    if not wanted:
        return [], bool(chunk_ids)

    # Build citation objects using the *real* chunk titles so the validator's
    # title check is satisfied only by genuine membership.
    proposed = [
        CitationObject(
            chunk_id=cid,
            document_id=by_id[cid].document_id,
            title=by_id[cid].title,
            source_type=by_id[cid].source_type,
            relevant_text=by_id[cid].text[:500],
        )
        for cid in wanted
    ]

    is_valid, valid = validate_citations(proposed, list(passages))

    citations = [
        AnalysisCitation(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            title=c.title,
            source_type=c.source_type,
            jurisdiction=c.jurisdiction,
            publication_date=c.publication_date,
            page_number=c.page_number,
            url=c.url,
            relevant_text=c.relevant_text,
        )
        for c in valid
    ]

    dropped = bool(chunk_ids) and (not is_valid or len(valid) != len(chunk_ids))
    return citations, dropped


def analyze_claims_content(
    db: Session,
    version: ProductVersion,
    claims: Sequence[Claim],
    evidence: Sequence[Evidence],
    user_id: Optional[int] = None,
) -> ClaimAnalysisResult:
    """
    Run a claim-to-evidence review for a version.

    Raises:
        Exception: whatever the LLM provider raises. The caller decides how to
            surface a provider outage; this function never fabricates a result.
        ValueError: when the model's JSON cannot be parsed or validated at all.
    """
    result = ClaimAnalysisResult(
        product_id=version.product_id,
        product_version_id=version.id,
        claim_count=len(claims),
    )

    if not claims:
        result.claim_status = "NO_CLAIMS_RECORDED"
        result.summary = "This product version has no claims to review."
        result.warnings.append(
            "No claims were found on this version, so there was nothing to assess. "
            "Add claims and run the review again."
        )
        result.explanation = SignalExplanation(
            signal="No claims recorded.",
            why="This product version has no claims on record, so there was nothing to assess.",
            missing=["Claims for this product version"],
            limit=(
                "NO_CLAIMS_RECORDED applies only to this product version; claims on "
                "other versions are unaffected."
            ),
        )
        return result

    # -------------------------------------------------------
    # 1. Resolve the LLM provider first
    # -------------------------------------------------------
    # Retrieval (embedding + reranking) is the expensive part of this pipeline,
    # so an unavailable AI provider should fail before any of it is paid for.
    llm = get_llm_provider()

    # -------------------------------------------------------
    # 2. Retrieve passages per claim
    # -------------------------------------------------------
    passages: Dict[int, List[RetrievedChunk]] = {
        claim.id: _retrieve_for_claim(db, claim, user_id) for claim in claims
    }

    # -------------------------------------------------------
    # 3. LLM structured output
    # -------------------------------------------------------
    raw = llm.generate(
        system_prompt=CLAIM_ANALYSIS_SYSTEM_PROMPT,
        user_prompt=_build_prompt(version, claims, evidence, passages),
    )

    try:
        parsed = ClaimAnalysisLLMOutput(**json.loads(raw))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ValueError(f"The AI returned malformed analysis output: {exc}") from exc

    by_claim = {item.claim_id: item for item in parsed.assessments}
    invalid_citation_seen = False
    has_verified_evidence = _has_verified_evidence(evidence)

    # -------------------------------------------------------
    # 4. Clamp, validate citations, build assessments
    # -------------------------------------------------------
    for claim in claims:
        current = _claim_value(claim)

        # Expert-verified claims are locked: the AI is not allowed to touch them.
        if is_expert_verified(claim) or current == "expert_verified":
            result.assessments.append(
                ClaimAssessment(
                    claim_id=claim.id,
                    claim_text=claim.claim_text,
                    claim_type=claim.claim_type.value if hasattr(claim.claim_type, "value") else claim.claim_type,
                    current_evidence_status=current,
                    suggested_evidence_status=current,
                    risk_level=claim.risk_level or "medium",
                    review_status=claim.review_status or "verified",
                    rationale=(
                        "This claim is EXPERT_VERIFIED. The AI does not assess or alter "
                        "expert-verified information."
                    ),
                    provenance=claim.provenance or "EXPERT_VERIFIED",
                    expert_verified_locked=True,
                    **_claim_standing(claim, has_verified_evidence),
                )
            )
            continue

        item = by_claim.get(claim.id)
        claim_passages = passages.get(claim.id) or []

        if item is None:
            result.warnings.append(
                f"The AI did not return an assessment for claim {claim.id}; "
                "it was recorded as needing evidence."
            )
            suggested = "needs_evidence"
            risk = claim.risk_level or "medium"
            rationale = NO_EVIDENCE_NOTE
            missing: List[str] = ["No assessment was produced for this claim."]
            citations: List[AnalysisCitation] = []
        else:
            suggested = clamp_ai_evidence_status(item.suggested_evidence_status)
            risk = item.risk_level if item.risk_level in _ALLOWED_RISK else "medium"
            rationale = item.rationale
            missing = list(item.missing_evidence)
            citations, dropped = _resolve_citations(item.citation_chunk_ids, claim_passages)
            invalid_citation_seen = invalid_citation_seen or dropped

        # A claim can never be *downgraded* from an already stronger user stance,
        # but the AI suggestion is advisory and never written back to the claim.
        result.assessments.append(
            ClaimAssessment(
                claim_id=claim.id,
                claim_text=claim.claim_text,
                claim_type=claim.claim_type.value if hasattr(claim.claim_type, "value") else claim.claim_type,
                current_evidence_status=current,
                suggested_evidence_status=suggested,
                risk_level=risk,
                review_status=_review_status_for(risk, suggested),
                rationale=rationale,
                missing_evidence=missing,
                citations=citations,
                provenance=AI_ANALYSIS_PROVENANCE,
                **_claim_standing(claim, has_verified_evidence),
            )
        )

    # -------------------------------------------------------
    # 5. Summary + warnings
    # -------------------------------------------------------
    result.summary = parsed.summary or _default_summary(result.assessments)
    result.warnings.extend(parsed.warnings)

    if invalid_citation_seen:
        result.warnings.append(
            "Some citations suggested by the AI did not match the passages actually "
            "retrieved and were removed. Affected claims may be less well supported "
            "than the wording suggests."
        )

    uncited = [a for a in result.assessments if not a.citations and not a.expert_verified_locked]
    if uncited:
        result.warnings.append(
            f"{len(uncited)} of {len(result.assessments)} claims have no citation in the "
            "accessible corpus. Those claims remain as declared and need evidence."
        )

    result.explanation = _claim_explanation(result)
    return result


def _review_status_for(risk: str, suggested: str) -> str:
    """Map a risk/status pair onto a review-workflow-facing status label."""
    if risk == "high":
        return "review_recommended"
    if suggested == "partially_supported":
        return "review_recommended"
    return "pending"


def _default_summary(assessments: Sequence[ClaimAssessment]) -> str:
    """Fallback summary when the model did not provide one."""
    if not assessments:
        return "No claims were assessed."
    needs = sum(1 for a in assessments if a.suggested_evidence_status == "needs_evidence")
    partial = sum(1 for a in assessments if a.suggested_evidence_status == "partially_supported")
    high = sum(1 for a in assessments if a.risk_level == "high")
    return (
        f"Reviewed {len(assessments)} claim(s): {needs} need evidence, "
        f"{partial} are partially supported by the accessible corpus, "
        f"{high} carry high risk and are recommended for expert review."
    )
