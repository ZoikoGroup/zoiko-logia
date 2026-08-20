"""
Uploaded-document store for Ask Kriton™ attachments.

Deliberately kept OUT of the Massarius™ source library (app/domains/
source_library). A file a user uploads is not a governed source: it has no
publisher, no version label, no licence state and no jurisdiction scope, and
nobody has approved it for retrieval. Registering it in `sources` would let a
client's own spreadsheet inherit the authority of an ACTIVE, approved standard
and appear in a SourceBundle as though the governance workflow had cleared it.

So these are separate tables, and retrieval reaches them through a separate
channel (see service.py and the document context block in
orchestration/websearch.py) that is labelled to the model, to the reader and
in the audit ledger as the user's OWN material — never as authority.

Both tables are strictly tenant-private: unlike `sources`, there is no shared
/ non-private case, so the RLS policy in app/main.py is plain tenant equality.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Lifecycle of a single upload. "ready" is the only state retrieval will read
# from — a document that failed extraction stays visible to its owner with the
# reason attached rather than disappearing, so the user learns that their
# scanned PDF produced no text instead of silently getting ungrounded answers.
STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_FAILED = "failed"


class UserDocument(Base):
    __tablename__ = "user_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    filename: Mapped[str] = mapped_column(String, nullable=False)
    extension: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # SHA-256 of the raw bytes. Recorded so an audited answer can later be
    # reproduced against the exact file version it was grounded in — a
    # re-upload under the same filename produces a different hash.
    content_sha256: Mapped[str] = mapped_column(String, nullable=False)

    # Path inside the object-storage bucket, empty when storage is not
    # configured (the pipeline still works — see storage.py).
    storage_path: Mapped[str] = mapped_column(String, nullable=False, default="")

    status: Mapped[str] = mapped_column(String, nullable=False, default=STATUS_PENDING)
    # Populated only when status is "failed"; surfaced to the uploader.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_user_documents_owner", "tenant_id", "user_id"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("user_documents.id"), nullable=False)
    # Denormalised from the parent document so every retrieval query can filter
    # on tenant WITHOUT a join, which is what lets the RLS policy on this table
    # stand on its own rather than depending on the parent row being visible.
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Ordinal within the document, 0-based — used to present retrieved chunks
    # in document order rather than in score order.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Human-readable origin of the chunk, e.g. "page 4" or "sheet 'Q3' rows
    # 120-148". This is what makes a citation point INTO the file instead of at
    # it, so the reader can verify the claim.
    locator: Mapped[str] = mapped_column(String, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_document_chunks_document", "document_id", "ordinal"),
        Index("ix_document_chunks_owner", "tenant_id", "user_id"),
    )
