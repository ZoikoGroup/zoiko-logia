"""Administration console: teams, access reviews, tenant policy and its
staged change requests, and release candidates. All tenant isolated by RLS.

Revision ID: t9m0n1o2p3q4
Revises: s8l9m0n1o2p3
"""
from alembic import op
import sqlalchemy as sa

revision = "t9m0n1o2p3q4"
down_revision = "s8l9m0n1o2p3"
branch_labels = None
depends_on = None

_RLS_TABLES = ("teams", "team_members", "access_reviews", "tenant_policies", "setting_change_requests",
               "release_candidates")


def _ts(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False)


def _user(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.String(), sa.ForeignKey("users.id"), nullable=nullable)


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "teams" not in existing:
        op.create_table(
            "teams",
            sa.Column("id", sa.String(), primary_key=True), _tenant(),
            sa.Column("name", sa.String(), nullable=False), sa.Column("description", sa.String(), nullable=False),
            _user("owner_user_id"), _user("created_by", nullable=False), _ts("created_at", nullable=False),
            sa.UniqueConstraint("tenant_id", "name", name="uq_team_name"),
        )
        op.create_index("ix_teams_tenant_id", "teams", ["tenant_id"])

    if "team_members" not in existing:
        op.create_table(
            "team_members",
            sa.Column("id", sa.String(), primary_key=True), _tenant(),
            sa.Column("team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=False),
            _user("user_id", nullable=False), _user("added_by", nullable=False), _ts("added_at", nullable=False),
            sa.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
        )
        op.create_index("ix_team_members_tenant_id", "team_members", ["tenant_id"])
        op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
        op.create_index("ix_team_members_user_id", "team_members", ["user_id"])

    if "access_reviews" not in existing:
        op.create_table(
            "access_reviews",
            sa.Column("id", sa.String(), primary_key=True), _tenant(), _user("user_id", nullable=False),
            sa.Column("role", sa.String(), nullable=False), sa.Column("decision", sa.String(), nullable=False),
            sa.Column("note", sa.Text(), nullable=False), _user("reviewer_id", nullable=False),
            _ts("reviewed_at", nullable=False),
        )
        op.create_index("ix_access_reviews_tenant_id", "access_reviews", ["tenant_id"])
        op.create_index("ix_access_reviews_user_id", "access_reviews", ["user_id"])

    if "tenant_policies" not in existing:
        op.create_table(
            "tenant_policies",
            sa.Column("id", sa.String(), primary_key=True), _tenant(),
            sa.Column("key", sa.String(), nullable=False), sa.Column("value", sa.JSON(), nullable=False),
            sa.Column("change_request_id", sa.String()), _user("updated_by", nullable=False),
            _ts("updated_at", nullable=False),
            sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_policy_key"),
        )
        op.create_index("ix_tenant_policies_tenant_id", "tenant_policies", ["tenant_id"])

    if "setting_change_requests" not in existing:
        op.create_table(
            "setting_change_requests",
            sa.Column("id", sa.String(), primary_key=True), _tenant(),
            sa.Column("ref", sa.String(), nullable=False), sa.Column("key", sa.String(), nullable=False),
            sa.Column("current_value", sa.JSON(), nullable=False), sa.Column("proposed_value", sa.JSON(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            _user("requested_by", nullable=False), _ts("requested_at", nullable=False),
            _user("decided_by"), _ts("decided_at"), sa.Column("decision_note", sa.Text(), nullable=False),
            sa.UniqueConstraint("tenant_id", "ref", name="uq_setting_change_ref"),
        )
        op.create_index("ix_setting_change_requests_tenant_id", "setting_change_requests", ["tenant_id"])

    if "release_candidates" not in existing:
        op.create_table(
            "release_candidates",
            sa.Column("id", sa.String(), primary_key=True), _tenant(),
            sa.Column("ref", sa.String(), nullable=False), sa.Column("name", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=False), sa.Column("component", sa.String(), nullable=False),
            sa.Column("change_ref", sa.String(), nullable=False), sa.Column("description", sa.Text(), nullable=False),
            sa.Column("risk", sa.String(), nullable=False), _user("owner_user_id"),
            sa.Column("status", sa.String(), nullable=False), sa.Column("gates", sa.JSON(), nullable=False),
            _user("created_by", nullable=False), _ts("created_at", nullable=False),
            _user("approved_by"), _ts("approved_at"), _ts("deployed_at"), _ts("rolled_back_at"),
            sa.Column("history", sa.JSON(), nullable=False),
            sa.UniqueConstraint("tenant_id", "ref", name="uq_release_candidate_ref"),
        )
        op.create_index("ix_release_candidates_tenant_id", "release_candidates", ["tenant_id"])

    if bind.dialect.name == "postgresql":
        for table in _RLS_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
            op.execute(
                f"CREATE POLICY tenant_isolation_{table} ON {table} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )


def downgrade():
    for table in ("release_candidates", "setting_change_requests", "tenant_policies", "access_reviews",
                  "team_members", "teams"):
        op.drop_table(table)
