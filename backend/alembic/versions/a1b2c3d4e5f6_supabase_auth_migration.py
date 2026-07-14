"""supabase auth migration: users profile columns + self-row RLS

Revision ID: a1b2c3d4e5f6
Revises: 6e756620f1c6
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '6e756620f1c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# WITH CHECK mirrors USING (not just self-id) so a tenant Admin can still
# insert a new teammate row (POST /users) — that row's id is the new
# teammate's, not the admin's own app.user_id. Keyed off app.user_id (set by
# get_db from the verified Supabase token), not Supabase's own auth.uid() —
# that only resolves through Supabase's own PostgREST/GoTrue layer, never
# through this backend's plain SQLAlchemy/asyncpg connection.
#
# The admin check goes through a SECURITY DEFINER function rather than an
# inline subquery on `users` — a policy on `users` that queries `users`
# again has that inner query evaluated under the same policy too, and
# Postgres rejects it as infinite recursion. A SECURITY DEFINER function
# runs as its owner (a superuser here), bypassing RLS for its internal
# query and breaking the self-reference.
_ADMIN_OR_SELF_PREDICATE = """(
    id = current_setting('app.user_id', true)
    OR _is_requester_tenant_admin(tenant_id)
)"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('first_name', sa.String(), nullable=False, server_default=''))
    op.add_column('users', sa.Column('last_name', sa.String(), nullable=False, server_default=''))
    op.add_column('users', sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')))
    op.drop_column('users', 'hashed_password')

    op.execute('ALTER TABLE users ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE users FORCE ROW LEVEL SECURITY')
    op.execute("""
        CREATE OR REPLACE FUNCTION _is_requester_tenant_admin(target_tenant_id VARCHAR)
        RETURNS boolean
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM users
                WHERE id = current_setting('app.user_id', true)
                  AND role = 'Admin'
                  AND tenant_id = target_tenant_id
            )
        $$
    """)
    op.execute(
        f"CREATE POLICY users_self_or_tenant_admin ON users "
        f"USING {_ADMIN_OR_SELF_PREDICATE} WITH CHECK {_ADMIN_OR_SELF_PREDICATE}"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('DROP POLICY IF EXISTS users_self_or_tenant_admin ON users')
    op.execute('DROP FUNCTION IF EXISTS _is_requester_tenant_admin(VARCHAR)')
    op.execute('ALTER TABLE users DISABLE ROW LEVEL SECURITY')

    op.add_column('users', sa.Column('hashed_password', sa.String(), nullable=False, server_default=''))
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'created_at')
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name')
