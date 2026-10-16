"""In-app notifications, the per-tenant ledger cursor that feeds them, and
per-user settings.

Notification rows are only ever read by their recipient (filtered by user_id
in notifications_workflow.service) and are written by the system sweep, so
they carry no RLS policy, like audit-derived read models elsewhere.

Revision ID: u1n2o3p4q5r6
Revises: w2p3q4r5s6t7
"""
from alembic import op
import sqlalchemy as sa

revision = "u1n2o3p4q5r6"
# Follows Workpapers (s8l9m0n1o2p3), which took this slot in main first.
down_revision = "w2p3q4r5s6t7"  # after main's billing (was s8l9m0n1o2p3)
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "notifications" not in existing:
        op.create_table(
            "notifications",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("body", sa.String(), nullable=False),
            sa.Column("link", sa.String(), nullable=False),
            sa.Column("source_event_id", sa.String(), nullable=False),
            _ts("created_at", nullable=False),
            _ts("read_at"),
            sa.UniqueConstraint("user_id", "source_event_id", "kind", name="uq_notification_once"),
        )
        op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
        op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
        op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    if "notification_cursors" not in existing:
        op.create_table(
            "notification_cursors",
            sa.Column("tenant_id", sa.String(), primary_key=True),
            _ts("last_ingested_at", nullable=False),
        )

    if "user_settings" not in existing:
        op.create_table(
            "user_settings",
            sa.Column("user_id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("preferences", sa.JSON(), nullable=False),
            _ts("updated_at", nullable=False),
        )
        op.create_index("ix_user_settings_tenant_id", "user_settings", ["tenant_id"])


def downgrade():
    for table in ("user_settings", "notification_cursors", "notifications"):
        op.drop_table(table)
