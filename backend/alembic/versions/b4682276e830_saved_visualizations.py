"""saved visualizations (save-to-conversation export feature)

Revision ID: b4682276e830
Revises: b7c8d9e0f1a2

NOTE: this targets a fresh database. Any environment where
app.main's create_all() lifespan already bootstrapped this table (every
local dev environment run against this branch before this migration
existed) will hit "relation already exists" on `alembic upgrade` — that
environment already has the table (and, once app/main.py's
_migrate_saved_visualization_columns has run, the updated_at column too)
and should be reconciled with `alembic stamp b4682276e830` instead of
running this migration.
"""
from alembic import op
import sqlalchemy as sa


revision = "b4682276e830"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_visualizations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("query_id", sa.String(), nullable=False),
        sa.Column("visualization_type", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_references", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Idempotency (dedup on repeated Idempotency-Key headers) is handled by
    # the existing shared idempotency_records table, not a constraint here —
    # see app/domains/kriton_workspace/router.py's post_saved_visualization,
    # which namespaces the key by user_id before checking that table. There
    # is no natural content-uniqueness constraint on this table itself: two
    # legitimately different saves can share a title, payload, or query_id.
    op.create_index("ix_saved_visualizations_tenant_id", "saved_visualizations", ["tenant_id"])
    op.create_index("ix_saved_visualizations_user_id", "saved_visualizations", ["user_id"])
    op.create_index("ix_saved_visualizations_query_id", "saved_visualizations", ["query_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_visualizations_query_id", table_name="saved_visualizations")
    op.drop_index("ix_saved_visualizations_user_id", table_name="saved_visualizations")
    op.drop_index("ix_saved_visualizations_tenant_id", table_name="saved_visualizations")
    op.drop_table("saved_visualizations")
