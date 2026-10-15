"""Operations: measured health history, operational alerts, service owners and
the provider / integration registers.

service_owners, operations_alerts, provider_records and integration_records
are tenant isolated by RLS like every other tenant table.
service_health_samples is not: it is platform telemetry (a dependency's state
and latency) with no tenant data, shared by every tenant's Status page.

Revision ID: s8l9m0n1o2p3
Revises: r7k8l9m0n1o2
"""
from alembic import op
import sqlalchemy as sa

revision = "s8l9m0n1o2p3"
down_revision = "r7k8l9m0n1o2"
branch_labels = None
depends_on = None

_RLS_TABLES = ("service_owners", "operations_alerts", "provider_records", "integration_records")


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False)


def _user(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.String(), sa.ForeignKey("users.id"), nullable=nullable)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "service_health_samples" not in existing:
        op.create_table(
            "service_health_samples",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("service_key", sa.String(), nullable=False),
            _ts("checked_at", nullable=False),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("latency_ms", sa.Float()),
            sa.Column("p50_ms", sa.Float()),
            sa.Column("requests", sa.Integer()),
            sa.Column("errors", sa.Integer()),
            sa.Column("detail", sa.String(), nullable=False),
        )
        op.create_index("ix_service_health_samples_service_key", "service_health_samples", ["service_key"])
        op.create_index("ix_service_health_samples_checked_at", "service_health_samples", ["checked_at"])

    if "service_owners" not in existing:
        op.create_table(
            "service_owners",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(),
            sa.Column("service_key", sa.String(), nullable=False),
            _user("owner_user_id", nullable=False),
            _user("updated_by", nullable=False),
            _ts("updated_at", nullable=False),
            sa.UniqueConstraint("tenant_id", "service_key", name="uq_service_owner"),
        )
        op.create_index("ix_service_owners_tenant_id", "service_owners", ["tenant_id"])

    if "operations_alerts" not in existing:
        op.create_table(
            "operations_alerts",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(),
            sa.Column("ref", sa.String(), nullable=False),
            sa.Column("source_key", sa.String(), nullable=False),
            sa.Column("origin", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False),
            sa.Column("href", sa.String(), nullable=False),
            sa.Column("service_key", sa.String()),
            sa.Column("state", sa.String(), nullable=False),
            _user("owner_user_id"),
            _user("created_by"),
            _ts("detected_at", nullable=False),
            _ts("last_seen_at", nullable=False),
            _ts("acknowledged_at"),
            _user("acknowledged_by"),
            _ts("resolved_at"),
            _user("resolved_by"),
            sa.Column("history", sa.JSON(), nullable=False),
            sa.UniqueConstraint("tenant_id", "ref", name="uq_operations_alert_ref"),
            sa.UniqueConstraint("tenant_id", "source_key", name="uq_operations_alert_source"),
        )
        op.create_index("ix_operations_alerts_tenant_id", "operations_alerts", ["tenant_id"])

    if "provider_records" not in existing:
        op.create_table(
            "provider_records",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(),
            sa.Column("ref", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("service", sa.String(), nullable=False),
            sa.Column("config_key", sa.String()),
            sa.Column("decision", sa.String(), nullable=False),
            sa.Column("criticality", sa.String(), nullable=False),
            sa.Column("region", sa.String(), nullable=False),
            sa.Column("approved_use", sa.String(), nullable=False),
            sa.Column("data_classification", sa.String(), nullable=False),
            sa.Column("contract_state", sa.String(), nullable=False),
            _user("owner_user_id"),
            _ts("next_review_at"),
            sa.Column("gates", sa.JSON(), nullable=False),
            _user("created_by", nullable=False),
            _ts("created_at", nullable=False),
            _user("decided_by"),
            _ts("decided_at"),
            _ts("updated_at", nullable=False),
            sa.Column("history", sa.JSON(), nullable=False),
            sa.UniqueConstraint("tenant_id", "ref", name="uq_provider_record_ref"),
        )
        op.create_index("ix_provider_records_tenant_id", "provider_records", ["tenant_id"])

    if "integration_records" not in existing:
        op.create_table(
            "integration_records",
            sa.Column("id", sa.String(), primary_key=True),
            _tenant(),
            sa.Column("ref", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("provider_id", sa.String(), sa.ForeignKey("provider_records.id")),
            sa.Column("health_key", sa.String()),
            sa.Column("authorization", sa.String(), nullable=False),
            sa.Column("data_flow", sa.String(), nullable=False),
            sa.Column("region", sa.String(), nullable=False),
            sa.Column("risk_tier", sa.String(), nullable=False),
            sa.Column("auth_method", sa.String(), nullable=False),
            sa.Column("scopes_requested", sa.JSON(), nullable=False),
            sa.Column("scopes_approved", sa.JSON(), nullable=False),
            _user("owner_user_id"),
            sa.Column("gates", sa.JSON(), nullable=False),
            _user("created_by", nullable=False),
            _ts("created_at", nullable=False),
            _user("decided_by"),
            _ts("decided_at"),
            _ts("updated_at", nullable=False),
            sa.Column("history", sa.JSON(), nullable=False),
            sa.UniqueConstraint("tenant_id", "ref", name="uq_integration_record_ref"),
        )
        op.create_index("ix_integration_records_tenant_id", "integration_records", ["tenant_id"])

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
    for table in ("integration_records", "provider_records", "operations_alerts", "service_owners",
                  "service_health_samples"):
        op.drop_table(table)
