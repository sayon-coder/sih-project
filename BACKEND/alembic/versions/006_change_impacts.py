"""Phase 7 - change-impact table (change_impacts).

Revision ID: 006
Revises: 005
Create Date: 2026-09-25

Phase 7 adds the formulation change-impact simulator, which compares two versions
of a product. Each run is stored here, pinned to both versions, so a historical
comparison is never rewritten when a later version is created.

The table reuses the existing ``analysisstatus`` enum (created in migration 002),
so this migration only adds the table. ``downgrade`` drops it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_impacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("old_version_id", sa.Integer(), nullable=False),
        sa.Column("new_version_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED",
                name="analysisstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="COMPLETED",
        ),
        sa.Column("results", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("review_questions", sa.Text(), nullable=True),
        sa.Column("warnings", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["old_version_id"], ["product_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["new_version_id"], ["product_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_change_impacts_id"), "change_impacts", ["id"], unique=False)
    op.create_index(op.f("ix_change_impacts_product_id"), "change_impacts", ["product_id"], unique=False)
    op.create_index(op.f("ix_change_impacts_old_version_id"), "change_impacts", ["old_version_id"], unique=False)
    op.create_index(op.f("ix_change_impacts_new_version_id"), "change_impacts", ["new_version_id"], unique=False)
    op.create_index(op.f("ix_change_impacts_status"), "change_impacts", ["status"], unique=False)
    op.create_index(op.f("ix_change_impacts_created_at"), "change_impacts", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_change_impacts_created_at"), table_name="change_impacts")
    op.drop_index(op.f("ix_change_impacts_status"), table_name="change_impacts")
    op.drop_index(op.f("ix_change_impacts_new_version_id"), table_name="change_impacts")
    op.drop_index(op.f("ix_change_impacts_old_version_id"), table_name="change_impacts")
    op.drop_index(op.f("ix_change_impacts_product_id"), table_name="change_impacts")
    op.drop_index(op.f("ix_change_impacts_id"), table_name="change_impacts")
    op.drop_table("change_impacts")
