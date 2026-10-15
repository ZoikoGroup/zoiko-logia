"""Billing: versioned plan / rate card, credits and metering disputes, and
closed statements. All tenant isolated by RLS.

Revision ID: w2p3q4r5s6t7
Revises: v1o2p3q4r5s6
"""
from alembic import op
import sqlalchemy as sa

revision = "w2p3q4r5s6t7"
down_revision = "v1o2p3q4r5s6"
branch_labels = None
depends_on = None

_RLS = ("billing_plans", "billing_adjustments", "billing_statements")


def _tenant():
    return sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False)


def _user(name, nullable=True):
    return sa.Column(name, sa.String(), sa.ForeignKey("users.id"), nullable=nullable)


def _ts(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "billing_plans" not in existing:
        op.create_table(
            "billing_plans",
            sa.Column("id", sa.String(), primary_key=True), _tenant(),
            sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False), sa.Column("currency", sa.String(), nullable=False),
            sa.Column("commitment_cents", sa.Integer(), nullable=False), sa.Column("included", sa.JSON(), nullable=False),
            sa.Column("rates", sa.JSON(), nullable=False), sa.Column("soft_budget_cents", sa.Integer(), nullable=False),
            sa.Column("hard_cap_cents", sa.Integer(), nullable=False), sa.Column("effective_from", sa.String(), nullable=False),
            sa.Column("note", sa.Text(), nullable=False), _user("proposed_by", False), _ts("proposed_at", False),
            _user("decided_by"), _ts("decided_at"),
            sa.UniqueConstraint("tenant_id", "version", name="uq_billing_plan_version"),
        )
        op.create_index("ix_billing_plans_tenant_id", "billing_plans", ["tenant_id"])
    if "billing_adjustments" not in existing:
        op.create_table(
            "billing_adjustments",
            sa.Column("id", sa.String(), primary_key=True), _tenant(),
            sa.Column("period", sa.String(), nullable=False), sa.Column("kind", sa.String(), nullable=False),
            sa.Column("meter", sa.String()), sa.Column("amount_cents", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            _user("created_by", False), _ts("created_at", False), _user("decided_by"), _ts("decided_at"),
            sa.Column("decision_note", sa.Text(), nullable=False),
        )
        op.create_index("ix_billing_adjustments_tenant_id", "billing_adjustments", ["tenant_id"])
    if "billing_statements" not in existing:
        op.create_table(
            "billing_statements",
            sa.Column("id", sa.String(), primary_key=True), _tenant(),
            sa.Column("ref", sa.String(), nullable=False), sa.Column("period", sa.String(), nullable=False),
            sa.Column("currency", sa.String(), nullable=False), sa.Column("plan_version", sa.Integer(), nullable=False),
            sa.Column("lines", sa.JSON(), nullable=False), sa.Column("subtotal_cents", sa.Integer(), nullable=False),
            sa.Column("credits_cents", sa.Integer(), nullable=False), sa.Column("total_cents", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False), _user("issued_by", False), _ts("issued_at", False),
            _ts("paid_at"), sa.Column("payment_reference", sa.String(), nullable=False),
            sa.UniqueConstraint("tenant_id", "period", name="uq_billing_statement_period"),
            sa.UniqueConstraint("tenant_id", "ref", name="uq_billing_statement_ref"),
        )
        op.create_index("ix_billing_statements_tenant_id", "billing_statements", ["tenant_id"])
    if bind.dialect.name == "postgresql":
        for table in _RLS:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
            op.execute(f"CREATE POLICY tenant_isolation_{table} ON {table} "
                       "USING (tenant_id = current_setting('app.tenant_id', true)) "
                       "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))")


def downgrade():
    for table in ("billing_statements", "billing_adjustments", "billing_plans"):
        op.drop_table(table)
