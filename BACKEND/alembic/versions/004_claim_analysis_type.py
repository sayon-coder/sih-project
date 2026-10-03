"""Phase 5 - add CLAIM_ANALYSIS to the analysistype enum.

Revision ID: 004
Revises: 003
Create Date: 2026-09-23

Phase 5 introduces the claim-to-evidence analysis endpoint. Its results are
stored in the existing ``analyses`` table, which until now had no analysis type
for a claim review. This migration adds the single missing enum label.

PostgreSQL cannot remove a value from an existing enum, so ``downgrade`` is a
documented no-op: dropping the type itself happens in migration 002's downgrade,
which runs later in the chain.
"""

from alembic import op

# revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
    # PostgreSQL versions, and a duplicate label is a harmless no-op, so guard
    # with a DO block that simply ignores the duplicate-object error.
    op.execute(
        """
        DO $$ BEGIN
            ALTER TYPE analysistype ADD VALUE IF NOT EXISTS 'CLAIM_ANALYSIS';
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    # PostgreSQL does not support removing a value from an enum type.
    # The label is harmless if left in place, and 002's downgrade drops the
    # whole type, so there is nothing to undo here.
    pass
