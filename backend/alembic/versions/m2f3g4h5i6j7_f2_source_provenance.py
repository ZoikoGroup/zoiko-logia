"""F2 source provenance, passage, relationship and rights register.

Revision ID: m2f3g4h5i6j7
Revises: l1f2g3h4i5j6
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "m2f3g4h5i6j7"
down_revision: Union[str, Sequence[str], None] = "l1f2g3h4i5j6"
branch_labels = None
depends_on = None


def _create_table_if_missing(existing_tables: set[str], name: str, *elements) -> bool:
    if name in existing_tables:
        return False
    op.create_table(name, *elements)
    existing_tables.add(name)
    return True


def upgrade() -> None:
    bind = op.get_bind()
    if context.is_offline_mode():
        existing_tables: set[str] = set()
        source_columns: set[str] = set()
        # The restored l1 history already owns source_url.
        version_columns = {"source_url"}
        existing_indexes: set[str] = set()
        existing_fks: set[str | None] = set()
    else:
        inspector = sa.inspect(bind)
        existing_tables = set(inspector.get_table_names())
        source_columns = {column["name"] for column in inspector.get_columns("sources")}
        version_columns = {column["name"] for column in inspector.get_columns("source_versions")}
        existing_indexes = {index["name"] for index in inspector.get_indexes("source_versions")}
        existing_fks = {fk.get("name") for fk in inspector.get_foreign_keys("source_versions")}

    if "publisher" not in source_columns:
        op.add_column("sources", sa.Column("publisher", sa.String(), nullable=False, server_default=""))
    if "owner" not in source_columns:
        op.add_column("sources", sa.Column("owner", sa.String(), nullable=False, server_default=""))

    version_additions = {
        "source_url": sa.Column("source_url", sa.String(), nullable=True),
        "content_hash": sa.Column("content_hash", sa.String(), nullable=False, server_default=""),
        "published_at": sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        "retrieved_at": sa.Column(
            "retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        "quality_state": sa.Column(
            "quality_state", sa.String(), nullable=False, server_default="UNREVIEWED"
        ),
        "original_language": sa.Column(
            "original_language", sa.String(), nullable=False, server_default="en"
        ),
        "translation_of_version_id": sa.Column("translation_of_version_id", sa.String(), nullable=True),
        "superseded_by_version_id": sa.Column("superseded_by_version_id", sa.String(), nullable=True),
        "revoked_at": sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        "revocation_reason": sa.Column("revocation_reason", sa.String(), nullable=True),
    }
    for name, column in version_additions.items():
        if name not in version_columns:
            op.add_column("source_versions", column)

    if "uq_source_version_tenant_content_hash" not in existing_indexes:
        op.create_index(
            "uq_source_version_tenant_content_hash",
            "source_versions",
            ["tenant_id", "content_hash"],
            unique=True,
            postgresql_where=sa.text("content_hash <> ''"),
            sqlite_where=sa.text("content_hash <> ''"),
        )
    if "fk_source_versions_translation" not in existing_fks:
        op.create_foreign_key(
            "fk_source_versions_translation", "source_versions", "source_versions",
            ["translation_of_version_id"], ["id"],
        )
    if "fk_source_versions_superseded" not in existing_fks:
        op.create_foreign_key(
            "fk_source_versions_superseded", "source_versions", "source_versions",
            ["superseded_by_version_id"], ["id"],
        )

    rights_created = _create_table_if_missing(
        existing_tables,
        "source_rights",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("source_version_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False, server_default="deny"),
        sa.Column("rights_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reason_code", sa.String(), nullable=False, server_default="RIGHT_NOT_GRANTED"),
        sa.Column("terms_reference", sa.String(), nullable=False, server_default=""),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_version_id"], ["source_versions.id"]),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_version_id", "operation", "rights_version",
            name="uq_source_right_operation_version",
        ),
        sa.CheckConstraint("decision IN ('allow', 'deny')", name="ck_source_right_decision"),
        sa.CheckConstraint("rights_version > 0", name="ck_source_right_version_positive"),
        sa.CheckConstraint(
            "operation IN ('ingestion','indexing','retrieval','model_transmission','display','summary','export','retention','training')",
            name="ck_source_right_operation",
        ),
    )
    if rights_created:
        op.create_index("ix_source_rights_tenant_id", "source_rights", ["tenant_id"])
        op.create_index("ix_source_rights_source_version_id", "source_rights", ["source_version_id"])
        op.create_index("ix_source_rights_operation", "source_rights", ["operation"])

    passages_created = _create_table_if_missing(
        existing_tables,
        "source_passages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("source_version_id", sa.String(), nullable=False),
        sa.Column("locator", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False, server_default="en"),
        sa.Column("is_translation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("derived_from_passage_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_version_id"], ["source_versions.id"]),
        sa.ForeignKeyConstraint(["derived_from_passage_id"], ["source_passages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_version_id", "locator", name="uq_source_passage_locator"),
    )
    if passages_created:
        op.create_index("ix_source_passages_tenant_id", "source_passages", ["tenant_id"])
        op.create_index("ix_source_passages_source_version_id", "source_passages", ["source_version_id"])
        op.create_index("ix_source_passages_content_hash", "source_passages", ["content_hash"])

    relationships_created = _create_table_if_missing(
        existing_tables,
        "source_relationships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("from_version_id", sa.String(), nullable=False),
        sa.Column("to_version_id", sa.String(), nullable=False),
        sa.Column("relationship_type", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["from_version_id"], ["source_versions.id"]),
        sa.ForeignKeyConstraint(["to_version_id"], ["source_versions.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_version_id", "to_version_id", "relationship_type",
            name="uq_source_version_relationship",
        ),
        sa.CheckConstraint(
            "relationship_type IN ('supersedes','clarifies','references','complements','conflicts','historical_only')",
            name="ck_source_relationship_type",
        ),
    )
    if relationships_created:
        op.create_index("ix_source_relationships_tenant_id", "source_relationships", ["tenant_id"])
        op.create_index("ix_source_relationships_from_version_id", "source_relationships", ["from_version_id"])
        op.create_index("ix_source_relationships_to_version_id", "source_relationships", ["to_version_id"])

    usages_created = _create_table_if_missing(
        existing_tables,
        "source_usages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("source_version_id", sa.String(), nullable=False),
        sa.Column("passage_id", sa.String(), nullable=True),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_version_id"], ["source_versions.id"]),
        sa.ForeignKeyConstraint(["passage_id"], ["source_passages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_version_id", "artifact_type", "artifact_id", "operation",
            name="uq_source_usage_artifact",
        ),
    )
    if usages_created:
        op.create_index("ix_source_usages_tenant_id", "source_usages", ["tenant_id"])
        op.create_index("ix_source_usages_source_version_id", "source_usages", ["source_version_id"])
        op.create_index("ix_source_usages_artifact_id", "source_usages", ["artifact_id"])

    if op.get_bind().dialect.name == "postgresql":
        checks = (
            ("source_rights", "ck_source_right_decision", "decision IN ('allow', 'deny')"),
            ("source_rights", "ck_source_right_version_positive", "rights_version > 0"),
            (
                "source_rights", "ck_source_right_operation",
                "operation IN ('ingestion','indexing','retrieval','model_transmission','display','summary','export','retention','training')",
            ),
            (
                "source_relationships", "ck_source_relationship_type",
                "relationship_type IN ('supersedes','clarifies','references','complements','conflicts','historical_only')",
            ),
        )
        for table, constraint, expression in checks:
            op.execute(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{constraint}') THEN "
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ({expression}); "
                "END IF; END $$"
            )
        for table in ("source_rights", "source_passages", "source_relationships", "source_usages"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        for table in ("source_rights", "source_passages"):
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            op.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} USING ("
                "tenant_id = current_setting('app.tenant_id', true) OR EXISTS ("
                "SELECT 1 FROM source_versions sv JOIN sources s ON s.id = sv.source_id "
                f"WHERE sv.id = {table}.source_version_id AND s.is_tenant_private = false)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )
        op.execute("DROP POLICY IF EXISTS source_relationships_tenant_isolation ON source_relationships")
        op.execute(
            "CREATE POLICY source_relationships_tenant_isolation ON source_relationships USING ("
            "tenant_id = current_setting('app.tenant_id', true) OR EXISTS ("
            "SELECT 1 FROM source_versions sv JOIN sources s ON s.id = sv.source_id "
            "WHERE sv.id = source_relationships.from_version_id AND s.is_tenant_private = false)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute("DROP POLICY IF EXISTS source_usages_tenant_isolation ON source_usages")
        op.execute(
            "CREATE POLICY source_usages_tenant_isolation ON source_usages "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_approved_source_content_update()
            RETURNS trigger AS $$
            BEGIN
                IF OLD.status IN ('APPROVED', 'ACTIVE') AND (
                    NEW.source_id IS DISTINCT FROM OLD.source_id OR
                    NEW.version_label IS DISTINCT FROM OLD.version_label OR
                    NEW.content_hash IS DISTINCT FROM OLD.content_hash OR
                    NEW.file_path IS DISTINCT FROM OLD.file_path OR
                    NEW.source_url IS DISTINCT FROM OLD.source_url OR
                    NEW.original_language IS DISTINCT FROM OLD.original_language OR
                    NEW.translation_of_version_id IS DISTINCT FROM OLD.translation_of_version_id
                ) THEN
                    RAISE EXCEPTION 'approved source version content is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("DROP TRIGGER IF EXISTS trg_approved_source_content_immutable ON source_versions")
        op.execute("""
            CREATE TRIGGER trg_approved_source_content_immutable
            BEFORE UPDATE ON source_versions
            FOR EACH ROW EXECUTE FUNCTION prevent_approved_source_content_update()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_approved_passage_change()
            RETURNS trigger AS $$
            DECLARE version_status text;
            BEGIN
                SELECT status INTO version_status FROM source_versions
                WHERE id = OLD.source_version_id;
                IF version_status IN ('APPROVED', 'ACTIVE') THEN
                    RAISE EXCEPTION 'approved source passages are immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("DROP TRIGGER IF EXISTS trg_approved_passage_immutable ON source_passages")
        op.execute("""
            CREATE TRIGGER trg_approved_passage_immutable
            BEFORE UPDATE OR DELETE ON source_passages
            FOR EACH ROW EXECUTE FUNCTION prevent_approved_passage_change()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_source_ledger_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'source rights and usage records are append-only';
            END;
            $$ LANGUAGE plpgsql
        """)
        for table in ("source_rights", "source_usages"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
            op.execute(
                f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION prevent_source_ledger_mutation()"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("source_rights", "source_usages"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
        op.execute("DROP FUNCTION IF EXISTS prevent_source_ledger_mutation()")
        op.execute("DROP TRIGGER IF EXISTS trg_approved_passage_immutable ON source_passages")
        op.execute("DROP FUNCTION IF EXISTS prevent_approved_passage_change()")
        op.execute("DROP TRIGGER IF EXISTS trg_approved_source_content_immutable ON source_versions")
        op.execute("DROP FUNCTION IF EXISTS prevent_approved_source_content_update()")
    op.drop_table("source_usages")
    op.drop_table("source_relationships")
    op.drop_table("source_passages")
    op.drop_table("source_rights")
    op.drop_constraint("fk_source_versions_superseded", "source_versions", type_="foreignkey")
    op.drop_constraint("fk_source_versions_translation", "source_versions", type_="foreignkey")
    op.drop_index("uq_source_version_tenant_content_hash", table_name="source_versions")
    for column in (
        "revocation_reason", "revoked_at", "superseded_by_version_id", "translation_of_version_id",
        "original_language", "quality_state", "retrieved_at", "published_at", "content_hash", "source_url",
    ):
        op.drop_column("source_versions", column)
    op.drop_column("sources", "owner")
    op.drop_column("sources", "publisher")
