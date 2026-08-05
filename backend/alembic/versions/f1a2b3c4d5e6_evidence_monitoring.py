"""V8.4 evidence monitoring — aggregation runs and reviewer-alert dedup.

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visualization_evidence_aggregation_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_version", sa.String(), nullable=False),
        sa.Column("valid_event_count", sa.Integer(), nullable=False),
        sa.Column("distinct_conversation_count", sa.Integer(), nullable=False),
        sa.Column("distinct_actor_count", sa.Integer(), nullable=False),
        sa.Column("eligible_finding_count", sa.Integer(), nullable=False),
        sa.Column("created_report_id", sa.String()),
        sa.Column("triggered_by", sa.String(), nullable=False),
    )
    op.create_table(
        "visualization_evidence_alerts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("evidence_version", sa.String(), nullable=False),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "evidence_version", name="uq_visualization_evidence_alerts_scope"),
    )
    op.create_index("ix_visualization_evidence_aggregation_runs_tenant_id", "visualization_evidence_aggregation_runs", ["tenant_id"])
    op.create_index("ix_visualization_evidence_aggregation_runs_run_at", "visualization_evidence_aggregation_runs", ["run_at"])
    op.create_index("ix_visualization_evidence_alerts_tenant_id", "visualization_evidence_alerts", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_visualization_evidence_alerts_tenant_id", table_name="visualization_evidence_alerts")
    op.drop_table("visualization_evidence_alerts")
    op.drop_index("ix_visualization_evidence_aggregation_runs_run_at", table_name="visualization_evidence_aggregation_runs")
    op.drop_index("ix_visualization_evidence_aggregation_runs_tenant_id", table_name="visualization_evidence_aggregation_runs")
    op.drop_table("visualization_evidence_aggregation_runs")
