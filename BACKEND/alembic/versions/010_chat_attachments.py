"""Chat attachments - PDFs attached to chat messages.

Revision ID: 010
Revises: 009
Create Date: 2026-09-26

Adds ``chat_attachments``: one row per PDF a user attaches to a chat. The
file's extracted text is stored with the owner and optionally bound to a chat
session, so the assistant can answer questions from the document (and reuse it
for follow-ups in the same conversation). ``downgrade`` drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_attachments_id"), "chat_attachments", ["id"], unique=False)
    op.create_index(
        op.f("ix_chat_attachments_user_id"), "chat_attachments", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_chat_attachments_session_id"), "chat_attachments", ["session_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_attachments_session_id"), table_name="chat_attachments")
    op.drop_index(op.f("ix_chat_attachments_user_id"), table_name="chat_attachments")
    op.drop_index(op.f("ix_chat_attachments_id"), table_name="chat_attachments")
    op.drop_table("chat_attachments")
