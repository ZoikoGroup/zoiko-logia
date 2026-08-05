"""V8.5 evidence monitoring — full run-lifecycle bookkeeping.

Renames visualization_evidence_aggregation_runs.run_at to started_at and
adds the outcome/idempotency columns the scheduled-monitoring operational
job and admin status panel need: completed_at, status, monitoring_period,
trigger_source, draft_created, alert_created, failure_category.

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""
from alembic import op
import sqlalchemy as sa

revision = "g2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None

_TABLE = "visualization_evidence_aggregation_runs"


def upgrade() -> None:
    op.alter_column(_TABLE, "run_at", new_column_name="started_at")
    op.add_column(_TABLE, sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.add_column(_TABLE, sa.Column("status", sa.String(), nullable=False, server_default="succeeded"))
    op.add_column(_TABLE, sa.Column("monitoring_period", sa.String(), nullable=False, server_default=""))
    op.add_column(_TABLE, sa.Column("trigger_source", sa.String(), nullable=False, server_default="manual"))
    op.add_column(_TABLE, sa.Column("draft_created", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(_TABLE, sa.Column("alert_created", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(_TABLE, sa.Column("failure_category", sa.String()))
    op.alter_column(_TABLE, "status", server_default=None)
    op.alter_column(_TABLE, "monitoring_period", server_default=None)
    op.alter_column(_TABLE, "trigger_source", server_default=None)
    op.alter_column(_TABLE, "draft_created", server_default=None)
    op.alter_column(_TABLE, "alert_created", server_default=None)
    op.create_index(f"ix_{_TABLE}_status", _TABLE, ["status"])
    op.create_index(f"ix_{_TABLE}_monitoring_period", _TABLE, ["monitoring_period"])


def downgrade() -> None:
    op.drop_index(f"ix_{_TABLE}_monitoring_period", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_status", table_name=_TABLE)
    op.drop_column(_TABLE, "failure_category")
    op.drop_column(_TABLE, "alert_created")
    op.drop_column(_TABLE, "draft_created")
    op.drop_column(_TABLE, "trigger_source")
    op.drop_column(_TABLE, "monitoring_period")
    op.drop_column(_TABLE, "status")
    op.drop_column(_TABLE, "completed_at")
    op.alter_column(_TABLE, "started_at", new_column_name="run_at")
