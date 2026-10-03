"""Phase 8 - disclosures table.

Revision ID: 007
Revises: 006
Create Date: 2026-09-26

Phase 8 adds public-disclosure tracking: one immutable ``disclosures`` row per
recorded event, pinned to the product version it describes. Each row carries
a SHA-256 ``record_hash`` and a unique ``verification_id`` used by the QR
verification endpoint. ``downgrade`` drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "disclosures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("product_version_id", sa.Integer(), nullable=False),
        sa.Column(
            "disclosure_type",
            postgresql.ENUM(
                "CONFERENCE_PRESENTATION",
                "PUBLICATION",
                "WEBSITE",
                "INVESTOR_DISCLOSURE",
                "ADVERTISING",
                "COMMERCIAL_LAUNCH",
                "OTHER",
                name="disclosuretype",
                create_type=True,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("venue_or_channel", sa.String(length=500), nullable=True),
        sa.Column("disclosure_date", sa.String(length=40), nullable=True),
        sa.Column("declarant_name", sa.String(length=255), nullable=True),
        sa.Column("institution", sa.String(length=500), nullable=True),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("verification_id", sa.String(length=32), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
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
    op.create_index(op.f("ix_disclosures_id"), "disclosures", ["id"], unique=False)
    op.create_index(
        op.f("ix_disclosures_product_id"), "disclosures", ["product_id"], unique=False
    )
    op.create_index(
        op.f("ix_disclosures_product_version_id"),
        "disclosures",
        ["product_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_disclosures_disclosure_type"),
        "disclosures",
        ["disclosure_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_disclosures_record_hash"), "disclosures", ["record_hash"], unique=False
    )
    op.create_index(
        op.f("ix_disclosures_verification_id"),
        "disclosures",
        ["verification_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("disclosures")
    op.execute("DROP TYPE IF EXISTS disclosuretype")
