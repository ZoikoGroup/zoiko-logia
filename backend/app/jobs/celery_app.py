from celery import Celery

from app.core.config import get_settings


settings = get_settings()
celery_app = Celery(
    "kriton",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND or None,
    include=["app.jobs.ingestion_jobs"],
)
celery_app.conf.task_routes = {
    "kriton.ingest_document": {"queue": "documents"},
    "kriton.cleanup_expired_workspace": {"queue": "maintenance"},
}
celery_app.conf.beat_schedule = {
    "cleanup-expired-workspace-hourly": {
        "task": "kriton.cleanup_expired_workspace",
        "schedule": 3600.0,
    },
}
celery_app.conf.task_acks_late = True
celery_app.conf.worker_prefetch_multiplier = 1
