"""WF-01 release governance (ZL-WF-GAP-01): document authority (A1), the
as-built ledger (A2), the runtime QA ledger (A3), gap ownership decisions and
release verdicts. Platform-scoped metadata (decision D3).

Evidence, decisions and observations are append-only: on PostgreSQL every
UPDATE and DELETE is refused by trigger. Authority documents and aliases may
change only through the service's revision-checked, ratified path, and are
never deleted.

Revision ID: g2a3b4c5d6e7
Revises: h3b4c5d6e7f8
"""
from typing import Sequence, Union

from alembic import op

revision: str = "g2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "h3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("authority_documents", "authority_aliases", "authority_change_requests", "gap_ownership_decisions",
          "release_verdicts", "asbuilt_manifests", "asbuilt_mappings", "asbuilt_verifications",
          "qa_cases", "qa_baseline", "qa_runs", "qa_observations", "qa_adjudications")
APPEND_ONLY = ("authority_change_requests", "gap_ownership_decisions", "release_verdicts", "asbuilt_manifests",
               "asbuilt_mappings", "asbuilt_verifications", "qa_cases", "qa_baseline", "qa_runs",
               "qa_observations", "qa_adjudications")
NO_DELETE = ("authority_documents", "authority_aliases")


def upgrade() -> None:
    from app.db.base import Base
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)
    if bind.dialect.name != "postgresql":
        return
    op.execute("""
        CREATE OR REPLACE FUNCTION wf01_refuse_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only: % refused', TG_TABLE_NAME, TG_OP;
        END;
        $$ LANGUAGE plpgsql
    """)
    for name in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{name}_append_only ON {name}")
        op.execute(f"CREATE TRIGGER trg_{name}_append_only BEFORE UPDATE OR DELETE ON {name} "
                   f"FOR EACH ROW EXECUTE FUNCTION wf01_refuse_mutation()")
    for name in NO_DELETE:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{name}_no_delete ON {name}")
        op.execute(f"CREATE TRIGGER trg_{name}_no_delete BEFORE DELETE ON {name} "
                   f"FOR EACH ROW EXECUTE FUNCTION wf01_refuse_mutation()")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name in APPEND_ONLY:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{name}_append_only ON {name}")
        for name in NO_DELETE:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{name}_no_delete ON {name}")
        op.execute("DROP FUNCTION IF EXISTS wf01_refuse_mutation()")
    for name in reversed(TABLES):
        op.drop_table(name)
