"""Phase 4 - pgvector extension + RAG tables.

Revision ID: 003
Revises: 002
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Enable pgvector extension
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ------------------------------------------------------------------
    # 2. source_documents  (admin corpus + user-uploaded documents)
    # ------------------------------------------------------------------
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column(
            "source_type",
            sa.String(80),
            nullable=False,
            comment="patent|law|regulation|official_guidance|scientific_paper|traditional_knowledge|other",
        ),
        sa.Column("jurisdiction", sa.String(100), nullable=True),
        sa.Column("language", sa.String(20), nullable=False, server_default="en"),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column(
            "document_hash",
            sa.String(64),
            nullable=True,
            unique=True,
            comment="SHA-256 hex; used for duplicate detection",
        ),
        sa.Column(
            "uploader_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="True = visible to all users in RAG; False = only uploader",
        ),
        sa.Column(
            "corpus_version",
            sa.String(50),
            nullable=True,
            comment="e.g. v1.0 or demo-2026-09",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="PENDING",
            comment="PENDING|INDEXING|INDEXED|FAILED",
        ),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            onupdate=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index("ix_source_documents_status", "source_documents", ["status"])
    op.create_index("ix_source_documents_source_type", "source_documents", ["source_type"])
    op.create_index("ix_source_documents_uploader_id", "source_documents", ["uploader_id"])
    op.create_index("ix_source_documents_is_public", "source_documents", ["is_public"])

    # ------------------------------------------------------------------
    # 3. source_chunks  (text chunks with dense vector + tsvector)
    # ------------------------------------------------------------------
    op.create_table(
        "source_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column(
            "embedding",
            postgresql.ARRAY(sa.Float()),
            nullable=True,
            comment="BGE-M3 dense embedding (1024-dim); stored as float array for pgvector ops",
        ),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            nullable=True,
            comment="PostgreSQL full-text search vector",
        ),
        sa.Column("metadata_json", sa.Text(), nullable=True, comment="JSON: source_type, jurisdiction, language, etc."),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_source_chunks_document_id", "source_chunks", ["document_id"])
    op.create_index("ix_source_chunks_chunk_index", "source_chunks", ["chunk_index"])

    # GIN index for full-text search
    op.create_index(
        "ix_source_chunks_search_vector",
        "source_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )

    # ------------------------------------------------------------------
    # 4. Vector index using pgvector operator class
    #    We use a plain column + cast to vector type at query time.
    #    The IVFFlat index is created after data is loaded; skip for now.
    #    (Can be added with: CREATE INDEX ... USING ivfflat (embedding::vector(1024)) WITH (lists=100))
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 5. chat_sessions
    # ------------------------------------------------------------------
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "product_version_id",
            sa.Integer(),
            sa.ForeignKey("product_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            onupdate=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    # ------------------------------------------------------------------
    # 6. chat_messages
    # ------------------------------------------------------------------
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            comment="user | assistant",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations_json",
            sa.Text(),
            nullable=True,
            comment="JSON array of CitationObject",
        ),
        sa.Column(
            "sources_json",
            sa.Text(),
            nullable=True,
            comment="JSON array of source metadata",
        ),
        sa.Column(
            "insufficient_evidence",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("language", sa.String(20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("source_chunks")
    op.drop_table("source_documents")
    # Note: we do NOT drop the vector extension as it may be used elsewhere
