"""server-side conversation document binding

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None

def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("workspace_conversation_documents"):
        return
    op.create_table(
        "workspace_conversation_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), sa.ForeignKey("workspace_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", "conversation_id", "document_id", name="uq_conversation_document"),
    )
    for column in ("tenant_id", "user_id", "conversation_id", "document_id"):
        op.create_index(f"ix_workspace_conversation_documents_{column}", "workspace_conversation_documents", [column])

def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("workspace_conversation_documents"):
        op.drop_table("workspace_conversation_documents")
