"""V10 consent-based visualization personalization.

Adds the personalization consent, learned-profile, and recomputation-run
tables, plus four privacy-safe metadata columns on the existing
visualization_telemetry_events table.

Revision ID: h3c4d5e6f7g8
Revises: g2b3c4d5e6f7
"""
from alembic import op
import sqlalchemy as sa

revision = "h3c4d5e6f7g8"
down_revision = "g2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("visualization_telemetry_events", sa.Column("personalization_enabled", sa.Boolean()))
    op.add_column("visualization_telemetry_events", sa.Column("personalization_affected_selection", sa.Boolean()))
    op.add_column("visualization_telemetry_events", sa.Column("personalization_model_version", sa.String()))
    op.add_column("visualization_telemetry_events", sa.Column("personalization_confidence_band", sa.String()))

    op.create_table(
        "visualization_personalization_consents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("personalization_enabled", sa.Boolean(), nullable=False),
        sa.Column("personalization_scope", sa.String(), nullable=False),
        sa.Column("personalization_history_window", sa.String(), nullable=False),
        sa.Column("allow_view_switch_learning", sa.Boolean(), nullable=False),
        sa.Column("allow_export_learning", sa.Boolean(), nullable=False),
        sa.Column("allow_save_learning", sa.Boolean(), nullable=False),
        sa.Column("consent_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "actor_id", name="uq_visualization_personalization_consents_scope"),
    )
    op.create_table(
        "visualization_personalization_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("consent_status", sa.String(), nullable=False),
        sa.Column("consent_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_window_start", sa.Date()),
        sa.Column("evidence_window_end", sa.Date()),
        sa.Column("interaction_count", sa.Integer(), nullable=False),
        sa.Column("conversation_count", sa.Integer(), nullable=False),
        sa.Column("chart_family_preferences", sa.JSON(), nullable=False),
        sa.Column("intent_chart_preferences", sa.JSON(), nullable=False),
        sa.Column("table_preference_signal", sa.Float()),
        sa.Column("density_preference_signal", sa.Float()),
        sa.Column("confidence_by_signal", sa.JSON(), nullable=False),
        sa.Column("last_recomputed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "actor_id", name="uq_visualization_personalization_profiles_scope"),
    )
    op.create_table(
        "visualization_personalization_recomputation_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("processing_date", sa.String(), nullable=False),
        sa.Column("profile_version", sa.String(), nullable=False),
        sa.Column("profiles_recomputed_count", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("failure_category", sa.String()),
        sa.Column("triggered_by", sa.String(), nullable=False),
    )
    op.create_index("ix_visualization_personalization_consents_tenant_id", "visualization_personalization_consents", ["tenant_id"])
    op.create_index("ix_visualization_personalization_consents_actor_id", "visualization_personalization_consents", ["actor_id"])
    op.create_index("ix_visualization_personalization_profiles_tenant_id", "visualization_personalization_profiles", ["tenant_id"])
    op.create_index("ix_visualization_personalization_profiles_actor_id", "visualization_personalization_profiles", ["actor_id"])
    op.create_index("ix_visualization_personalization_recomputation_runs_tenant_id", "visualization_personalization_recomputation_runs", ["tenant_id"])
    op.create_index("ix_visualization_personalization_recomputation_runs_started_at", "visualization_personalization_recomputation_runs", ["started_at"])
    op.create_index("ix_visualization_personalization_recomputation_runs_status", "visualization_personalization_recomputation_runs", ["status"])
    op.create_index("ix_visualization_personalization_recomputation_runs_processing_date", "visualization_personalization_recomputation_runs", ["processing_date"])


def downgrade() -> None:
    op.drop_index("ix_visualization_personalization_recomputation_runs_processing_date", table_name="visualization_personalization_recomputation_runs")
    op.drop_index("ix_visualization_personalization_recomputation_runs_status", table_name="visualization_personalization_recomputation_runs")
    op.drop_index("ix_visualization_personalization_recomputation_runs_started_at", table_name="visualization_personalization_recomputation_runs")
    op.drop_index("ix_visualization_personalization_recomputation_runs_tenant_id", table_name="visualization_personalization_recomputation_runs")
    op.drop_index("ix_visualization_personalization_profiles_actor_id", table_name="visualization_personalization_profiles")
    op.drop_index("ix_visualization_personalization_profiles_tenant_id", table_name="visualization_personalization_profiles")
    op.drop_index("ix_visualization_personalization_consents_actor_id", table_name="visualization_personalization_consents")
    op.drop_index("ix_visualization_personalization_consents_tenant_id", table_name="visualization_personalization_consents")
    op.drop_table("visualization_personalization_recomputation_runs")
    op.drop_table("visualization_personalization_profiles")
    op.drop_table("visualization_personalization_consents")
    op.drop_column("visualization_telemetry_events", "personalization_confidence_band")
    op.drop_column("visualization_telemetry_events", "personalization_model_version")
    op.drop_column("visualization_telemetry_events", "personalization_affected_selection")
    op.drop_column("visualization_telemetry_events", "personalization_enabled")
