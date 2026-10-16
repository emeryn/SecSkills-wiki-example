"""Single sign-on: external identities on users and server-side OIDC login flows.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("external_id", sa.String(length=255), nullable=True))
    op.create_index(
        "uq_users_external_identity",
        "users",
        ["auth_source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_table(
        "oidc_flows",
        sa.Column("state_hash", sa.LargeBinary(), nullable=False),
        sa.Column("binding_hash", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("next_path", sa.String(length=500), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("purpose IN ('login', 'reauth')", name=op.f("ck_oidc_flows_purpose")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_oidc_flows_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("state_hash", name=op.f("pk_oidc_flows")),
    )
    op.create_index(op.f("ix_oidc_flows_expires_at"), "oidc_flows", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_oidc_flows_expires_at"), table_name="oidc_flows")
    op.drop_table("oidc_flows")
    op.drop_index("uq_users_external_identity", table_name="users")
    op.drop_column("users", "external_id")
