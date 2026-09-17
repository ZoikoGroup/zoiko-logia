"""Supabase object storage metadata

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("workspace_documents", "workspace_artifacts"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "storage_provider" not in columns:
            op.add_column(table, sa.Column("storage_provider", sa.String(), nullable=False, server_default="local"))
        if "storage_bucket" not in columns:
            op.add_column(table, sa.Column("storage_bucket", sa.String(), nullable=True))
        if "storage_object_path" not in columns:
            op.add_column(table, sa.Column("storage_object_path", sa.String(), nullable=True))

def downgrade() -> None:
    for table in ("workspace_artifacts", "workspace_documents"):
        for column in ("storage_object_path", "storage_bucket", "storage_provider"):
            op.drop_column(table, column)
