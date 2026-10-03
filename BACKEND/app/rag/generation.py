"""
RAG answer generation with structured output and citation validation.

Pipeline:
  retrieved chunks
  → build context prompt
  → Groq LLM (JSON mode)
  → parse + Pydantic validate
  → citation validation
  → if invalid/insufficient → return controlled insufficient-evidence response
  → return StructuredRAGResponse
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from pydantic import ValidationError

from app.llm.base import LLMProvider
from app.llm.schemas import CitationObject, StructuredRAGResponse
from app.rag.citation import INSUFFICIENT_EVIDENCE_MESSAGE, validate_citations
from app.rag.jurisdiction_scope import build_scope_block
from app.rag.schemas import RetrievedChunk

logger = logging.getLogger(__name__)

# IP-SAKTI system prompt — enforces source-backed, non-hallucinated answers
SYSTEM_PROMPT = """You are IP-SAKTI Sahayak, an AI assistant specialising in Ayurveda intellectual property, regulatory guidance, traditional knowledge, and biodiversity.

WHAT YOU ALREADY HAVE ACCESS TO in this message (nothing needs to be fetched, and no external system can be queried):
- === RETRIEVED CONTEXT PASSAGES ===: passages searched from the knowledge base of this system (the documents indexed here).
- === PRODUCT CONTEXT ===: the full content of the Product Passport version the user selected in the Context Options. It IS available to you right now - answer questions about the user's product (ingredients, formulation, markets, claims, version, changes) directly from it.
- === USER-ATTACHED DOCUMENT ===: when present, the document attached to this message.

STRICT RULES:
1. Answer using the provided context: the retrieved passages and, when present, the PRODUCT CONTEXT and the attached document together.
2. If none of the provided context contains enough information to answer, set "insufficient_evidence": true and write a brief explanation in "answer".
3. Every factual claim must be cited to at least one passage, or explicitly attributed to the Product Passport (user-provided product data) or the attached document - passport and attached-document facts need no chunk citation and must never be presented as independently verified.
4. Citations must use the exact chunk_id values from the context.
5. Do NOT invent sources, URLs, page numbers, patent numbers, or legal provisions.
6. Use cautious language: "may", "potentially", "based on available evidence".
7. Do not make absolute legal, patent, regulatory, or medical conclusions.
8. When a PRODUCT CONTEXT block is present, never say you cannot access the product, its files, the product database or the knowledge base. Instead state what you do have: the selected Product Passport version and the sources retrieved for this question.

Respond ONLY with valid JSON matching this exact schema:
{
  "answer": "<your answer text>",
  "insufficient_evidence": false,
  "citations": [
    {
      "chunk_id": <int>,
      "document_id": <int>,
      "title": "<document title>",
      "source_type": "<type>",
      "relevant_text": "<exact quoted passage supporting this claim>"
    }
  ],
  "warnings": ["<any caveats or disclaimers>"]
}"""


def build_context_prompt(
    query: str,
    chunks: List[RetrievedChunk],
    product_context: Optional[Dict] = None,
    document_context: Optional[str] = None,
    jurisdiction_scope: Optional[Dict] = None,
) -> str:
    """Build the user prompt with retrieved context."""
    parts = []

    # Market context first: every rule below (structure, citations,
    # evidence gaps) is scoped to the selected target markets.
    scope_block = build_scope_block(jurisdiction_scope)
    if scope_block:
        parts.append(scope_block)
        parts.append("")

    if document_context:
        parts.append("=== USER-ATTACHED DOCUMENT ===")
        parts.append(
            "The user attached the following document. It is valid context "
            "for this question: if it answers the question, answer from it "
            "and set insufficient_evidence to false. Attached documents "
            "have no chunk ids, so keep the citations array empty and "
            "never invent chunk ids."
        )
        parts.append(document_context)
        parts.append("")

    if product_context:
        parts.append("=== PRODUCT CONTEXT ===")
        parts.append(
            "The content of the Product Passport version selected in the "
            "Context Options is provided below. It IS available to you: "
            "answer questions about this product directly from it, and "
            "never say you cannot access the product, its files or any "
            "database when this block is present. It is the user's own "
            "product data (not independently verified), so attribute such "
            "facts to \"Product Passport (user-provided)\" instead of "
            "citing a passage."
        )
        parts.append(json.dumps(product_context, indent=2, ensure_ascii=False))
        parts.append("")

    parts.append("=== RETRIEVED CONTEXT PASSAGES ===")
    parts.append(
        "These passages were searched from this system's knowledge base "
        "(indexed documents) for this question and are available to you:"
    )
    for i, chunk in enumerate(chunks, 1):
        parts.append(
            f"[Passage {i}] chunk_id={chunk.chunk_id} | document_id={chunk.document_id} | "
            f"title=\"{chunk.title}\" | type={chunk.source_type} | jurisdiction={chunk.jurisdiction or 'N/A'}"
        )
        parts.append(chunk.text)
        parts.append("")

    parts.append("=== QUESTION ===")
    parts.append(query)
    parts.append("")
    parts.append("Respond with valid JSON only.")

    return "\n".join(parts)


def generate_rag_answer(
    query: str,
    chunks: List[RetrievedChunk],
    llm: LLMProvider,
    product_context: Optional[Dict] = None,
    document_context: Optional[str] = None,
    jurisdiction_scope: Optional[Dict] = None,
    launch_question: bool = False,
    max_retries: int = 2,
) -> StructuredRAGResponse:
    """
    Generate a citation-validated RAG answer.

    Parameters
    ----------
    query:
        The user's question.
    chunks:
        Chunks returned from hybrid_retrieve (already reranked).
    llm:
        The configured LLM provider.
    product_context:
        Optional dict of product passport data to inject as context.
    document_context:
        Optional extracted text of a PDF the user attached to this
        message. Treated as trusted context even when the corpus
        retrieved nothing.
    jurisdiction_scope:
        Optional market-entry scope (selected target markets, allowed
        jurisdictions, missing information). When given, the prompt is
        prefixed with the MARKET CONTEXT rules so the answer stays
        scoped to the selected markets.
    launch_question:
        True when the question asks whether the product can be launched.
        Launch readiness needs verified market evidence: with no chunks
        and no attachment the deterministic evidence-gap answer is
        returned without consulting the model, even when a Product
        Passport is selected (the passport never proves launch readiness).
    max_retries:
        How many times to retry if the LLM returns invalid JSON.

    Returns
    -------
    StructuredRAGResponse — always a valid, citation-checked response.
    The ``insufficient_evidence`` flag is True when evidence is lacking.
    """
    # Early exit when there is neither corpus evidence nor an attachment,
    # unless a selected Product Passport can ground the answer - a passport
    # question ("what is in my product?") must reach the model. Launch
    # questions keep the deterministic path: without verified sources the
    # spec's evidence-gap answer is returned and the model is never asked
    # to fill the gap (it cannot prove launch readiness from a passport).
    if not chunks and not document_context and (
        not product_context or launch_question
    ):
        logger.info("No chunks retrieved — returning insufficient evidence response")
        return StructuredRAGResponse(
            answer=INSUFFICIENT_EVIDENCE_MESSAGE,
            citations=[],
            insufficient_evidence=True,
            warnings=["No relevant documents found in the corpus."],
        )

    user_prompt = build_context_prompt(
        query, chunks, product_context, document_context, jurisdiction_scope
    )

    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            raw = llm.generate(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
        except Exception as exc:
            logger.error("LLM call failed (attempt %d): %s", attempt, exc)
            last_error = exc
            continue

        # Parse JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("LLM returned invalid JSON (attempt %d): %s", attempt, exc)
            last_error = exc
            continue

        # Validate with Pydantic
        try:
            citations_raw = data.get("citations", [])
            citations = [CitationObject(**c) for c in citations_raw]
        except (ValidationError, TypeError) as exc:
            logger.warning("Citation schema invalid (attempt %d): %s", attempt, exc)
            last_error = exc
            continue

        insufficient = data.get("insufficient_evidence", False)
        answer = data.get("answer", "").strip()
        warnings = data.get("warnings", [])

        if insufficient or not answer:
            return StructuredRAGResponse(
                answer=INSUFFICIENT_EVIDENCE_MESSAGE if not answer else answer,
                citations=[],
                insufficient_evidence=True,
                warnings=warnings + ["The assistant indicated insufficient evidence."],
            )

        # Attachment-only answer: the corpus contributed no chunks, so
        # citations cannot be verified here and are not trusted.
        if not chunks:
            extra = []
            if citations:
                extra.append(
                    "Citations referring to the attached document were not "
                    "verified against the corpus and were omitted."
                )
            return StructuredRAGResponse(
                answer=answer,
                citations=[],
                insufficient_evidence=False,
                warnings=warnings + extra,
            )

        # Citation validation
        is_valid, valid_citations = validate_citations(citations, chunks)

        if not is_valid and not valid_citations:
            if not citations:
                # The model attached no citations at all, but sources WERE
                # retrieved for this question. Full abstention is reserved
                # for having no source (spec item 12); keep the answer and
                # state honestly that its claims carry no verified citation.
                logger.info(
                    "Model returned no citations although %d chunk(s) were "
                    "retrieved — keeping the answer with a warning",
                    len(chunks),
                )
                return StructuredRAGResponse(
                    answer=answer,
                    citations=[],
                    insufficient_evidence=False,
                    warnings=warnings + [
                        "This answer was produced from retrieved sources, but "
                        "no verifiable citations were attached — treat its "
                        "claims as unverified until cited."
                    ],
                )
            # Hard failure — every cited source is fabricated or mismatched,
            # so the answer cannot be trusted.
            logger.warning("All citations failed validation — returning insufficient evidence")
            return StructuredRAGResponse(
                answer=INSUFFICIENT_EVIDENCE_MESSAGE,
                citations=[],
                insufficient_evidence=True,
                warnings=warnings + ["Citation validation failed — no verified sources available."],
            )

        # Partial success — use valid citations only
        if not is_valid:
            warnings = warnings + [
                "Some citations could not be verified and were removed. "
                "The answer may be partially supported."
            ]

        return StructuredRAGResponse(
            answer=answer,
            citations=valid_citations,
            insufficient_evidence=False,
            warnings=warnings,
        )

    # All retries failed
    logger.error("RAG generation failed after %d attempts: %s", max_retries, last_error)
    return StructuredRAGResponse(
        answer=INSUFFICIENT_EVIDENCE_MESSAGE,
        citations=[],
        insufficient_evidence=True,
        warnings=["The AI system encountered an error. Please try again."],
    )
