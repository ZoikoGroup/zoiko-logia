"""workspace document ingestion and searchable chunks

Revision ID: b2c3d4e5f6a7
Revises: i4d5e6f7g8h9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "i4d5e6f7g8h9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("workspace_documents"):
        op.create_table(
        "workspace_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_workspace_documents_tenant_id", "workspace_documents", ["tenant_id"])
        op.create_index("ix_workspace_documents_user_id", "workspace_documents", ["user_id"])
        op.create_index("ix_workspace_documents_content_hash", "workspace_documents", ["content_hash"])
    if not inspector.has_table("workspace_document_chunks"):
        op.create_table(
        "workspace_document_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("workspace_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("location", sa.String(), nullable=False),
        sa.Column("chunk_metadata", sa.JSON(), nullable=False),
        )
        op.create_index("ix_workspace_document_chunks_document_id", "workspace_document_chunks", ["document_id"])
        op.create_index("ix_workspace_document_chunks_tenant_id", "workspace_document_chunks", ["tenant_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("workspace_document_chunks"):
        op.drop_table("workspace_document_chunks")
    if inspector.has_table("workspace_documents"):
        op.drop_table("workspace_documents")
