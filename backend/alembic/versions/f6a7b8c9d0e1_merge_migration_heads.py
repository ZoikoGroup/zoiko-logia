"""merge safety-tenant and application-schema migration branches"""
from typing import Sequence, Union

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = (
    "b7c8d9e0f1a2",
    "e5f6a7b8c9d0",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
