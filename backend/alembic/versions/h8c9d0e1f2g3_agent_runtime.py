"""add durable agent runtime tables

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8c9d0e1f2g3"
down_revision: Union[str, Sequence[str], None] = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("agent_runs"):
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=True),
            sa.Column("goal", sa.Text(), nullable=False),
            sa.Column("task_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("risk_level", sa.String(), nullable=False),
            sa.Column("current_step", sa.Integer(), nullable=False),
            sa.Column("maximum_steps", sa.Integer(), nullable=False),
            sa.Column("plan", sa.JSON(), nullable=False),
            sa.Column("working_state", sa.JSON(), nullable=False),
            sa.Column("final_response", sa.JSON(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    run_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("agent_runs")}
    for column in ("tenant_id", "user_id", "conversation_id", "status"):
        index_name = f"ix_agent_runs_{column}"
        if index_name not in run_indexes:
            op.create_index(index_name, "agent_runs", [column])

    if not sa.inspect(bind).has_table("agent_steps"):
        op.create_table("agent_steps",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("decision_type", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("tool_arguments", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result_reference", sa.String(), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_step_run_sequence"),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uq_agent_step_idempotency"),
    )
    step_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("agent_steps")}
    for column in ("run_id", "tenant_id", "user_id", "status"):
        index_name = f"ix_agent_steps_{column}"
        if index_name not in step_indexes:
            op.create_index(index_name, "agent_steps", [column])


def downgrade() -> None:
    op.drop_table("agent_steps")
    op.drop_table("agent_runs")
