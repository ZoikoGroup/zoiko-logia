"""add disposal columns to emergency_safety_blocks

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-27 00:00:00.000000

Wires up ZL-T0-04 §14's Emergency Safety Block, previously an unused
model with no service function ever creating, checking, or disposing of
one. §15's audit catalog requires an emergency_safety_block_disposed event
covering "both expiry and manual release/rollback" — these columns are
what record which disposition happened and who reviewed it, beyond just
comparing against expires_at.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('emergency_safety_blocks', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('emergency_safety_blocks', sa.Column('disposed_at', sa.DateTime(), nullable=True))
    op.add_column('emergency_safety_blocks', sa.Column('disposition', sa.String(), nullable=True))
    op.add_column('emergency_safety_blocks', sa.Column('reviewer', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('emergency_safety_blocks', 'reviewer')
    op.drop_column('emergency_safety_blocks', 'disposition')
    op.drop_column('emergency_safety_blocks', 'disposed_at')
    op.drop_column('emergency_safety_blocks', 'is_active')
