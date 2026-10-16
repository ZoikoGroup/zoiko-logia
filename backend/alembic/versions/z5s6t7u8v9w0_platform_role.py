"""Platform role on users: the Super Admin control plane is granted
separately from the tenant role, so a tenant Admin never inherits it.

Revision ID: z5s6t7u8v9w0
Revises: y4r5s6t7u8v9
"""
from alembic import op
import sqlalchemy as sa

revision = "z5s6t7u8v9w0"  # was x3q4r5s6t7u8, which the audit index migration on main uses
down_revision = "y4r5s6t7u8v9"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: databases that ran this under its earlier revision id
    # already have the column.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    if "platform_role" not in columns:
        op.add_column("users", sa.Column("platform_role", sa.String(), nullable=True))


def downgrade():
    op.drop_column("users", "platform_role")
