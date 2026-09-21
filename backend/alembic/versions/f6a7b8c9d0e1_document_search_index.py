"""Add GIN-backed full-text search to workspace document chunks."""
from alembic import op


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE workspace_document_chunks ADD COLUMN IF NOT EXISTS search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english'::regconfig, coalesce(text, ''))) STORED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workspace_document_chunks_search "
        "ON workspace_document_chunks USING GIN (search_vector)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_workspace_document_chunks_search")
    op.execute("ALTER TABLE workspace_document_chunks DROP COLUMN IF EXISTS search_vector")
