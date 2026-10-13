"""Elevated-access governance: impersonation sessions, break-glass grants and
service accounts with API keys.

impersonation_sessions, break_glass_grants and service_accounts are tenant
isolated by RLS like every other tenant table. service_account_keys is not:
an API key is resolved by its hash before any tenant is known, and its rows
hold only hashes, prefixes and timestamps.

Revision ID: r7k8l9m0n1o2
Revises: q6j7k8l9m0n1
"""
from alembic import op
import sqlalchemy as sa

revision = "r7k8l9m0n1o2"
down_revision = "q6j7k8l9m0n1"
branch_labels = None
depends_on = None

_RLS_TABLES = ("impersonation_sessions", "break_glass_grants", "service_accounts")


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "impersonation_sessions" not in existing:
        op.create_table(
            "impersonation_sessions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("actor_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("target_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reason", sa.String(), nullable=False),
            _ts("started_at", nullable=False),
            _ts("expires_at", nullable=False),
            _ts("ended_at"),
        )
        op.create_index("ix_impersonation_sessions_tenant_id", "impersonation_sessions", ["tenant_id"])
        op.create_index("ix_impersonation_sessions_actor_id", "impersonation_sessions", ["actor_id"])

    if "break_glass_grants" not in existing:
        op.create_table(
            "break_glass_grants",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("permissions", sa.JSON(), nullable=False),
            sa.Column("reason", sa.String(), nullable=False),
            sa.Column("duration_minutes", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            _ts("requested_at", nullable=False),
            sa.Column("approved_by", sa.String(), sa.ForeignKey("users.id")),
            _ts("activated_at"),
            _ts("expires_at"),
            _ts("ended_at"),
            sa.Column("ended_by", sa.String(), sa.ForeignKey("users.id")),
            sa.Column("reviewed_by", sa.String(), sa.ForeignKey("users.id")),
            _ts("reviewed_at"),
            sa.Column("review_notes", sa.String()),
        )
        op.create_index("ix_break_glass_grants_tenant_id", "break_glass_grants", ["tenant_id"])
        op.create_index("ix_break_glass_grants_user_id", "break_glass_grants", ["user_id"])

    if "service_accounts" not in existing:
        op.create_table(
            "service_accounts",
            sa.Column("id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=False),
            sa.Column("owner_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            _ts("created_at", nullable=False),
        )
        op.create_index("ix_service_accounts_tenant_id", "service_accounts", ["tenant_id"])

    if "service_account_keys" not in existing:
        op.create_table(
            "service_account_keys",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("service_account_id", sa.String(), sa.ForeignKey("service_accounts.id"), nullable=False),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("key_prefix", sa.String(), nullable=False),
            sa.Column("key_hash", sa.String(), nullable=False, unique=True),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            _ts("created_at", nullable=False),
            _ts("expires_at", nullable=False),
            _ts("revoked_at"),
            _ts("last_used_at"),
        )
        op.create_index("ix_service_account_keys_service_account_id", "service_account_keys", ["service_account_id"])
        op.create_index("ix_service_account_keys_tenant_id", "service_account_keys", ["tenant_id"])

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
    for table in ("service_account_keys", "service_accounts", "break_glass_grants", "impersonation_sessions"):
        op.drop_table(table)
