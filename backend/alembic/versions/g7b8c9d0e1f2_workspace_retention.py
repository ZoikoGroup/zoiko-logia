"""Add retention deadlines for documents and generated artifacts."""
from alembic import op
import sqlalchemy as sa


revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)
    for table, days in (("workspace_documents", 30), ("workspace_artifacts", 7)):
        column_names = {column["name"] for column in inspector.get_columns(table)}
        if "expires_at" not in column_names:
            op.add_column(table, sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        expression = (
            f"datetime(created_at, '+{days} days')"
            if dialect == "sqlite"
            else f"created_at + INTERVAL '{days} days'"
        )
        op.execute(f"UPDATE {table} SET expires_at = {expression} WHERE expires_at IS NULL")
        index_name = f"ix_{table}_expires_at"
        index_names = {index["name"] for index in inspector.get_indexes(table)}
        if index_name not in index_names:
            op.create_index(index_name, table, ["expires_at"])


def downgrade():
    for table in ("workspace_artifacts", "workspace_documents"):
        op.drop_index(f"ix_{table}_expires_at", table_name=table)
        op.drop_column(table, "expires_at")
