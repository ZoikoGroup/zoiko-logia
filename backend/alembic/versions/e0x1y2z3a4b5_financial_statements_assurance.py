"""Financial statements: assurance cases, runs and evidence (Document 07, ZL-FSR-ENG-007).

fs_assurance_cases holds materiality, the finding register, the decision
ledger and misstatements; fs_assurance_runs holds each run with its
attestations and release certificate; fs_evidence_items holds evidence
documents (withdrawn, never deleted). Tenant isolated by RLS. Additive only.

Revision ID: e0x1y2z3a4b5
Revises: d9w0x1y2z3a4
"""
from alembic import op
import sqlalchemy as sa

revision = "e0x1y2z3a4b5"
down_revision = "d9w0x1y2z3a4"
branch_labels = None
depends_on = None

_TABLES = ("fs_assurance_cases", "fs_assurance_runs", "fs_evidence_items")


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "fs_assurance_cases" not in existing:
        op.create_table(
            "fs_assurance_cases",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("trial_balance_id", sa.String(), sa.ForeignKey("fs_trial_balances.id"), nullable=False),
            sa.Column("materiality", sa.JSON(), nullable=False),
            sa.Column("register", sa.JSON(), nullable=False),
            sa.Column("ledger", sa.JSON(), nullable=False),
            sa.Column("misstatements", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_fs_assurance_cases_tenant_id", "fs_assurance_cases", ["tenant_id"])
        op.create_index("ix_fs_assurance_cases_trial_balance_id", "fs_assurance_cases", ["trial_balance_id"])
    if "fs_assurance_runs" not in existing:
        op.create_table(
            "fs_assurance_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("case_id", sa.String(), sa.ForeignKey("fs_assurance_cases.id"), nullable=False),
            sa.Column("package_id", sa.String(), sa.ForeignKey("fs_report_packages.id"), nullable=False),
            sa.Column("package_version", sa.Integer(), nullable=False),
            sa.Column("input_hash", sa.String(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("attestations", sa.JSON(), nullable=False),
            sa.Column("certificate", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("superseded_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_fs_assurance_runs_tenant_id", "fs_assurance_runs", ["tenant_id"])
        op.create_index("ix_fs_assurance_runs_case_id", "fs_assurance_runs", ["case_id"])
    if "fs_evidence_items" not in existing:
        op.create_table(
            "fs_evidence_items",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("case_id", sa.String(), sa.ForeignKey("fs_assurance_cases.id"), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("sha256", sa.String(), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("media_type", sa.String(), nullable=False),
            sa.Column("content", sa.LargeBinary(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("domains", sa.JSON(), nullable=False),
            sa.Column("instruction_flag", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("uploaded_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("withdrawn_by", sa.String(), nullable=True),
            sa.Column("withdrawn_reason", sa.Text(), nullable=False),
        )
        op.create_index("ix_fs_evidence_items_tenant_id", "fs_evidence_items", ["tenant_id"])
        op.create_index("ix_fs_evidence_items_case_id", "fs_evidence_items", ["case_id"])
    if bind.dialect.name == "postgresql":
        for table in _TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
            op.execute(
                f"CREATE POLICY tenant_isolation_{table} ON {table} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )


def downgrade():
    for table in reversed(_TABLES):
        op.drop_table(table)
