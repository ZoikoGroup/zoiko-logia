"""Password reset by emailed code: password_reset_challenges.

Not under RLS: a reset happens before sign-in, when no tenant is known, and
the table holds only a keyed hash of the code, its owner and timestamps.

Revision ID: v1o2p3q4r5s6
Revises: u0n1o2p3q4r5
"""
from alembic import op
import sqlalchemy as sa

revision = "v1o2p3q4r5s6"
down_revision = "u0n1o2p3q4r5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "password_reset_challenges" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "password_reset_challenges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("salt", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_password_reset_challenges_user_id", "password_reset_challenges", ["user_id"])


def downgrade():
    op.drop_table("password_reset_challenges")
