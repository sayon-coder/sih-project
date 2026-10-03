"""Chat attachments: link to the indexed corpus document.

Revision ID: 011
Revises: 010
Create Date: 2026-09-26

Adds ``chat_attachments.document_id``: the ``source_documents`` row that
holds the attachment's page-aware, provenance-labelled chunks. The column is
nullable so attachments uploaded before indexing existed keep working (they
remain usable through prompt injection) and so a failed indexing step never
blocks storing the attachment itself. ``downgrade`` drops the column.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_attachments",
        sa.Column("document_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_attachments_document_id",
        "chat_attachments",
        "source_documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_chat_attachments_document_id"),
        "chat_attachments",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_attachments_document_id"), table_name="chat_attachments")
    op.drop_constraint(
        "fk_chat_attachments_document_id", "chat_attachments", type_="foreignkey"
    )
    op.drop_column("chat_attachments", "document_id")
