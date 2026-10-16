"""Search vector on pages, attachments, and the circular foreign keys of 0003.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("storage_key", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("inline_allowed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"], name=op.f("fk_attachments_page_id_pages"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_attachments_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_attachments_storage_key")),
    )
    op.create_index(op.f("ix_attachments_page_id"), "attachments", ["page_id"], unique=False)
    op.add_column("pages", sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True))
    op.create_index(
        "ix_pages_search_vector", "pages", ["search_vector"], unique=False, postgresql_using="gin"
    )
    op.execute(
        """
        UPDATE pages AS p
        SET search_vector =
            setweight(to_tsvector('simple', r.title), 'A')
            || setweight(to_tsvector('simple', r.body), 'B')
        FROM revisions AS r
        WHERE r.id = p.current_revision_id
        """
    )
    # 0003 declared these with use_alter inside create_table, which does not emit them.
    op.create_foreign_key(
        op.f("fk_pages_current_revision_id_revisions"),
        "pages",
        "revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_spaces_home_page_id_pages"),
        "spaces",
        "pages",
        ["home_page_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_spaces_home_page_id_pages"), "spaces", type_="foreignkey")
    op.drop_constraint(op.f("fk_pages_current_revision_id_revisions"), "pages", type_="foreignkey")
    op.drop_index("ix_pages_search_vector", table_name="pages", postgresql_using="gin")
    op.drop_column("pages", "search_vector")
    op.drop_index(op.f("ix_attachments_page_id"), table_name="attachments")
    op.drop_table("attachments")
