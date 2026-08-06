"""Dynamic Visualization Selection v8 preferences.

Revision ID: c8d9e0f1a2b3
Revises: b4682276e830
"""
from alembic import op
import sqlalchemy as sa

revision = "c8d9e0f1a2b3"
down_revision = "b4682276e830"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    # v4-v7 originally relied on application create_all(). Bring those
    # tables into the Alembic chain without colliding with existing installs.
    if "visualization_telemetry_events" not in existing:
        op.create_table(
            "visualization_telemetry_events",
            sa.Column("id", sa.String(), primary_key=True), sa.Column("event_name", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False), sa.Column("actor_id", sa.String()),
            sa.Column("conversation_id", sa.String()), sa.Column("query_id", sa.String()),
            sa.Column("analytical_intent", sa.String()), sa.Column("original_chart_type", sa.String()),
            sa.Column("active_chart_type", sa.String()), sa.Column("alternative_count", sa.Integer()),
            sa.Column("selection_source", sa.String()), sa.Column("renderer", sa.String()),
            sa.Column("schema_version", sa.String()), sa.Column("chart_family", sa.String()),
            sa.Column("ranking_version", sa.String()), sa.Column("experiment_id", sa.String()),
            sa.Column("experiment_group", sa.String()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("event_name", "tenant_id", "actor_id", "conversation_id", "created_at", "ranking_version", "experiment_id"):
            op.create_index(f"ix_visualization_telemetry_events_{column}", "visualization_telemetry_events", [column])
    if "ranking_configurations" not in existing:
        op.create_table(
            "ranking_configurations", sa.Column("id", sa.String(), primary_key=True),
            sa.Column("ranking_version", sa.String(), nullable=False), sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("weights", sa.JSON(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False), sa.Column("approved_by", sa.String()),
            sa.Column("approved_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("ranking_version", name="uq_ranking_configurations_ranking_version"),
        )
        op.create_index("ix_ranking_configurations_status", "ranking_configurations", ["status"])
        op.create_index("ix_ranking_configurations_created_at", "ranking_configurations", ["created_at"])
    if "ranking_experiments" not in existing:
        op.create_table(
            "ranking_experiments", sa.Column("id", sa.String(), primary_key=True), sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("control_ranking_version", sa.String(), nullable=False), sa.Column("variant_ranking_version", sa.String(), nullable=False),
            sa.Column("control_allocation_percent", sa.Float(), nullable=False), sa.Column("variant_allocation_percent", sa.Float(), nullable=False),
            sa.Column("targeting_rules", sa.JSON(), nullable=False), sa.Column("primary_metrics", sa.JSON(), nullable=False),
            sa.Column("secondary_metrics", sa.JSON(), nullable=False), sa.Column("guardrail_metrics", sa.JSON(), nullable=False),
            sa.Column("minimum_sample_size", sa.Integer()), sa.Column("start_at", sa.DateTime(timezone=True)),
            sa.Column("end_at", sa.DateTime(timezone=True)), sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("approved_by", sa.String()), sa.Column("status_reason", sa.String()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_ranking_experiments_status", "ranking_experiments", ["status"])
        op.create_index("ix_ranking_experiments_created_at", "ranking_experiments", ["created_at"])
    op.create_table(
        "visualization_preferences",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "actor_id", name="uq_visualization_preferences_scope"),
    )
    op.create_index("ix_visualization_preferences_tenant_id", "visualization_preferences", ["tenant_id"])
    op.create_index("ix_visualization_preferences_actor_id", "visualization_preferences", ["actor_id"])
    op.add_column("visualization_telemetry_events", sa.Column("preference_affected_selection", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("visualization_telemetry_events", "preference_affected_selection")
    op.drop_table("visualization_preferences")
