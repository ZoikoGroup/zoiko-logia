"""Policy-driven model deployments and immutable run manifests.

Revision ID: q6j7k8l9m0n1
Revises: p5i6j7k8l9m0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "q6j7k8l9m0n1"
down_revision: Union[str, Sequence[str], None] = "p5i6j7k8l9m0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        sa.Column("deployment_region", sa.String(), nullable=False, server_default=""),
        sa.Column("permitted_data_classes", sa.JSON(), nullable=False, server_default='["PUBLIC"]'),
        sa.Column("supported_task_types", sa.JSON(), nullable=False, server_default='["general_question"]'),
        sa.Column("allowed_tools", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("retention_policy", sa.String(), nullable=False, server_default="UNREVIEWED"),
        sa.Column("training_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evaluation_manifest_id", sa.String(), nullable=True),
        sa.Column("policy_version", sa.String(), nullable=False, server_default="f7.1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("submitted_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        op.add_column("model_definitions", column)

    op.create_table(
        "model_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("deployment_id", sa.String(), sa.ForeignKey("model_definitions.id"), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("data_classification", sa.String(), nullable=False),
        sa.Column("processing_region", sa.String(), nullable=False, server_default=""),
        sa.Column("prompt_id", sa.String(), nullable=False, server_default="inline"),
        sa.Column("prompt_version", sa.String(), nullable=False, server_default="inline"),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("retrieval_version", sa.String(), nullable=True),
        sa.Column("tool_versions", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("requested_tools", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("attempts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=True),
        sa.Column("output_hash", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_runs_tenant_id", "model_runs", ["tenant_id"])
    op.create_index("ix_model_runs_correlation_id", "model_runs", ["correlation_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE model_runs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE model_runs FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY model_runs_tenant_isolation ON model_runs
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS model_runs_tenant_isolation ON model_runs")
    op.drop_index("ix_model_runs_correlation_id", table_name="model_runs")
    op.drop_index("ix_model_runs_tenant_id", table_name="model_runs")
    op.drop_table("model_runs")
    for name in (
        "approved_at", "approved_by", "submitted_by", "enabled", "priority", "policy_version", "evaluation_manifest_id",
        "training_opt_out", "retention_policy", "allowed_tools",
        "supported_task_types", "permitted_data_classes", "deployment_region",
    ):
        op.drop_column("model_definitions", name)
