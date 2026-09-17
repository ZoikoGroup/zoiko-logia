"""compatibility bridge for databases stamped by the deployed schema line

Revision ID: i4d5e6f7g8h9
Revises: a1b2c3d4e5f6

The deployed database carries this revision but its historical migration file
is not present in this checkout.  Current ORM/startup migrations already
reconcile the schema it represents, so this bridge restores a continuous
Alembic graph without replaying unknown DDL.
"""
from typing import Sequence, Union

revision: str = "i4d5e6f7g8h9"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
