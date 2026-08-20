"""Retention deadlines and physical cleanup for temporary workspace files."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.kriton_workspace.models import Document, GeneratedArtifact
from app.domains.kriton_workspace.storage import delete_object

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _BACKEND_ROOT / "data"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def document_expiry(now: datetime | None = None) -> datetime:
    return (now or utc_now()) + timedelta(days=get_settings().DOCUMENT_RETENTION_DAYS)


def artifact_expiry(now: datetime | None = None) -> datetime:
    return (now or utc_now()) + timedelta(days=get_settings().ARTIFACT_RETENTION_DAYS)


def failed_upload_expiry(now: datetime | None = None) -> datetime:
    return (now or utc_now()) + timedelta(hours=get_settings().FAILED_UPLOAD_RETENTION_HOURS)


async def _remove_stored_file(row: Document | GeneratedArtifact) -> None:
    if row.storage_provider == "supabase" and row.storage_bucket and row.storage_object_path:
        await delete_object(row.storage_bucket, row.storage_object_path)
        return
    path = (_BACKEND_ROOT / row.storage_path).resolve()
    if not path.is_relative_to(_DATA_ROOT.resolve()):
        raise ValueError("Stored file path escapes the configured data root")
    path.unlink(missing_ok=True)


async def cleanup_expired_workspace(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Delete expired objects and their rows in bounded, retry-safe batches."""
    deadline = now or utc_now()
    limit = max(1, get_settings().RETENTION_CLEANUP_BATCH_SIZE)
    documents = list((await db.execute(
        select(Document).where(Document.expires_at.is_not(None), Document.expires_at <= deadline)
        .order_by(Document.expires_at).limit(limit)
    )).scalars().all())
    artifacts = list((await db.execute(
        select(GeneratedArtifact).where(
            GeneratedArtifact.expires_at.is_not(None), GeneratedArtifact.expires_at <= deadline
        ).order_by(GeneratedArtifact.expires_at).limit(limit)
    )).scalars().all())

    counts = {"documents": 0, "artifacts": 0}
    for document in documents:
        await _remove_stored_file(document)
        await db.execute(delete(Document).where(Document.id == document.id))
        counts["documents"] += 1
    for artifact in artifacts:
        await _remove_stored_file(artifact)
        await db.execute(delete(GeneratedArtifact).where(GeneratedArtifact.id == artifact.id))
        counts["artifacts"] += 1
    await db.commit()
    return counts
