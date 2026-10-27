"""Financial statements: trial-balance intake (Document 04, ZL-FSR-ENG-004).

Stored uploads with their original bytes and SHA-256, mapping decisions,
proposed journals, supporting records, approved snapshots and the event
history. Every table is tenant isolated by RLS like every other tenant table.
Additive only: no existing table is changed.

Revision ID: b7u8v9w0x1y2
Revises: a6t7u8v9w0x1
"""
from alembic import op
import sqlalchemy as sa

revision = "b7u8v9w0x1y2"
down_revision = "a6t7u8v9w0x1"
branch_labels = None
depends_on = None

_TABLES = ("fs_trial_balances", "fs_mapping_decisions", "fs_journals", "fs_supporting_records", "fs_snapshots",
           "fs_events")


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False)


def _tb() -> sa.Column:
    return sa.Column("trial_balance_id", sa.String(), sa.ForeignKey("fs_trial_balances.id", ondelete="CASCADE"),
                     nullable=False)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "fs_trial_balances" not in existing:
        op.create_table(
            "fs_trial_balances",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(),
            sa.Column("uploaded_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("sha256", sa.String(), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("media_type", sa.String(), nullable=False),
            sa.Column("original", sa.LargeBinary(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False, server_default="TRIAL_BALANCE"),
            sa.Column("units", sa.String(), nullable=False, server_default="units"),
            sa.Column("sign_convention", sa.String(), nullable=False, server_default="DEBIT_CREDIT_COLUMNS"),
            sa.Column("period_end", sa.String(), nullable=False, server_default=""),
            sa.Column("sheets", sa.JSON(), nullable=False),
            sa.Column("integrity", sa.JSON(), nullable=False),
            sa.Column("findings", sa.JSON(), nullable=False),
            sa.Column("lines", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("supersedes_id", sa.String(), sa.ForeignKey("fs_trial_balances.id"), nullable=True),
            sa.Column("superseded_by", sa.String(), nullable=True),
            _ts("created_at", nullable=False),
        )
        op.create_index("ix_fs_trial_balances_tenant_id", "fs_trial_balances", ["tenant_id"])

    if "fs_mapping_decisions" not in existing:
        op.create_table(
            "fs_mapping_decisions",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(), _tb(),
            sa.Column("account_key", sa.String(), nullable=False),
            sa.Column("account_name", sa.String(), nullable=False),
            sa.Column("balance", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("line_id", sa.String(), nullable=True),
            sa.Column("candidates", sa.JSON(), nullable=False),
            sa.Column("evidence_required", sa.Text(), nullable=False, server_default=""),
            sa.Column("basis", sa.Text(), nullable=False, server_default=""),
            sa.Column("allocations", sa.JSON(), nullable=False),
            sa.Column("evidence_ref", sa.String(), nullable=False, server_default=""),
            sa.Column("source", sa.String(), nullable=False, server_default=""),
            sa.Column("reviewer_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            _ts("decided_at"),
            sa.UniqueConstraint("trial_balance_id", "account_key", name="uq_fs_mapping_account"),
        )

    if "fs_journals" not in existing:
        op.create_table(
            "fs_journals",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(), _tb(),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("correction_type", sa.String(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("lines", sa.JSON(), nullable=False),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("review_status", sa.String(), nullable=False, server_default="PENDING_REVIEW"),
            sa.Column("reviewer_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            _ts("reviewed_at"),
            sa.Column("posting_status", sa.String(), nullable=False, server_default="NOT_POSTED"),
            _ts("created_at", nullable=False),
        )

    if "fs_supporting_records" not in existing:
        op.create_table(
            "fs_supporting_records",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(), _tb(),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("sha256", sa.String(), nullable=False),
            sa.Column("total", sa.String(), nullable=True),
            sa.Column("basis", sa.String(), nullable=False, server_default=""),
            sa.Column("finding", sa.JSON(), nullable=False),
            sa.Column("uploaded_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            _ts("created_at", nullable=False),
        )

    if "fs_snapshots" not in existing:
        op.create_table(
            "fs_snapshots",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(), _tb(),
            sa.Column("content_hash", sa.String(), nullable=False),
            sa.Column("line_totals", sa.JSON(), nullable=False),
            sa.Column("preparer_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("approver_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="APPROVED"),
            _ts("approved_at", nullable=False),
            _ts("superseded_at"),
        )

    if "fs_events" not in existing:
        op.create_table(
            "fs_events",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(), _tb(),
            sa.Column("actor_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("detail", sa.JSON(), nullable=False),
            _ts("at", nullable=False),
        )

    for table in _TABLES[1:]:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"], if_not_exists=True)
        op.create_index(f"ix_{table}_trial_balance_id", table, ["trial_balance_id"], if_not_exists=True)

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
