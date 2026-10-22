"""Private conversation input and calculation memory.

Revision ID: a6t7u8v9w0x1
Revises: z5s6t7u8v9w0
"""
from alembic import op
import sqlalchemy as sa

revision = 'a6t7u8v9w0x1'
down_revision = 'z5s6t7u8v9w0'
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table('conversation_turns'):
        op.create_table(
            'conversation_turns',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('tenant_id', sa.String(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('conversation_id', sa.String(), nullable=False),
            sa.Column('query_id', sa.String(), nullable=False),
            sa.Column('user_text', sa.Text(), nullable=False),
            sa.Column('snapshot', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('tenant_id', 'user_id', 'query_id', name='uq_conversation_turn_query'),
        )
        op.create_index('ix_conversation_turn_scope', 'conversation_turns',
                        ['tenant_id', 'user_id', 'conversation_id', 'created_at'])
    if op.get_bind().dialect.name == 'postgresql':
        predicate = "tenant_id = current_setting('app.tenant_id', true) AND user_id = current_setting('app.user_id', true)"
        op.execute('ALTER TABLE conversation_turns ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE conversation_turns FORCE ROW LEVEL SECURITY')
        op.execute('DROP POLICY IF EXISTS tenant_isolation_conversation_turns ON conversation_turns')
        op.execute(f'CREATE POLICY tenant_isolation_conversation_turns ON conversation_turns USING ({predicate}) WITH CHECK ({predicate})')


def downgrade():
    op.drop_table('conversation_turns')
