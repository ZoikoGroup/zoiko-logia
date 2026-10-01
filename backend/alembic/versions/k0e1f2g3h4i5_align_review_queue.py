"""align human review queue with canonical review_cases

Revision ID: k0e1f2g3h4i5
Revises: j9d0e1f2g3h4
"""
from alembic import op
import sqlalchemy as sa

revision = "k0e1f2g3h4i5"
down_revision = "j9d0e1f2g3h4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("review_cases")}
    columns = {
        "query_text": sa.Column("query_text", sa.Text(), nullable=True),
        "reviewer_decision": sa.Column("reviewer_decision", sa.String(), nullable=True),
        "reviewer_id": sa.Column("reviewer_id", sa.String(), nullable=True),
        "review_note": sa.Column("review_note", sa.Text(), nullable=True),
        "resolved_at": sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    }
    for name, column in columns.items():
        if name not in existing:
            op.add_column("review_cases", column)
    op.execute("UPDATE review_cases SET query_text = '' WHERE query_text IS NULL")
    op.execute("UPDATE review_cases SET review_note = '' WHERE review_note IS NULL")
    if bind.dialect.name != "sqlite":
        op.alter_column("review_cases", "query_text", nullable=False)
        op.alter_column("review_cases", "review_note", nullable=False)


def downgrade():
    for name in ("resolved_at", "review_note", "reviewer_id", "reviewer_decision", "query_text"):
        op.drop_column("review_cases", name)
