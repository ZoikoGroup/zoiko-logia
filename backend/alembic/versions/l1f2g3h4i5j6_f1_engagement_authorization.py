"""F1 engagement membership and operation grants

Revision ID: l1f2g3h4i5j6
Revises: k0e1f2g3h4i5
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "l1f2g3h4i5j6"
down_revision: Union[str, Sequence[str], None] = "k0e1f2g3h4i5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engagements",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("rights_version", sa.String(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_engagements_tenant_id", "engagements", ["tenant_id"])
    op.create_table(
        "engagement_memberships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("engagement_role", sa.String(), nullable=False, server_default="member"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["engagement_id"], ["engagements.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("engagement_id", "user_id", name="uq_engagement_member"),
    )
    op.create_index("ix_engagement_memberships_tenant_id", "engagement_memberships", ["tenant_id"])
    op.create_index("ix_engagement_memberships_engagement_id", "engagement_memberships", ["engagement_id"])
    op.create_index("ix_engagement_memberships_user_id", "engagement_memberships", ["user_id"])
    op.create_table(
        "engagement_grants",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("membership_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("effect", sa.String(), nullable=False, server_default="allow"),
        sa.Column("version", sa.String(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["engagement_memberships.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", "operation", name="uq_membership_operation"),
    )
    op.create_index("ix_engagement_grants_tenant_id", "engagement_grants", ["tenant_id"])
    op.create_index("ix_engagement_grants_membership_id", "engagement_grants", ["membership_id"])
    op.add_column("user_documents", sa.Column("engagement_id", sa.String(), nullable=True))
    op.create_foreign_key("fk_user_documents_engagement", "user_documents", "engagements", ["engagement_id"], ["id"])
    op.create_index("ix_user_documents_engagement_id", "user_documents", ["engagement_id"])
    op.add_column("document_chunks", sa.Column("engagement_id", sa.String(), nullable=True))
    op.create_foreign_key("fk_document_chunks_engagement", "document_chunks", "engagements", ["engagement_id"], ["id"])
    op.create_index("ix_document_chunks_engagement_id", "document_chunks", ["engagement_id"])

    if op.get_bind().dialect.name == "postgresql":
        for table in ("engagements", "engagement_memberships", "engagement_grants"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )
        document_policy = (
            "(current_setting('app.user_id', true) IS NOT NULL "
            "AND current_setting('app.user_id', true) != '' AND ("
            "(engagement_id IS NULL AND user_id = current_setting('app.user_id', true)) OR "
            "engagement_id IN (SELECT engagement_id FROM engagement_memberships "
            "WHERE user_id = current_setting('app.user_id', true) "
            "AND status = 'active' AND revoked_at IS NULL)))"
        )
        for table in ("user_documents", "document_chunks"):
            op.execute(f"DROP POLICY IF EXISTS owner_isolation_{table} ON {table}")
            op.execute(
                f"CREATE POLICY owner_isolation_{table} ON {table} "
                f"USING {document_policy} WITH CHECK {document_policy}"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        personal_policy = (
            "(current_setting('app.user_id', true) IS NOT NULL "
            "AND current_setting('app.user_id', true) != '' "
            "AND user_id = current_setting('app.user_id', true))"
        )
        for table in ("user_documents", "document_chunks"):
            op.execute(f"DROP POLICY IF EXISTS owner_isolation_{table} ON {table}")
            op.execute(
                f"CREATE POLICY owner_isolation_{table} ON {table} "
                f"USING {personal_policy} WITH CHECK {personal_policy}"
            )
    op.drop_index("ix_document_chunks_engagement_id", table_name="document_chunks")
    op.drop_constraint("fk_document_chunks_engagement", "document_chunks", type_="foreignkey")
    op.drop_column("document_chunks", "engagement_id")
    op.drop_index("ix_user_documents_engagement_id", table_name="user_documents")
    op.drop_constraint("fk_user_documents_engagement", "user_documents", type_="foreignkey")
    op.drop_column("user_documents", "engagement_id")
    op.drop_table("engagement_grants")
    op.drop_table("engagement_memberships")
    op.drop_table("engagements")
