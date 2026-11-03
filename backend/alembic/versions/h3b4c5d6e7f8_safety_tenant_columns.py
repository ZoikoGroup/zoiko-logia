"""Add tenant_id to safety_events, safety_overrides and escalation_cases where
it is missing.

The ORM has carried tenant_id on these three tables (risk_safety/models.py)
but no migration created it, so a database built only from migrations could
not record the risk_classification_applied event and every /ask failed with
503. Found by the WF-01 end-to-end run on a freshly migrated database. The
column is added only where absent, with the model's default, so a database
that already has it is unchanged.

Revision ID: h3b4c5d6e7f8
Revises: g2a3b4c5d6e7
"""
from typing import Sequence, Union

from alembic import op

revision: str = "h3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "g2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("safety_events", "safety_overrides", "escalation_cases")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id VARCHAR NOT NULL DEFAULT 'GLOBAL_CONTROL'")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")


def downgrade() -> None:
    # Not reversible safely: on a database that already had the column, this
    # migration changed nothing, and dropping it would destroy tenant ownership.
    pass
