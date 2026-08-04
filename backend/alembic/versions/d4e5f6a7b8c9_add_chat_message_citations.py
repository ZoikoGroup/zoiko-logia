"""add citations column to chat_messages

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-25 00:00:00.000000

Without this, reopening a past conversation had no citations to show at
all — the assistant message row only carried route/risk_level, and the
frontend fell back to an empty citations list on every historical message.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_messages', sa.Column('citations', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_messages', 'citations')
