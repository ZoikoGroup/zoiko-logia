from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "kriton",
    broker=settings.CELERY_BROKER_URL or "redis://localhost:6379/0",
    backend=settings.CELERY_RESULT_BACKEND or settings.CELERY_BROKER_URL or "redis://localhost:6379/1",
    include=["app.jobs.document_ingestion"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    timezone="UTC",
)
