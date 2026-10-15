"""Review, Escalation & Audit console: escalation assignment and history,
full support tickets (subject, description, SLA clock, conversation), incident
links to audit events and tickets, and audit export requests.

Every new column is nullable, so existing rows stay valid unchanged.
audit_export_requests is tenant isolated by RLS like every tenant table.

Revision ID: u0n1o2p3q4r5
Revises: t9m0n1o2p3q4
"""
from alembic import op
import sqlalchemy as sa

revision = "u0n1o2p3q4r5"
down_revision = "t9m0n1o2p3q4"
branch_labels = None
depends_on = None

_NEW_COLUMNS = {
    "escalation_cases": [
        ("assigned_to", sa.String()), ("origin", sa.String()), ("created_by", sa.String()), ("history", sa.JSON()),
    ],
    "support_tickets": [
        ("subject", sa.String()), ("description", sa.Text()), ("jurisdiction", sa.String()),
        ("first_response_at", sa.DateTime(timezone=True)), ("resolved_at", sa.DateTime(timezone=True)),
        ("resolution_note", sa.Text()), ("waiting_since", sa.DateTime(timezone=True)), ("paused_seconds", sa.Integer()),
        ("escalation_id", sa.String()), ("incident_id", sa.String()), ("messages", sa.JSON()),
    ],
    "security_incidents": [("linked_event_ids", sa.JSON()), ("ticket_id", sa.String())],
}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, columns in _NEW_COLUMNS.items():
        if table not in tables:
            continue  # created complete by the application's setup
        present = {c["name"] for c in inspector.get_columns(table)}
        for name, type_ in columns:
            if name not in present:
                op.add_column(table, sa.Column(name, type_, nullable=True))

    if "audit_export_requests" not in tables:
        op.create_table(
            "audit_export_requests",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("ref", sa.String(), nullable=False),
            sa.Column("purpose", sa.Text(), nullable=False),
            sa.Column("filters", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("requested_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("decided_by", sa.String(), sa.ForeignKey("users.id")),
            sa.Column("decided_at", sa.DateTime(timezone=True)),
            sa.Column("decision_note", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("downloads", sa.Integer(), nullable=False),
            sa.UniqueConstraint("tenant_id", "ref", name="uq_audit_export_ref"),
        )
        op.create_index("ix_audit_export_requests_tenant_id", "audit_export_requests", ["tenant_id"])

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE audit_export_requests ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE audit_export_requests FORCE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS tenant_isolation_audit_export_requests ON audit_export_requests")
        op.execute(
            "CREATE POLICY tenant_isolation_audit_export_requests ON audit_export_requests "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade():
    op.drop_table("audit_export_requests")
    for table, columns in _NEW_COLUMNS.items():
        for name, _ in columns:
            op.drop_column(table, name)
