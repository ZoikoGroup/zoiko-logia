"""WF-01 A3: the fixture provisioning ledger (qa_fixture_provisions), append-only
like the rest of the QA ledger (trigger function from g2a3b4c5d6e7).

Revision ID: i4c5d6e7f8a9
Revises: g2a3b4c5d6e7
"""
from typing import Sequence, Union

from alembic import op

revision: str = "i4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "g2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import app.domains.evaluation.qa_models  # noqa: F401  (registers the table)
    from app.db.base import Base
    bind = op.get_bind()
    Base.metadata.tables["qa_fixture_provisions"].create(bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        op.execute("CREATE TRIGGER trg_qa_fixture_provisions_append_only BEFORE UPDATE OR DELETE ON qa_fixture_provisions "
                   "FOR EACH ROW EXECUTE FUNCTION wf01_refuse_mutation()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_qa_fixture_provisions_append_only ON qa_fixture_provisions")
    op.drop_table("qa_fixture_provisions")
