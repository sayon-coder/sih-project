"""Phase 8b - reports table.

Revision ID: 008
Revises: 007
Create Date: 2026-09-26

Phase 8b adds PDF report generation. Each ``reports`` row pins one generated
PDF to the product version it describes and stores its SHA-256 content hash
plus a unique verification id (rendered as a QR code inside the PDF).
``downgrade`` drops the table and its enum type.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("product_version_id", sa.Integer(), nullable=False),
        sa.Column(
            "report_type",
            sa.Enum("IP_BRIEF", "DISCLOSURE_RECORD", "EXPERT_HANDOFF", name="reporttype"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verification_id", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["product_version_id"], ["product_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("verification_id"),
    )
    op.create_index(op.f("ix_reports_id"), "reports", ["id"], unique=False)
    op.create_index(op.f("ix_reports_product_id"), "reports", ["product_id"], unique=False)
    op.create_index(
        op.f("ix_reports_product_version_id"), "reports", ["product_version_id"], unique=False
    )
    op.create_index(op.f("ix_reports_report_type"), "reports", ["report_type"], unique=False)
    op.create_index(op.f("ix_reports_content_hash"), "reports", ["content_hash"], unique=False)
    op.create_index(
        op.f("ix_reports_verification_id"), "reports", ["verification_id"], unique=False
    )


def downgrade() -> None:
    op.drop_table("reports")
    op.execute("DROP TYPE IF EXISTS reporttype")
