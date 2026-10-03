"""
SQLAlchemy models for the RAG subsystem.
Covers: SourceDocument, SourceChunk, ChatSession, ChatMessage.

The embedding and search_vector columns use dialect-aware type decorators so
the models can be used with both PostgreSQL (production) and SQLite (tests).
"""
from __future__ import annotations

import enum
import json
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, TypeDecorator,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, TSVECTOR as PG_TSVECTOR
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# ============================================================
# Dialect-aware column types (PostgreSQL in prod, Text in SQLite tests)
# ============================================================

class EmbeddingType(TypeDecorator):
    """Stores a float list as a PostgreSQL ARRAY(Float) on Postgres, or JSON Text on SQLite."""
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(Float))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value  # pass list directly to pg ARRAY
        if value is None:
            return None
        return json.dumps(value)  # store as JSON text in SQLite

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return json.loads(value)


class TSVectorType(TypeDecorator):
    """PostgreSQL TSVECTOR on Postgres, nullable Text on SQLite (FTS not used in tests)."""
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_TSVECTOR())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        return value  # pass-through for both dialects

    def process_result_value(self, value, dialect):
        return value


class DocumentSourceType(str, enum.Enum):
    PATENT = "patent"
    LAW = "law"
    REGULATION = "regulation"
    OFFICIAL_GUIDANCE = "official_guidance"
    SCIENTIFIC_PAPER = "scientific_paper"
    TRADITIONAL_KNOWLEDGE = "traditional_knowledge"
    OTHER = "other"


class DocumentStatus(str, enum.Enum):
    PENDING = "PENDING"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


# ============================================================
# SourceDocument
# ============================================================

class SourceDocument(Base):
    """A document in the knowledge corpus (admin or user-uploaded)."""

    __tablename__ = "source_documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    source_type = Column(String(80), nullable=False, index=True)
    jurisdiction = Column(String(100), nullable=True)
    language = Column(String(20), nullable=False, default="en")
    author = Column(String(255), nullable=True)
    publication_date = Column(Date, nullable=True)
    source_url = Column(Text, nullable=True)
    file_path = Column(Text, nullable=True)
    document_hash = Column(String(64), nullable=True, unique=True)

    # Ownership / visibility
    uploader_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_public = Column(Boolean, nullable=False, default=False)

    # Corpus tracking
    corpus_version = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")
    chunk_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    chunks = relationship("SourceChunk", back_populates="document", cascade="all, delete-orphan")
    uploader = relationship("User", foreign_keys=[uploader_id])

    def __repr__(self) -> str:
        return f"<SourceDocument(id={self.id}, title={self.title!r}, status={self.status})>"


# ============================================================
# SourceChunk
# ============================================================

class SourceChunk(Base):
    """
    A text chunk derived from a SourceDocument.

    The ``embedding`` column stores the BGE-M3 dense vector as a
    PostgreSQL float array.  At query time we cast it to ``vector(1024)``
    using pgvector's ``<=>`` (cosine) or ``<#>`` (inner-product) operators.

    ``search_vector`` is a pre-computed tsvector for BM25/FTS queries.
    """

    __tablename__ = "source_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        Integer,
        ForeignKey("source_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    page_number = Column(Integer, nullable=True)

    # Dense vector stored as float[] for compatibility; cast to vector at query time
    embedding = Column(EmbeddingType, nullable=True)

    # Full-text search
    search_vector = Column(TSVectorType, nullable=True)

    # Denormalized metadata (JSON) for efficient filtering without joins
    metadata_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    document = relationship("SourceDocument", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<SourceChunk(id={self.id}, doc_id={self.document_id}, idx={self.chunk_index})>"


# ============================================================
# ChatSession
# ============================================================

class ChatSession(Base):
    """A conversation session between a user and the IP-SAKTI assistant."""

    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=True)

    # Optional product context
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product_version_id = Column(
        Integer, ForeignKey("product_versions.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan",
                            order_by="ChatMessage.created_at")
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<ChatSession(id={self.id}, user_id={self.user_id})>"


# ============================================================
# ChatMessage
# ============================================================

class ChatMessage(Base):
    """A single message within a ChatSession."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String(20), nullable=False, comment="user | assistant")
    content = Column(Text, nullable=False)
    citations_json = Column(Text, nullable=True)   # JSON array
    sources_json = Column(Text, nullable=True)     # JSON array
    insufficient_evidence = Column(Boolean, nullable=False, default=False)
    language = Column(String(20), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage(id={self.id}, session_id={self.session_id}, role={self.role})>"


# ============================================================
# ChatAttachment
# ============================================================

class ChatAttachment(Base):
    """A PDF attached to a chat message; stores the extracted plain text.

    Uploaded before (or with) a message and bound to the conversation on the
    first message that references it, so follow-up questions in the same
    session reuse the document without re-uploading.
    """

    __tablename__ = "chat_attachments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(
        Integer, ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename = Column(String(255), nullable=False)
    extracted_text = Column(Text, nullable=False)   # plain text parsed from the PDF
    char_count = Column(Integer, nullable=False, default=0)
    truncated = Column(Boolean, nullable=False, default=False)
    # Corpus document holding this attachment's page-aware chunks (so the
    # text is retrievable, not only prompt-injected). NULL for rows
    # uploaded before indexing existed and when indexing was skipped.
    document_id = Column(
        Integer,
        ForeignKey("source_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    session = relationship("ChatSession", backref="attachments")
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<ChatAttachment(id={self.id}, user_id={self.user_id}, "
            f"session_id={self.session_id}, filename={self.filename!r})>"
        )
