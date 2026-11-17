from celery import Celery
from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "radiology_triage",
    broker=settings.redis_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)
