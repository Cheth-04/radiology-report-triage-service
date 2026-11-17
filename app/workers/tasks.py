"""Celery processing pipeline; persistent job status lives in PostgreSQL."""
import logging
import uuid

from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.models.report import Report
from app.models.report_result import ReportResult
from app.services.extraction import InvalidLLMResponse, TemporaryLLMError, extract_report
from app.services.alerts import emit_critical_alert
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.ping")
def ping():
    return {"worker": "ok"}


def mark_failed(report_id: uuid.UUID, message: str) -> None:
    with SessionLocal() as db:
        report = db.get(Report, report_id)
        if report is not None and report.status != "done":
            report.status = "failed"
            report.error_message = message[:1000]
            db.commit()


@celery_app.task(bind=True, name="app.workers.tasks.process_report", max_retries=3)
def process_report(self, report_id: str):
    """Transition queued -> processing -> done (or failed after bounded retries).

    Replaying a completed task is harmless. Never return raw report text or LLM
    content in Celery results/logging. The database commit is the source of truth.
    """
    try:
        parsed_id = uuid.UUID(report_id)
    except (ValueError, AttributeError):
        logger.error("Rejecting invalid report id from queue")
        return {"status": "invalid_id"}

    try:
        with SessionLocal() as db:
            report = db.get(Report, parsed_id)
            if report is None:
                return {"job_id": report_id, "status": "not_found"}
            if report.status == "done":
                return {"job_id": report_id, "status": "done"}
            if report.status == "failed":
                return {"job_id": report_id, "status": "failed"}
            report.status = "processing"
            report.error_message = None
            text = report.report_text
            db.commit()

        result = extract_report(text)

        with SessionLocal() as db:
            report = db.get(Report, parsed_id)
            if report is None:
                return {"job_id": report_id, "status": "not_found"}
            if report.status == "done":
                return {"job_id": report_id, "status": "done"}
            # Persist result + status in one transaction.
            record = db.query(ReportResult).filter(ReportResult.report_id == parsed_id).one_or_none()
            if record is None:
                record = ReportResult(report_id=parsed_id)
                db.add(record)
            for key, value in result.model_dump().items():
                setattr(record, key, value)
            report.status = "done"
            report.error_message = None
            db.commit()

        if result.is_critical:
            emit_critical_alert(parsed_id, result.critical_reason)
        logger.info("Report processing completed job_id=%s", parsed_id)
        return {"job_id": report_id, "status": "done"}

    except TemporaryLLMError as exc:
        if self.request.retries < self.max_retries:
            delay = min(2 ** (self.request.retries + 1), 30)
            logger.warning("Transient LLM failure job_id=%s attempt=%s; retry in %ss", parsed_id, self.request.retries + 1, delay)
            raise self.retry(exc=exc, countdown=delay)
        mark_failed(parsed_id, "LLM unavailable after retries")
        logger.error("LLM retries exhausted job_id=%s", parsed_id)
        return {"job_id": report_id, "status": "failed"}
    except InvalidLLMResponse:
        mark_failed(parsed_id, "Invalid or unsupported LLM extraction")
        logger.error("Invalid extraction job_id=%s", parsed_id)
        return {"job_id": report_id, "status": "failed"}
    except SQLAlchemyError:
        logger.exception("Database failure processing job_id=%s", parsed_id)
        # Fail the Celery task rather than falsely recording success. An operator
        # can recover an interrupted processing job by requeueing its id.
        raise
