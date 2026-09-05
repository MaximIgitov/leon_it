"""knowledge documents

Revision ID: 9c4e2a7b1d03
Revises: 4a1c8f2b7e05
Create Date: 2026-09-05 05:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4e2a7b1d03"
down_revision: str | None = "4a1c8f2b7e05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_label", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("knowledge_documents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_documents_organization_id"), ["organization_id"], unique=False
        )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "position", name="uq_knowledge_chunk_position"),
    )
    with op.batch_alter_table("knowledge_chunks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_chunks_document_id"), ["document_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_chunks_organization_id"), ["organization_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_chunks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_chunks_organization_id"))
        batch_op.drop_index(batch_op.f("ix_knowledge_chunks_document_id"))
    op.drop_table("knowledge_chunks")
    with op.batch_alter_table("knowledge_documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_documents_organization_id"))
    op.drop_table("knowledge_documents")
