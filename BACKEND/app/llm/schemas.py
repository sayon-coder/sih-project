"""Pydantic schemas for LLM responses and RAG structured output."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class CitationObject(BaseModel):
    """A single validated citation in an assistant answer."""
    chunk_id: int = Field(..., description="ID of the SourceChunk that was retrieved")
    document_id: int
    title: str
    source_type: str
    jurisdiction: Optional[str] = None
    publication_date: Optional[str] = None
    page_number: Optional[int] = None
    relevant_text: str = Field(..., description="The exact passage from the chunk that supports the answer")
    url: Optional[str] = None
    # ── Confidence indicator (SIH requirement: "mandatory source citations with
    #    a confidence indicator").  Populated from the cross-encoder reranker
    #    score (0.0 – 1.0); label is the human-readable tier shown in the UI.
    confidence_score: Optional[float] = Field(
        None,
        ge=0.0, le=1.0,
        description="Reranker similarity score (0–1). None when score unavailable.",
    )
    confidence_label: Optional[str] = Field(
        None,
        description="Human-readable confidence tier: HIGH | MEDIUM | LOW",
    )


class StructuredRAGResponse(BaseModel):
    """The validated, citation-checked response from the RAG pipeline."""
    answer: str
    citations: List[CitationObject] = Field(default_factory=list)
    insufficient_evidence: bool = False
    warnings: List[str] = Field(default_factory=list)
    language: str = "en"
