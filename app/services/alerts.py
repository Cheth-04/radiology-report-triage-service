"""Demo-only critical alert transport.

The assignment permits a log alert. No raw report text is written to logs.
In production, use a durable, authenticated outbox/webhook with delivery tracking.
"""
import logging
import uuid

logger = logging.getLogger("radiology_triage.alerts")


def emit_critical_alert(job_id: uuid.UUID, reason: str) -> None:
    # The reason is required by our extraction schema and stored in Postgres.
    # Log only job ID and an alert type to avoid exposing report content in logs.
    logger.warning("CRITICAL TRIAGE ALERT job_id=%s type=critical_radiology_finding", job_id)
