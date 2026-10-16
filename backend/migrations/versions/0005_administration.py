"""Administration and operations: settings, blocked IPs, server errors, audit severity.

Also makes the two circular foreign keys deferrable so a backup can be restored table by table,
and lets the runtime role read (never write) the schema revision recorded in backups.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CIRCULAR_FKS = (
    ("fk_pages_current_revision_id_revisions", "pages", "revisions", "current_revision_id"),
    ("fk_spaces_home_page_id_pages", "spaces", "pages", "home_page_id"),
)


def _recreate_circular_fks(*, deferrable: bool) -> None:
    for name, table, referred, column in _CIRCULAR_FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name,
            table,
            referred,
            [column],
            ["id"],
            ondelete="SET NULL",
            deferrable=deferrable or None,
            initially="IMMEDIATE" if deferrable else None,
        )


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("value_enc", sa.LargeBinary(), nullable=False),
        sa.Column("dek_wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_settings_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )
    op.create_table(
        "blocked_ips",
        sa.Column("ip", postgresql.INET(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("ip", name=op.f("pk_blocked_ips")),
    )
    op.create_table(
        "server_errors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.CheckConstraint("source IN ('request', 'job')", name=op.f("ck_server_errors_source")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_server_errors")),
    )
    op.create_index(
        op.f("ix_server_errors_occurred_at"), "server_errors", ["occurred_at"], unique=False
    )
    op.add_column(
        "audit_events",
        sa.Column("severity", sa.String(length=16), server_default="info", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_audit_events_severity"),
        "audit_events",
        "severity IN ('info', 'warning', 'critical')",
    )
    op.create_index(op.f("ix_audit_events_severity"), "audit_events", ["severity"], unique=False)
    _recreate_circular_fks(deferrable=True)
    op.execute("GRANT SELECT ON TABLE alembic_version TO app_runtime")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON TABLE alembic_version FROM app_runtime")
    _recreate_circular_fks(deferrable=False)
    op.drop_index(op.f("ix_audit_events_severity"), table_name="audit_events")
    op.drop_constraint(op.f("ck_audit_events_severity"), "audit_events", type_="check")
    op.drop_column("audit_events", "severity")
    op.drop_index(op.f("ix_server_errors_occurred_at"), table_name="server_errors")
    op.drop_table("server_errors")
    op.drop_table("blocked_ips")
    op.drop_table("settings")
