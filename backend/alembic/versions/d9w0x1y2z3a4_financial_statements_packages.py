"""Financial statements: assembled report packages (Document 05, ZL-FSR-ENG-005).

One row per package version: inputs, fingerprint, result, sign-offs and the
append-only history. Tenant isolated by RLS. Additive only.

Revision ID: d9w0x1y2z3a4
Revises: c8v9w0x1y2z3
"""
from alembic import op
import sqlalchemy as sa

revision = "d9w0x1y2z3a4"
down_revision = "c8v9w0x1y2z3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "fs_report_packages" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "fs_report_packages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("trial_balance_id", sa.String(), sa.ForeignKey("fs_trial_balances.id"), nullable=False),
            sa.Column("prior_trial_balance_id", sa.String(), sa.ForeignKey("fs_trial_balances.id"), nullable=True),
            sa.Column("resolution_id", sa.String(), sa.ForeignKey("fs_resolutions.id"), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("inputs", sa.JSON(), nullable=False),
            sa.Column("fingerprint", sa.String(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("signoffs", sa.JSON(), nullable=False),
            sa.Column("history", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("superseded_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_fs_report_packages_tenant_id", "fs_report_packages", ["tenant_id"])
        op.create_index("ix_fs_report_packages_trial_balance_id", "fs_report_packages", ["trial_balance_id"])
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE fs_report_packages ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE fs_report_packages FORCE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS tenant_isolation_fs_report_packages ON fs_report_packages")
        op.execute(
            "CREATE POLICY tenant_isolation_fs_report_packages ON fs_report_packages "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade():
    op.drop_table("fs_report_packages")
