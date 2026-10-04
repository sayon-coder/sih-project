"""Clarification answers for the interactive classification loop.

Revision ID: 014
Revises: 013
Create Date: 2026-10-03

Creates ``clarification_answers`` exactly as
``app.models.clarification_models`` defines it: one recorded answer per
(product version, question key). Answer rows cascade with the version;
the answering user is SET NULL so the record survives account erasure.
``downgrade`` drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clarification_answers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_version_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("question_key", sa.String(length=100), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "answered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["product_version_id"],
            ["product_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_clarification_answers_id"),
        "clarification_answers",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_clarification_answers_product_version_id"),
        "clarification_answers",
        ["product_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_clarification_answers_user_id"),
        "clarification_answers",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_clarification_answers_question_key"),
        "clarification_answers",
        ["question_key"],
        unique=False,
    )


def downgrade() -> None:
    for column in ("id", "product_version_id", "user_id", "question_key"):
        op.drop_index(
            op.f(f"ix_clarification_answers_{column}"),
            table_name="clarification_answers",
        )
    op.drop_table("clarification_answers")
