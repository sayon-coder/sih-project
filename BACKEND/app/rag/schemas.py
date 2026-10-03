"""Pydantic schemas for the RAG pipeline internal types."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ParsedDocument(BaseModel):
    """Output of the document parser."""
    text: str
    pages: List[Dict[str, Any]] = Field(default_factory=list)
    num_pages: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """A single text chunk ready for embedding."""
    text: str
    chunk_index: int
    page_number: Optional[int] = None
    token_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    """A chunk returned by hybrid retrieval, with scores."""
    chunk_id: int
    document_id: int
    title: str
    source_type: str
    jurisdiction: Optional[str] = None
    language: str = "en"
    publication_date: Optional[str] = None
    source_url: Optional[str] = None
    text: str
    page_number: Optional[int] = None
    vector_score: float = 0.0
    keyword_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None
    final_score: float = 0.0


class MetadataFilter(BaseModel):
    """Filters for RAG retrieval."""
    source_types: Optional[List[str]] = None
    jurisdictions: Optional[List[str]] = None
    language: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    uploader_id: Optional[int] = None      # None = no uploader filter
    include_public: bool = True
    include_private: bool = False
