"""Financial statements: Reporting Rules Resolutions (Document 03, ZL-FSR-ENG-003).

One row per resolution revision: the entity facts, their hash, the rule-pack
digest, the result, reviewer judgments, the append-only history and its
approval. Tenant isolated by RLS. Additive only.

Revision ID: c8v9w0x1y2z3
Revises: b7u8v9w0x1y2
"""
from alembic import op
import sqlalchemy as sa

revision = "c8v9w0x1y2z3"
down_revision = "b7u8v9w0x1y2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "fs_resolutions" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "fs_resolutions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("entity_key", sa.String(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("facts", sa.JSON(), nullable=False),
            sa.Column("facts_hash", sa.String(), nullable=False),
            sa.Column("rule_pack_digest", sa.String(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("judgments", sa.JSON(), nullable=False),
            sa.Column("history", sa.JSON(), nullable=False),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("trial_balance_id", sa.String(), sa.ForeignKey("fs_trial_balances.id"), nullable=True),
            sa.Column("prepared_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("approved_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_fs_resolutions_tenant_id", "fs_resolutions", ["tenant_id"])
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE fs_resolutions ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE fs_resolutions FORCE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS tenant_isolation_fs_resolutions ON fs_resolutions")
        op.execute(
            "CREATE POLICY tenant_isolation_fs_resolutions ON fs_resolutions "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade():
    op.drop_table("fs_resolutions")
