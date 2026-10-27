"""Financial statements: publication artifacts and issues (Document 06, ZL-FSR-ENG-006).

fs_publication_artifacts keeps each rendered file (and quarantined external
edits) with its semantic model, byte hash and validation report;
fs_publication_issues keeps issued publications and filing attempts.
Tenant isolated by RLS. Additive only.

Revision ID: f1y2z3a4b5c6
Revises: e0x1y2z3a4b5
"""
from alembic import op
import sqlalchemy as sa

revision = "f1y2z3a4b5c6"
down_revision = "e0x1y2z3a4b5"
branch_labels = None
depends_on = None

_TABLES = ("fs_publication_artifacts", "fs_publication_issues")


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "fs_publication_artifacts" not in existing:
        op.create_table(
            "fs_publication_artifacts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("package_id", sa.String(), sa.ForeignKey("fs_report_packages.id"), nullable=False),
            sa.Column("package_version", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False, server_default="RENDER"),
            sa.Column("audience", sa.String(), nullable=False),
            sa.Column("channel", sa.String(), nullable=False),
            sa.Column("scale", sa.String(), nullable=False, server_default="units"),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("model", sa.JSON(), nullable=False),
            sa.Column("model_hash", sa.String(), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("media_type", sa.String(), nullable=False),
            sa.Column("sha256", sa.String(), nullable=False),
            sa.Column("content", sa.LargeBinary(), nullable=False),
            sa.Column("validation", sa.JSON(), nullable=False),
            sa.Column("source_artifact_id", sa.String(), nullable=True),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_fs_publication_artifacts_tenant_id", "fs_publication_artifacts", ["tenant_id"])
        op.create_index("ix_fs_publication_artifacts_package_id", "fs_publication_artifacts", ["package_id"])
        op.create_index("ix_fs_publication_artifacts_idempotency_key", "fs_publication_artifacts", ["idempotency_key"])
    if "fs_publication_issues" not in existing:
        op.create_table(
            "fs_publication_issues",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("package_id", sa.String(), sa.ForeignKey("fs_report_packages.id"), nullable=False),
            sa.Column("package_version", sa.Integer(), nullable=False),
            sa.Column("audience", sa.String(), nullable=False),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("release_id", sa.String(), nullable=False),
            sa.Column("artifacts", sa.JSON(), nullable=False),
            sa.Column("filing", sa.JSON(), nullable=False),
            sa.Column("issued_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("auth_aal", sa.String(), nullable=False, server_default="aal1"),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("superseded_by", sa.String(), nullable=True),
        )
        op.create_index("ix_fs_publication_issues_tenant_id", "fs_publication_issues", ["tenant_id"])
        op.create_index("ix_fs_publication_issues_package_id", "fs_publication_issues", ["package_id"])
    if bind.dialect.name == "postgresql":
        for table in _TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
            op.execute(
                f"CREATE POLICY tenant_isolation_{table} ON {table} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )


def downgrade():
    for table in reversed(_TABLES):
        op.drop_table(table)
