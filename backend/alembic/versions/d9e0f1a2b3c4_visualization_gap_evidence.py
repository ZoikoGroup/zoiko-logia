"""V8.2 visualization gap evidence. Revision ID: d9e0f1a2b3c4"""
from alembic import op
import sqlalchemy as sa
revision="d9e0f1a2b3c4"; down_revision="c8d9e0f1a2b3"; branch_labels=None; depends_on=None

def upgrade():
    op.add_column("visualization_telemetry_events", sa.Column("environment",sa.String(),nullable=True))
    op.create_table("visualization_gap_events",
        sa.Column("id",sa.String(),primary_key=True), sa.Column("dedup_key",sa.String(),nullable=False),
        sa.Column("tenant_id",sa.String(),nullable=False), sa.Column("actor_id",sa.String()), sa.Column("conversation_id",sa.String()),
        sa.Column("analytical_intent",sa.String()), sa.Column("requested_chart_type",sa.String(),nullable=False),
        sa.Column("requested_visualization_family",sa.String(),nullable=False), sa.Column("gap_type",sa.String(),nullable=False),
        sa.Column("data_shape_class",sa.String(),nullable=False), sa.Column("fallback_chart_type",sa.String()),
        sa.Column("fallback_output_type",sa.String(),nullable=False), sa.Column("registry_candidate_count",sa.Integer(),nullable=False),
        sa.Column("ranking_version",sa.String(),nullable=False), sa.Column("schema_version",sa.String(),nullable=False),
        sa.Column("environment",sa.String(),nullable=False), sa.Column("valid_evidence",sa.Boolean(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("dedup_key", name="uq_visualization_gap_events_dedup_key"))
    op.create_table("visualization_gap_reports", sa.Column("id",sa.String(),primary_key=True), sa.Column("tenant_id",sa.String(),nullable=False),
        sa.Column("period_start",sa.Date(),nullable=False), sa.Column("period_end",sa.Date(),nullable=False), sa.Column("evidence_version",sa.String(),nullable=False),
        sa.Column("approved_findings",sa.JSON(),nullable=False), sa.Column("status",sa.String(),nullable=False), sa.Column("created_by",sa.String(),nullable=False),
        sa.Column("approved_by",sa.String()), sa.Column("approved_at",sa.DateTime(timezone=True)), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_visualization_telemetry_events_environment", "visualization_telemetry_events", ["environment"])
    op.create_index("ix_visualization_gap_events_tenant_id", "visualization_gap_events", ["tenant_id"])
    op.create_index("ix_visualization_gap_events_requested_chart_type", "visualization_gap_events", ["requested_chart_type"])
    op.create_index("ix_visualization_gap_events_environment", "visualization_gap_events", ["environment"])
    op.create_index("ix_visualization_gap_events_created_at", "visualization_gap_events", ["created_at"])
    op.create_index("ix_visualization_gap_reports_tenant_id", "visualization_gap_reports", ["tenant_id"])

def downgrade():
    op.drop_index("ix_visualization_gap_reports_tenant_id", table_name="visualization_gap_reports")
    op.drop_table("visualization_gap_reports")
    op.drop_table("visualization_gap_events")
    op.drop_index("ix_visualization_telemetry_events_environment", table_name="visualization_telemetry_events")
    op.drop_column("visualization_telemetry_events","environment")
