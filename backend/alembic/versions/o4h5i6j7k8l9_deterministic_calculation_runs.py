"""Deterministic calculation runs and verified chart specifications.

Revision ID: o4h5i6j7k8l9
Revises: n3g4h5i6j7k8
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

revision: str = "o4h5i6j7k8l9"
down_revision: Union[str, Sequence[str], None] = "n3g4h5i6j7k8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set() if context.is_offline_mode() else set(sa.inspect(op.get_bind()).get_table_names())
    if "calculation_runs" not in existing:
        op.create_table(
            "calculation_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("query_id", sa.String(), nullable=False),
            sa.Column("operation", sa.String(), nullable=False),
            sa.Column("rule_version", sa.String(), nullable=False),
            sa.Column("inputs", sa.JSON(), nullable=False),
            sa.Column("output_value", sa.String(), nullable=False),
            sa.Column("output_unit", sa.String(), nullable=False),
            sa.Column("rounding_mode", sa.String(), nullable=False),
            sa.Column("scale", sa.Integer(), nullable=False),
            sa.Column("chart_spec", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="completed"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("status IN ('completed','failed')", name="ck_calculation_run_status"),
        )
        op.create_index("ix_calculation_runs_tenant_id", "calculation_runs", ["tenant_id"])
        op.create_index("ix_calculation_runs_query_id", "calculation_runs", ["query_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = "
            "'ck_calculation_run_status') THEN ALTER TABLE calculation_runs ADD CONSTRAINT "
            "ck_calculation_run_status CHECK (status IN ('completed','failed')); END IF; END $$"
        )
        op.execute("ALTER TABLE calculation_runs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE calculation_runs FORCE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS calculation_runs_tenant_isolation ON calculation_runs")
        op.execute(
            "CREATE POLICY calculation_runs_tenant_isolation ON calculation_runs "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_calculation_run_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'completed calculation runs are immutable';
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("DROP TRIGGER IF EXISTS trg_calculation_runs_immutable ON calculation_runs")
        op.execute(
            "CREATE TRIGGER trg_calculation_runs_immutable BEFORE UPDATE OR DELETE ON calculation_runs "
            "FOR EACH ROW EXECUTE FUNCTION prevent_calculation_run_mutation()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_calculation_runs_immutable ON calculation_runs")
        op.execute("DROP FUNCTION IF EXISTS prevent_calculation_run_mutation()")
    op.drop_table("calculation_runs")
