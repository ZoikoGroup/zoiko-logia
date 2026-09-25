"""Agentic document ingestion and evidence review metadata.

Revision ID: p5i6j7k8l9m0
Revises: o4h5i6j7k8l9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p5i6j7k8l9m0"
down_revision: Union[str, Sequence[str], None] = "o4h5i6j7k8l9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column in (
        ("ingestion_job_id", sa.Column("ingestion_job_id", sa.String(), nullable=True)),
        ("parser_version", sa.Column("parser_version", sa.String(), nullable=False, server_default="f6.1")),
        ("extraction_method", sa.Column("extraction_method", sa.String(), nullable=False, server_default="pending")),
        ("coverage_ratio", sa.Column("coverage_ratio", sa.Float(), nullable=False, server_default="0")),
        ("extraction_confidence", sa.Column("extraction_confidence", sa.Float(), nullable=False, server_default="0")),
        ("processing_plan", sa.Column("processing_plan", sa.JSON(), nullable=False, server_default="{}")),
        ("review_reason", sa.Column("review_reason", sa.Text(), nullable=True)),
        ("processed_at", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True)),
    ):
        op.add_column("user_documents", column)
    op.execute("UPDATE user_documents SET ingestion_job_id = id WHERE ingestion_job_id IS NULL")
    op.alter_column("user_documents", "ingestion_job_id", nullable=False)

    for column in (
        sa.Column("location", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("extraction_confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("corrected_content", sa.Text(), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("corrected_by", sa.String(), nullable=True),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("document_chunks", column)


def downgrade() -> None:
    for name in ("corrected_at", "corrected_by", "correction_reason", "corrected_content",
                 "extraction_confidence", "location"):
        op.drop_column("document_chunks", name)
    for name in ("processed_at", "review_reason", "processing_plan", "extraction_confidence",
                 "coverage_ratio", "extraction_method", "parser_version", "ingestion_job_id"):
        op.drop_column("user_documents", name)
