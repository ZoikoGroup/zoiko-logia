"""governed learning phases one through four

Revision ID: j9d0e1f2g3h4
Revises: h8c9d0e1f2g3
"""
from alembic import op
import sqlalchemy as sa

revision = "j9d0e1f2g3h4"
down_revision = "h8c9d0e1f2g3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    def create_table(table_name, *columns):
        if not sa.inspect(bind).has_table(table_name):
            op.create_table(table_name, *columns)

    create_table("kriton_feedback_items", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False), sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False), sa.Column("query_id", sa.String(), nullable=False), sa.Column("correlation_id", sa.String()), sa.Column("query_text", sa.Text(), nullable=False), sa.Column("feedback_type", sa.String(), nullable=False), sa.Column("reason_code", sa.String(), nullable=False), sa.Column("correction", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True)))
    create_table("kriton_memory_items", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False), sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False), sa.Column("key", sa.String(), nullable=False), sa.Column("value", sa.Text(), nullable=False), sa.Column("scope", sa.String(), nullable=False), sa.Column("confirmed", sa.Boolean(), nullable=False), sa.Column("source_feedback_id", sa.String()), sa.Column("created_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("tenant_id", "user_id", "key", name="uq_kriton_memory_owner_key"))
    create_table("kriton_learning_candidates", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False), sa.Column("feedback_id", sa.String(), sa.ForeignKey("kriton_feedback_items.id"), nullable=False), sa.Column("query_text", sa.Text(), nullable=False), sa.Column("expected_answer", sa.Text(), nullable=False), sa.Column("reason_code", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("reviewer_id", sa.String()), sa.Column("review_note", sa.Text(), nullable=False), sa.Column("benchmark_case_id", sa.String()), sa.Column("created_at", sa.DateTime(timezone=True)), sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    create_table("kriton_workflow_definitions", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False), sa.Column("name", sa.String(), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("match_terms", sa.JSON(), nullable=False), sa.Column("plan", sa.JSON(), nullable=False), sa.Column("allowed_formats", sa.JSON(), nullable=False), sa.Column("risk_level", sa.String(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False), sa.Column("approved_by", sa.String()), sa.Column("created_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("tenant_id", "name", "version", name="uq_kriton_workflow_version"))
    create_table("kriton_source_update_reviews", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False), sa.Column("source_id", sa.String(), sa.ForeignKey("sources.id"), nullable=False), sa.Column("proposed_version_id", sa.String(), sa.ForeignKey("source_versions.id"), nullable=False), sa.Column("detected_by", sa.String(), nullable=False), sa.Column("content_hash", sa.String()), sa.Column("change_summary", sa.Text(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("submitted_by", sa.String(), nullable=False), sa.Column("reviewer_id", sa.String()), sa.Column("review_note", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True)), sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    for table, columns in {"kriton_feedback_items": ["tenant_id", "user_id", "query_id"], "kriton_memory_items": ["tenant_id", "user_id"], "kriton_learning_candidates": ["tenant_id", "status"], "kriton_workflow_definitions": ["tenant_id"], "kriton_source_update_reviews": ["tenant_id", "status"]}.items():
        for column in columns:
            index_name = f"ix_{table}_{column}"
            existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
            if index_name not in existing_indexes:
                op.create_index(index_name, table, [column])


def downgrade():
    for table in ["kriton_source_update_reviews", "kriton_workflow_definitions", "kriton_learning_candidates", "kriton_memory_items", "kriton_feedback_items"]:
        op.drop_table(table)
