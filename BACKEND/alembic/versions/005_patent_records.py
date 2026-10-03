"""Phase 6 - patent screening tables (patent_records, patent_features).

Revision ID: 005
Revises: 004
Create Date: 2026-09-25

Phase 6 adds the patent-screening workflow. When a user screens a product
version, the candidate records identified for *that version* are stored here,
together with the technical features that were compared. Both tables are pinned
to ``product_versions`` with ``ON DELETE CASCADE`` so removing a version removes
its screenings.

The ``analysistype`` enum already contains the Phase 6 labels
(``IP_ROUTE_MAP``, ``PATENT_SCREENING``, ``BIODIVERSITY_SCREENING``,
``TK_SCREENING``) because they were created with the enum in migration 002, so
this migration only adds tables. ``downgrade`` drops them.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patent_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_version_id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.String(length=120), nullable=False),
        sa.Column("patent_number", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("assignee", sa.String(length=255), nullable=True),
        sa.Column("jurisdiction", sa.String(length=100), nullable=True),
        sa.Column("publication_date", sa.String(length=40), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_passage", sa.Text(), nullable=True),
        sa.Column("record_source", sa.String(length=40), nullable=False, server_default="DEMO_CORPUS"),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("corpus_version", sa.String(length=50), nullable=True),
        sa.Column("relevance_label", sa.String(length=60), nullable=False, server_default="Further Review Recommended"),
        sa.Column("similarity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("similarity_band", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("uncertainty", sa.Text(), nullable=True),
        sa.Column("provenance", sa.String(length=50), nullable=False, server_default="AI_ANALYSIS"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_version_id"], ["product_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_patent_records_id"), "patent_records", ["id"], unique=False)
    op.create_index(op.f("ix_patent_records_product_version_id"), "patent_records", ["product_version_id"], unique=False)
    op.create_index(op.f("ix_patent_records_record_id"), "patent_records", ["record_id"], unique=False)
    op.create_index(op.f("ix_patent_records_record_source"), "patent_records", ["record_source"], unique=False)

    op.create_table(
        "patent_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patent_record_id", sa.Integer(), nullable=False),
        sa.Column("feature_type", sa.String(length=60), nullable=False),
        sa.Column("feature_value", sa.String(length=500), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("user_value", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["patent_record_id"], ["patent_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patent_record_id", "feature_type", "feature_value", name="uq_patent_feature"),
    )
    op.create_index(op.f("ix_patent_features_id"), "patent_features", ["id"], unique=False)
    op.create_index(op.f("ix_patent_features_patent_record_id"), "patent_features", ["patent_record_id"], unique=False)
    op.create_index(op.f("ix_patent_features_feature_type"), "patent_features", ["feature_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_patent_features_feature_type"), table_name="patent_features")
    op.drop_index(op.f("ix_patent_features_patent_record_id"), table_name="patent_features")
    op.drop_index(op.f("ix_patent_features_id"), table_name="patent_features")
    op.drop_table("patent_features")

    op.drop_index(op.f("ix_patent_records_record_source"), table_name="patent_records")
    op.drop_index(op.f("ix_patent_records_record_id"), table_name="patent_records")
    op.drop_index(op.f("ix_patent_records_product_version_id"), table_name="patent_records")
    op.drop_index(op.f("ix_patent_records_id"), table_name="patent_records")
    op.drop_table("patent_records")
