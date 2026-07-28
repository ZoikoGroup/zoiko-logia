"""tenant scope safety workflow records

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa


revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("escalation_cases", "safety_overrides", "safety_events"):
        op.add_column(table, sa.Column("tenant_id", sa.String(), nullable=True))
        op.execute(
            f"UPDATE {table} SET tenant_id = COALESCE((SELECT id FROM tenants LIMIT 1), 'GLOBAL_CONTROL') "
            "WHERE tenant_id IS NULL"
        )
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in reversed(("escalation_cases", "safety_overrides", "safety_events")):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
