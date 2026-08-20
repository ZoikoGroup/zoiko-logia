"""Add retention deadlines for documents and generated artifacts."""
from alembic import op
import sqlalchemy as sa


revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    dialect = op.get_bind().dialect.name
    for table, days in (("workspace_documents", 30), ("workspace_artifacts", 7)):
        op.add_column(table, sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        expression = (
            f"datetime(created_at, '+{days} days')"
            if dialect == "sqlite"
            else f"created_at + INTERVAL '{days} days'"
        )
        op.execute(f"UPDATE {table} SET expires_at = {expression} WHERE expires_at IS NULL")
        op.create_index(f"ix_{table}_expires_at", table, ["expires_at"])


def downgrade():
    for table in ("workspace_artifacts", "workspace_documents"):
        op.drop_index(f"ix_{table}_expires_at", table_name=table)
        op.drop_column(table, "expires_at")
