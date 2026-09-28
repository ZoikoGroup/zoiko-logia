"""Durable background document extraction jobs."""
import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.domains.kriton_workspace.documents import process_document
from app.domains.kriton_workspace.models import Document
from app.domains.kriton_workspace.retention import cleanup_expired_workspace
from app.jobs.celery_app import celery_app


async def _process(document_id: str) -> None:
    async with AsyncSessionLocal() as db:
        document = (await db.execute(
            select(Document).where(Document.id == document_id)
        )).scalar_one_or_none()
        if document is not None:
            await process_document(db, document)


@celery_app.task(
    name="kriton.ingest_document",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def ingest_document_job(document_id: str) -> None:
    asyncio.run(_process(document_id))


def enqueue_document_ingestion(document_id: str) -> None:
    ingest_document_job.apply_async(args=[document_id], queue="documents")


async def _cleanup_expired() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        return await cleanup_expired_workspace(db)


@celery_app.task(name="kriton.cleanup_expired_workspace")
def cleanup_expired_workspace_job() -> dict[str, int]:
    return asyncio.run(_cleanup_expired())
