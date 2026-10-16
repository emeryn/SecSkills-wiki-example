"""Baseline: restrict the Alembic bookkeeping table to the owner role.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Default privileges grant DML on every owner table to the runtime role; the migration
    # history is not application data.
    op.execute("REVOKE ALL ON TABLE alembic_version FROM app_runtime")


def downgrade() -> None:
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE alembic_version TO app_runtime")
