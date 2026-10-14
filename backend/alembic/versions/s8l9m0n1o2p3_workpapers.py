"""Workpapers: client job files with linked items and a maker-checker sign-off.

workpapers and workpaper_items are tenant isolated by RLS like every other
tenant table. Additive only: no existing table is changed.

Revision ID: s8l9m0n1o2p3
Revises: r7k8l9m0n1o2
"""
from alembic import op
import sqlalchemy as sa

revision = "s8l9m0n1o2p3"
down_revision = "r7k8l9m0n1o2"
branch_labels = None
depends_on = None

_RLS_TABLES = ("workpapers", "workpaper_items")


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "workpapers" not in existing:
        op.create_table(
            "workpapers",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("engagement_id", sa.String(), sa.ForeignKey("engagements.id"), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("period", sa.String(), nullable=False, server_default=""),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reviewer_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("signed_off_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            _ts("signed_off_at"),
            _ts("created_at", nullable=False),
            _ts("updated_at", nullable=False),
        )
        for column in ("tenant_id", "engagement_id", "owner_id", "reviewer_id"):
            op.create_index(f"ix_workpapers_{column}", "workpapers", [column])

    if "workpaper_items" not in existing:
        op.create_table(
            "workpaper_items",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("workpaper_id", sa.String(), sa.ForeignKey("workpapers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("item_id", sa.String(), nullable=False),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("added_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            _ts("added_at", nullable=False),
            sa.UniqueConstraint("workpaper_id", "kind", "item_id", name="uq_workpaper_item"),
        )
        op.create_index("ix_workpaper_items_tenant_id", "workpaper_items", ["tenant_id"])
        op.create_index("ix_workpaper_items_workpaper_id", "workpaper_items", ["workpaper_id"])

    if bind.dialect.name == "postgresql":
        for table in _RLS_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
            op.execute(
                f"CREATE POLICY tenant_isolation_{table} ON {table} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )


def downgrade():
    for table in ("workpaper_items", "workpapers"):
        op.drop_table(table)
