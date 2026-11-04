"""Independent source review and explicit reporting periods; no data correction.

Phase 1 (C2-C4, 25 Oct 2026). First written as b7u8v9w0x1y2 revising
a6t7u8v9w0x1, the id and parent main's financial_statements_intake already
had; renamed and placed after main's head on 4 Nov 2026, since two
migrations cannot share an id.

Revision ID: j5e6f7a8b9c0
Revises: h3b4c5d6e7f8
"""
from alembic import op
import sqlalchemy as sa
revision = "j5e6f7a8b9c0"
down_revision = "h3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("source_versions", "source_passages"):
        op.add_column(table, sa.Column("reporting_period_start", sa.Date(), nullable=True))
        op.add_column(table, sa.Column("reporting_period_end", sa.Date(), nullable=True))
    op.add_column("source_versions", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("source_reviewer_identities",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("auth_subject", sa.String(), nullable=False, unique=True),
        sa.Column("identity_kind", sa.String(), nullable=False),
        sa.Column("verified_by", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("source_approvals",
        sa.Column("version_id", sa.String(), sa.ForeignKey("source_versions.id"), primary_key=True),
        sa.Column("approver_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitter_person_id", sa.String(), nullable=False),
        sa.Column("reviewer_person_id", sa.String(), nullable=False),
        sa.Column("auth_subject", sa.String(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    # Audit events are deliberately never deleted or rewritten. Export review
    # attestations/receipts and new period metadata before schema downgrade.
    op.drop_table("source_approvals")
    op.drop_table("source_reviewer_identities")
    op.drop_column("source_versions", "superseded_at")
    for table in ("source_passages", "source_versions"):
        op.drop_column(table, "reporting_period_end")
        op.drop_column(table, "reporting_period_start")
