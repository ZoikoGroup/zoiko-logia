"""Composite index on audit_events (tenant_id, ingested_at).

The Governance Dashboard counts a tenant's events in the last N days, the
notification sweep and the status page read a tenant's latest events; with
only single-column indexes the 30-day count took ~2.9s over 138k rows.
Created CONCURRENTLY so writes to the ledger are never blocked.

Revision ID: x3q4r5s6t7u8
Revises: u1n2o3p4q5r6
"""
from alembic import op

revision = "x3q4r5s6t7u8"  # was t9m0n1o2p3q4, which main now uses
down_revision = "u1n2o3p4q5r6"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_events_tenant_ingested_at "
                   "ON audit_events (tenant_id, ingested_at)")


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_audit_events_tenant_ingested_at")
