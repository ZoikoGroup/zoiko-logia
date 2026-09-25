"""Celery entry point. Messages contain identifiers only, never file bytes."""
from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.jobs.celery_app import celery_app
from app.domains.documents.service import process_staged_document
from app.domains.audit_ledger.event_envelope import record_event_async

settings = get_settings()


@celery_app.task(
    bind=True,
    name="documents.process",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=settings.DOCUMENT_TASK_MAX_RETRIES,
    soft_time_limit=settings.DOCUMENT_TASK_TIMEOUT_SECONDS,
)
def process_document_task(self, document_id: str, tenant_id: str, user_id: str) -> dict:
    async def run() -> dict:
        async with AsyncSessionLocal() as db:
            result = await process_staged_document(
                db, document_id=document_id, tenant_id=tenant_id, user_id=user_id
            )
            await record_event_async(
                db, tenant_id=tenant_id,
                event_name=("kriton_workspace.attachment_indexed"
                            if result.status == "ready"
                            else "kriton_workspace.attachment_review_required"
                            if result.status == "needs_review"
                            else "kriton_workspace.attachment_rejected"),
                emitting_service="document_worker", actor_id=user_id,
                subject_type="attachment", subject_id=document_id,
                payload={"status": result.status, "chunk_count": result.chunk_count,
                         "extraction_method": result.extraction_method,
                         "coverage_ratio": result.coverage_ratio,
                         "confidence": result.extraction_confidence},
            )
            return result.__dict__
    return asyncio.run(run())
