"""Hybrid retrieval planning and immutable evidence bundle manifests.

Revision ID: n3g4h5i6j7k8
Revises: m2f3g4h5i6j7
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

revision: str = "n3g4h5i6j7k8"
down_revision: Union[str, Sequence[str], None] = "m2f3g4h5i6j7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set() if context.is_offline_mode() else set(sa.inspect(op.get_bind()).get_table_names())
    manifests_created = "evidence_bundle_manifests" not in existing
    if manifests_created:
        op.create_table(
        "evidence_bundle_manifests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("query_id", sa.String(), nullable=False),
        sa.Column("retrieval_plan", sa.JSON(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("index_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_evidence_bundle_manifests_tenant_id", "evidence_bundle_manifests", ["tenant_id"])
        op.create_index("ix_evidence_bundle_manifests_query_id", "evidence_bundle_manifests", ["query_id"])
    entries_created = "evidence_bundle_entries" not in existing
    if entries_created:
        op.create_table(
        "evidence_bundle_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("bundle_id", sa.String(), sa.ForeignKey("evidence_bundle_manifests.id"), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("source_version_id", sa.String(), nullable=False),
        sa.Column("passage_id", sa.String(), nullable=False, server_default=""),
        sa.Column("disposition", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("retrieval_method", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False, server_default=""),
        sa.UniqueConstraint(
            "bundle_id", "source_version_id", "passage_id", "disposition",
            name="uq_evidence_bundle_entry",
        ),
        sa.CheckConstraint(
            "disposition IN ('selected','excluded')",
            name="ck_evidence_bundle_entry_disposition",
        ),
        )
        op.create_index("ix_evidence_bundle_entries_bundle_id", "evidence_bundle_entries", ["bundle_id"])
        op.create_index("ix_evidence_bundle_entries_tenant_id", "evidence_bundle_entries", ["tenant_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname = 'ck_evidence_bundle_entry_disposition') THEN "
            "ALTER TABLE evidence_bundle_entries ADD CONSTRAINT "
            "ck_evidence_bundle_entry_disposition CHECK "
            "(disposition IN ('selected','excluded')); END IF; END $$"
        )
        for table in ("evidence_bundle_manifests", "evidence_bundle_entries"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            op.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_evidence_bundle_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'evidence bundle manifests and entries are append-only';
            END;
            $$ LANGUAGE plpgsql
        """)
        for table in ("evidence_bundle_manifests", "evidence_bundle_entries"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
            op.execute(
                f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION prevent_evidence_bundle_mutation()"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("evidence_bundle_entries", "evidence_bundle_manifests"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
        op.execute("DROP FUNCTION IF EXISTS prevent_evidence_bundle_mutation()")
    op.drop_table("evidence_bundle_entries")
    op.drop_table("evidence_bundle_manifests")
