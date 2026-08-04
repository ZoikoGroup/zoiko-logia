"""add conversations and chat_messages tables (chat_history domain)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-25 00:00:00.000000

Note: the live database's alembic_version currently points at a revision
('b1c2d3e4f5a6') not present in this versions/ directory — pre-existing
drift from before this migration, not introduced by it (see the
tenant_id NOT NULL findings on safety_events/safety_overrides/
escalation_cases for the same underlying pattern: manual DB changes made
outside the tracked migration history). This migration is written to chain
cleanly onto the last migration that IS present locally (b2c3d4e5f6a7) so a
fresh environment built from these files alone gets a correct, complete
history; reconciling the live alembic_version pointer is a separate,
pre-existing issue this migration does not attempt to fix.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conversations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('jurisdiction', sa.String(), nullable=False),
        sa.Column('mode', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_conversations_user_updated', 'conversations', ['user_id', 'updated_at'])

    op.create_table(
        'chat_messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('conversation_id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('route', sa.String(), nullable=True),
        sa.Column('risk_level', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chat_messages_conversation_created', 'chat_messages', ['conversation_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_chat_messages_conversation_created', table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index('ix_conversations_user_updated', table_name='conversations')
    op.drop_table('conversations')
