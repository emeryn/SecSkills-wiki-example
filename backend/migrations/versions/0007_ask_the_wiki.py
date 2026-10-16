"""Ask the wiki: page chunks with embeddings, versioned system prompts, daily token usage.

The ``vector`` extension is marked trusted in the database image, so the owner role creates it.
Embeddings have no fixed dimension (it depends on the model): retrieval is an exact scan
restricted to readable spaces, which is what the permission filter requires anyway.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "page_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"], name=op.f("fk_page_chunks_page_id_pages"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name=op.f("fk_page_chunks_space_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["revisions.id"],
            name=op.f("fk_page_chunks_revision_id_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_chunks")),
    )
    op.execute("ALTER TABLE page_chunks ADD COLUMN embedding vector NOT NULL")
    op.create_index(op.f("ix_page_chunks_page_id"), "page_chunks", ["page_id"], unique=False)
    op.create_index(op.f("ix_page_chunks_space_id"), "page_chunks", ["space_id"], unique=False)
    op.create_table(
        "llm_prompts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_llm_prompts_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_prompts")),
    )
    op.create_index(op.f("ix_llm_prompts_name"), "llm_prompts", ["name"], unique=False)
    op.create_table(
        "llm_usage",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_llm_usage_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "day", name=op.f("pk_llm_usage")),
    )


def downgrade() -> None:
    op.drop_table("llm_usage")
    op.drop_index(op.f("ix_llm_prompts_name"), table_name="llm_prompts")
    op.drop_table("llm_prompts")
    op.drop_index(op.f("ix_page_chunks_space_id"), table_name="page_chunks")
    op.drop_index(op.f("ix_page_chunks_page_id"), table_name="page_chunks")
    op.drop_table("page_chunks")
