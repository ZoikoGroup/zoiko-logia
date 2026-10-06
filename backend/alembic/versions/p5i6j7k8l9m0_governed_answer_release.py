"""Governed answer release: retrieval metadata, feedback and tenant gold cases.

Revision ID: p5i6j7k8l9m0
Revises: o4h5i6j7k8l9
"""
from alembic import op
import sqlalchemy as sa

revision = "p5i6j7k8l9m0"
down_revision = "o4h5i6j7k8l9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    additions = {
        "evaluation_datasets": [sa.Column("tenant_id", sa.String())],
        "source_passages": [sa.Column("heading", sa.String(), nullable=False, server_default=""),
                            sa.Column("procedure", sa.String(), nullable=False, server_default="general")],
        "review_cases": [sa.Column("draft_answer", sa.Text(), nullable=False, server_default=""),
                         sa.Column("source", sa.String(), nullable=False, server_default="escalation")],
        "benchmark_cases": [sa.Column("key_facts", sa.JSON()), sa.Column("tenant_id", sa.String()),
                            sa.Column("category", sa.String(), nullable=False, server_default="reasoning")],
    }
    for table, columns in additions.items():
        existing = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    if "answer_feedback" not in sa.inspect(bind).get_table_names():
        op.create_table("answer_feedback",
            sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False), sa.Column("query_id", sa.String(), nullable=False),
            sa.Column("rating", sa.String(), nullable=False), sa.Column("reasons", sa.JSON(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False, server_default=""), sa.Column("review_case_id", sa.String()),
            sa.Column("created_at", sa.DateTime(timezone=True)),
            sa.CheckConstraint("rating IN ('up', 'down')", name="ck_answer_feedback_rating"))
    if "query_answer_records" not in sa.inspect(bind).get_table_names():
        op.create_table("query_answer_records",
            sa.Column("query_id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False), sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("external_evidence", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True)))
    for table, columns in {
        "review_cases": [("tenant_id", "status", "created_at")],
        "query_answer_records": [("tenant_id",), ("user_id",)],
        "evidence_bundle_manifests": [("tenant_id", "query_id")],
        "benchmark_cases": [("tenant_id",)],
        "evaluation_datasets": [("tenant_id",)],
        "sources": [("tenant_id", "category")],
        "source_versions": [("source_id", "status")],
        "answer_feedback": [("tenant_id",), ("user_id",), ("query_id",)],
    }.items():
        existing = {i["name"] for i in sa.inspect(bind).get_indexes(table)}
        for fields in columns:
            name = f"ix_{table}_{'_'.join(fields)}"
            if name not in existing:
                op.create_index(name, table, list(fields))
    if bind.dialect.name == "postgresql":
        # Extension installation is an explicit database administrator step.
        if not bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar():
            raise RuntimeError("pgvector must be enabled by the database administrator before migration")
        existing = {c["name"] for c in sa.inspect(bind).get_columns("source_passages")}
        if "embedding" not in existing:
            op.execute("ALTER TABLE source_passages ADD COLUMN embedding vector(384)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_source_passages_embedding ON source_passages USING hnsw (embedding vector_cosine_ops)")
        for table in ("review_cases", "answer_feedback", "query_answer_records"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
            op.execute(f"CREATE POLICY tenant_isolation_{table} ON {table} USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true))")


def downgrade():
    # Preserve reviewed answers and evidence. Roll back application code;
    # deleting feedback/gold records is never a release rollback operation.
    pass
