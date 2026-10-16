"""Content: spaces, memberships, pages, revisions, favorites.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spaces",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("home_page_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "visibility IN ('restricted', 'internal')", name=op.f("ck_spaces_visibility")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_spaces_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["home_page_id"],
            ["pages.id"],
            name=op.f("fk_spaces_home_page_id_pages"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spaces")),
        sa.UniqueConstraint("key", name=op.f("uq_spaces_key")),
    )
    op.create_table(
        "pages",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("title_norm", sa.String(length=200), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("depth", sa.SmallInteger(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.Column("trash_root_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("depth BETWEEN 1 AND 5", name=op.f("ck_pages_depth")),
        sa.ForeignKeyConstraint(
            ["current_revision_id"],
            ["revisions.id"],
            name=op.f("fk_pages_current_revision_id_revisions"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by"],
            ["users.id"],
            name=op.f("fk_pages_deleted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["pages.id"], name=op.f("fk_pages_parent_id_pages"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["spaces.id"], name=op.f("fk_pages_space_id_spaces"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pages")),
        sa.UniqueConstraint("space_id", "slug", name="uq_pages_space_slug"),
    )
    op.create_index(op.f("ix_pages_deleted_at"), "pages", ["deleted_at"], unique=False)
    op.create_index(
        "ix_pages_space_parent", "pages", ["space_id", "parent_id", "position"], unique=False
    )
    op.create_index(
        "uq_pages_space_title_live",
        "pages",
        ["space_id", "title_norm"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "space_members",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("principal_type", sa.String(length=8), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "principal_type IN ('user', 'group')", name=op.f("ck_space_members_principal_type")
        ),
        sa.CheckConstraint(
            "role IN ('viewer', 'editor', 'space_admin')", name=op.f("ck_space_members_role")
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name=op.f("fk_space_members_space_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "space_id", "principal_type", "principal_id", name=op.f("pk_space_members")
        ),
    )
    op.create_index(
        "ix_space_members_principal",
        "space_members",
        ["principal_type", "principal_id"],
        unique=False,
    )
    op.create_table(
        "favorites",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"], name=op.f("fk_favorites_page_id_pages"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_favorites_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "page_id", name=op.f("pk_favorites")),
    )
    op.create_index(op.f("ix_favorites_page_id"), "favorites", ["page_id"], unique=False)
    op.create_table(
        "revisions",
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("restored_from_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_revisions_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"], name=op.f("fk_revisions_page_id_pages"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["restored_from_id"],
            ["revisions.id"],
            name=op.f("fk_revisions_restored_from_id_revisions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revisions")),
        sa.UniqueConstraint("page_id", "number", name="uq_revisions_page_number"),
    )
    op.create_index(op.f("ix_revisions_author_id"), "revisions", ["author_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_revisions_author_id"), table_name="revisions")
    op.drop_table("revisions")
    op.drop_index(op.f("ix_favorites_page_id"), table_name="favorites")
    op.drop_table("favorites")
    op.drop_index("ix_space_members_principal", table_name="space_members")
    op.drop_table("space_members")
    op.drop_index(
        "uq_pages_space_title_live",
        table_name="pages",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_pages_space_parent", table_name="pages")
    op.drop_index(op.f("ix_pages_deleted_at"), table_name="pages")
    op.drop_table("pages")
    op.drop_table("spaces")
