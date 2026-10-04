"""
Citation validation.

Every answer produced by the RAG pipeline must cite only chunks that were
actually retrieved.  This module validates that:

  1. Each citation references a chunk_id in the retrieved set.
  2. The title and source_type in the citation match the real chunk.

If validation fails, the answer is replaced with the insufficient-evidence
controlled response rather than letting a hallucinated citation reach the user.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Set, Tuple

from app.llm.schemas import CitationObject
from app.rag.schemas import RetrievedChunk

# Render jurisdiction codes ("IN", "INT") as human names ("India",
# "International") so a citation never shows an ambiguous code (spec item 7).
from app.analysis.ip_schemas import human_jurisdiction

logger = logging.getLogger(__name__)

INSUFFICIENT_EVIDENCE_MESSAGE = (
    "Insufficient evidence in the current verified corpus to answer this question. "
    "The available documents do not contain enough relevant information. "
    "Please consult qualified legal, patent, or regulatory professionals for advice specific to your situation.\n\n"
    "This platform provides preliminary, source-backed information and decision support. "
    "It does not constitute legal, patent, regulatory, medical, or government advice or approval."
)


def validate_citations(
    answer_citations: List[CitationObject],
    retrieved_chunks: List[RetrievedChunk],
) -> Tuple[bool, List[CitationObject]]:
    """
    Validate that all citations reference actually retrieved chunks.

    Parameters
    ----------
    answer_citations:
        Citations the LLM included in its structured response.
    retrieved_chunks:
        Chunks returned by hybrid_retrieve() and passed to the LLM.

    Returns
    -------
    (is_valid, valid_citations)
        ``is_valid`` is True only when ALL citations are valid.
        ``valid_citations`` contains only the citations that passed validation.
    """
    if not retrieved_chunks:
        logger.warning("Citation validation: no retrieved chunks — treating as insufficient evidence")
        return False, []

    # Build lookup by chunk_id
    chunk_by_id: Dict[int, RetrievedChunk] = {c.chunk_id: c for c in retrieved_chunks}
    retrieved_ids: Set[int] = set(chunk_by_id.keys())

    valid: List[CitationObject] = []
    all_valid = True

    for citation in answer_citations:
        if citation.chunk_id not in retrieved_ids:
            logger.warning(
                "Citation validation FAILED: chunk_id=%d not in retrieved set %s",
                citation.chunk_id,
                sorted(retrieved_ids),
            )
            all_valid = False
            continue

        real_chunk = chunk_by_id[citation.chunk_id]

        # Verify title matches (case-insensitive prefix match)
        if not _titles_match(citation.title, real_chunk.title):
            logger.warning(
                "Citation title mismatch: cited='%s', real='%s' (chunk_id=%d)",
                citation.title,
                real_chunk.title,
                citation.chunk_id,
            )
            all_valid = False
            continue

        # Fill in real metadata from the retrieved chunk
        citation.document_id = real_chunk.document_id
        citation.source_type = real_chunk.source_type
        citation.jurisdiction = human_jurisdiction(real_chunk.jurisdiction)
        citation.publication_date = real_chunk.publication_date
        citation.url = real_chunk.source_url
        citation.page_number = real_chunk.page_number

        valid.append(citation)

    _attach_confidence(valid, chunk_by_id)

    if not valid:
        all_valid = False

    logger.debug(
        "Citation validation: %d/%d citations valid",
        len(valid),
        len(answer_citations),
    )
    return all_valid, valid


#: Confidence tier cut-offs on the batch-relative score (see below).
HIGH_CUTOFF = 0.66
MEDIUM_CUTOFF = 0.33


def _attach_confidence(
    citations: List[CitationObject],
    chunk_by_id: Dict[int, RetrievedChunk],
) -> None:
    """Stamp the SIH confidence indicator on validated citations.

    Raw retrieval scores are uncalibrated (cross-encoder logits or RRF
    sums), so they are min-max normalised across the cited chunks of THIS
    answer only: ``confidence_score`` is the relative match strength in
    [0, 1] and the label tiers it. A single citation (or a zero spread) is
    the best evidence available for its answer, hence HIGH. The score is
    deliberately NOT a probability and is NOT comparable across answers.
    """
    if not citations:
        return
    raw = [chunk_by_id[c.chunk_id].final_score for c in citations]
    lo, hi = min(raw), max(raw)
    span = hi - lo
    for citation, score in zip(citations, raw):
        norm = 1.0 if span <= 0 else (score - lo) / span
        norm = round(max(0.0, min(1.0, norm)), 3)
        citation.confidence_score = norm
        citation.confidence_label = (
            "HIGH" if norm >= HIGH_CUTOFF
            else "MEDIUM" if norm >= MEDIUM_CUTOFF
            else "LOW"
        )


def _titles_match(cited_title: str, real_title: str) -> bool:
    """Fuzzy title match — allow the LLM to shorten the title slightly."""
    cited = cited_title.lower().strip()
    real = real_title.lower().strip()
    # Exact match, or one is a prefix/substring of the other
    return cited == real or cited in real or real[:40] in cited
