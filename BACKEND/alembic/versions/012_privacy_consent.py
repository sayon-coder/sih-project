"""DPDP privacy layer: consent records and the source-access evidence trail.

Revision ID: 012
Revises: 011
Create Date: 2026-10-03

Creates ``data_consents``, ``source_consents`` and ``source_access_logs``
exactly as ``app.models.privacy_models`` defines them (the tables the
privacy and sources-registry routers serve). Personal rows cascade with
the account; the access log uses SET NULL so the evidence trail survives
erasure without a personal identifier (same rule as ``audit_logs``).
``downgrade`` drops the three tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_consents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("notice_version", sa.String(length=50), nullable=False),
        sa.Column("purposes", sa.Text(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_data_consents_id"), "data_consents", ["id"], unique=False)
    op.create_index(
        op.f("ix_data_consents_user_id"), "data_consents", ["user_id"], unique=False
    )

    op.create_table(
        "source_consents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("source_title", sa.String(length=255), nullable=False),
        sa.Column("access_type", sa.String(length=50), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("permission", sa.String(length=20), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_source_consents_id"), "source_consents", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_source_consents_user_id"),
        "source_consents",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_consents_source_id"),
        "source_consents",
        ["source_id"],
        unique=False,
    )

    op.create_table(
        "source_access_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("source_consent_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_consent_id"], ["source_consents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_source_access_logs_id"),
        "source_access_logs",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_access_logs_user_id"),
        "source_access_logs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_access_logs_source_id"),
        "source_access_logs",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_access_logs_action"),
        "source_access_logs",
        ["action"],
        unique=False,
    )


def downgrade() -> None:
    for table, indexes in (
        (
            "source_access_logs",
            ["id", "user_id", "source_id", "action"],
        ),
        ("source_consents", ["id", "user_id", "source_id"]),
        ("data_consents", ["id", "user_id"]),
    ):
        for column in indexes:
            op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
    op.drop_table("source_access_logs")
    op.drop_table("source_consents")
    op.drop_table("data_consents")
