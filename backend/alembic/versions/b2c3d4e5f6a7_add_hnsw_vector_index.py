"""add HNSW vector index on kriton_vector_nodes

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add HNSW vector index for pgvector."""
    conn = op.get_bind()
    if conn.dialect.name == 'postgresql':
        op.execute("""
            CREATE INDEX IF NOT EXISTS kriton_vector_nodes_hnsw_idx
            ON public.kriton_vector_nodes
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """)


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    if conn.dialect.name == 'postgresql':
        op.execute('DROP INDEX IF EXISTS public.kriton_vector_nodes_hnsw_idx;')
