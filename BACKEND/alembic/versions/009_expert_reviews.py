"""Phase 9 - expert review tables.

Revision ID: 009
Revises: 008
Create Date: 2026-09-26

Phase 9 adds the expert review workflow: ``expert_reviews`` (one row per
review of a product version, carrying the workflow status) and
``review_comments`` (preserved reviewer discussion). ``downgrade`` drops both
tables and the enum type.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expert_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("product_version_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "AI_SCREENED",
                "REVIEW_REQUIRED",
                "EXPERT_REVIEW",
                "CORRECTION_REQUESTED",
                "RESUBMITTED",
                "REVIEWED",
                "ARCHIVED",
                name="reviewstatus",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ai_screen_summary", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("assigned_expert_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["product_version_id"], ["product_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["assigned_expert_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_expert_reviews_id"), "expert_reviews", ["id"], unique=False)
    op.create_index(
        op.f("ix_expert_reviews_product_id"), "expert_reviews", ["product_id"], unique=False
    )
    op.create_index(
        op.f("ix_expert_reviews_product_version_id"),
        "expert_reviews",
        ["product_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_expert_reviews_status"), "expert_reviews", ["status"], unique=False
    )

    op.create_table(
        "review_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["review_id"], ["expert_reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_review_comments_id"), "review_comments", ["id"], unique=False)
    op.create_index(
        op.f("ix_review_comments_review_id"), "review_comments", ["review_id"], unique=False
    )


def downgrade() -> None:
    op.drop_table("review_comments")
    op.drop_table("expert_reviews")
    op.execute("DROP TYPE IF EXISTS reviewstatus")
