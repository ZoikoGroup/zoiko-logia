"""Persist the formal V9 input artifact.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
"""
from alembic import op
import sqlalchemy as sa

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("visualization_gap_reports", sa.Column("artifact", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.alter_column("visualization_gap_reports", "artifact", server_default=None)


def downgrade() -> None:
    op.drop_column("visualization_gap_reports", "artifact")
