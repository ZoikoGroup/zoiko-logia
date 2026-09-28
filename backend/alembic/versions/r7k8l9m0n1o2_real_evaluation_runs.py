"""Real candidate evaluation, review evidence and release scorecards.

Revision ID: r7k8l9m0n1o2
Revises: q6j7k8l9m0n1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "r7k8l9m0n1o2"
down_revision: Union[str, Sequence[str], None] = "q6j7k8l9m0n1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("tenant_id", sa.String(), nullable=False, server_default="GLOBAL_CONTROL"),
        sa.Column("split", sa.String(), nullable=False, server_default="development"),
        sa.Column("frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
    ):
        op.add_column("evaluation_datasets", column)
    op.create_index("ix_evaluation_datasets_tenant_id", "evaluation_datasets", ["tenant_id"])

    op.add_column(
        "threshold_sets",
        sa.Column("tenant_id", sa.String(), nullable=False, server_default="GLOBAL_CONTROL"),
    )
    op.add_column("threshold_sets", sa.Column("status", sa.String(), nullable=False, server_default="PendingReview"))
    op.add_column("threshold_sets", sa.Column("submitted_by", sa.String(), nullable=True))
    op.add_column("threshold_sets", sa.Column("approved_by", sa.String(), nullable=True))
    op.add_column("threshold_sets", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_threshold_sets_tenant_id", "threshold_sets", ["tenant_id"])

    for column in (
        sa.Column("task_context", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("expected_claims", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("expected_calculations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("acceptable_statuses", sa.JSON(), nullable=False, server_default='["answered"]'),
        sa.Column("critical_error_types", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("document_family", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=False, server_default="en"),
        sa.Column("reviewer_provenance", sa.String(), nullable=True),
        sa.Column("fingerprint", sa.String(), nullable=False, server_default=""),
    ):
        op.add_column("benchmark_cases", column)
    op.create_index("ix_benchmark_cases_fingerprint", "benchmark_cases", ["fingerprint"])

    for column in (
        sa.Column("tenant_id", sa.String(), nullable=False, server_default="GLOBAL_CONTROL"),
        sa.Column("started_by", sa.String(), nullable=True),
        sa.Column("candidate_manifest", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
    ):
        op.add_column("evaluation_runs", column)
    op.create_index("ix_evaluation_runs_tenant_id", "evaluation_runs", ["tenant_id"])

    for column in (
        sa.Column("failure_reports", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("slice_metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("reviewed_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    ):
        op.add_column("result_packs", column)

    op.create_table(
        "evaluation_case_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", sa.String(), sa.ForeignKey("benchmark_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("response_status", sa.String(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("trace", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("latency_seconds", sa.Float(), nullable=False),
        sa.Column("source_recall", sa.Float(), nullable=True),
        sa.Column("citation_precision", sa.Float(), nullable=True),
        sa.Column("numeric_correctness", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("review_status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evaluation_case_results_run_id", "evaluation_case_results", ["run_id"])
    op.create_index("ix_evaluation_case_results_case_id", "evaluation_case_results", ["case_id"])

    op.create_table(
        "evaluation_reviewer_judgments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_result_id", sa.String(), sa.ForeignKey("evaluation_case_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("metric_scores", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("critical_errors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("adjudication", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evaluation_reviewer_judgments_case_result_id", "evaluation_reviewer_judgments", ["case_result_id"])

    if op.get_bind().dialect.name == "postgresql":
        for table in ("evaluation_datasets", "evaluation_runs", "threshold_sets"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("threshold_sets", "evaluation_runs", "evaluation_datasets"):
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.drop_index("ix_evaluation_reviewer_judgments_case_result_id", table_name="evaluation_reviewer_judgments")
    op.drop_table("evaluation_reviewer_judgments")
    op.drop_index("ix_evaluation_case_results_case_id", table_name="evaluation_case_results")
    op.drop_index("ix_evaluation_case_results_run_id", table_name="evaluation_case_results")
    op.drop_table("evaluation_case_results")
    for name in ("complete", "expected_case_count", "reviewed_case_count", "slice_metrics", "failure_reports"):
        op.drop_column("result_packs", name)
    op.drop_index("ix_evaluation_runs_tenant_id", table_name="evaluation_runs")
    for name in ("failure_reason", "completed_at", "case_count", "candidate_manifest", "started_by", "tenant_id"):
        op.drop_column("evaluation_runs", name)
    op.drop_index("ix_benchmark_cases_fingerprint", table_name="benchmark_cases")
    for name in ("fingerprint", "reviewer_provenance", "language", "document_family", "critical_error_types", "acceptable_statuses", "expected_calculations", "expected_claims", "task_context"):
        op.drop_column("benchmark_cases", name)
    op.drop_index("ix_evaluation_datasets_tenant_id", table_name="evaluation_datasets")
    for name in ("created_by", "frozen_at", "frozen", "split", "tenant_id"):
        op.drop_column("evaluation_datasets", name)
    op.drop_index("ix_threshold_sets_tenant_id", table_name="threshold_sets")
    for name in ("approved_at", "approved_by", "submitted_by", "status", "tenant_id"):
        op.drop_column("threshold_sets", name)
