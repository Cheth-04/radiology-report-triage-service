"""Retrieve durable job state from PostgreSQL, never the Celery result backend."""
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.report import Report
from app.models.report_result import ReportResult
from app.models.user import User
from app.schemas.job import JobRead, JobResult

router = APIRouter(prefix="/jobs", tags=["Jobs"])
logger = logging.getLogger(__name__)


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        report = db.get(Report, job_id)
        # Use 404 for both absent and unauthorized jobs to avoid ID enumeration.
        if report is None or (current_user.role != "admin" and report.owner_id != current_user.id):
            raise HTTPException(status_code=404, detail="Job not found")

        result = None
        if report.status == "done":
            record = db.scalar(select(ReportResult).where(ReportResult.report_id == job_id))
            if record is None:
                # A 'done' report without persisted extraction is inconsistent.
                logger.error("Completed job missing extraction job_id=%s", job_id)
                raise HTTPException(status_code=503, detail="Job result temporarily unavailable")
            result = JobResult.model_validate(record)

        return JobRead(
            job_id=report.id,
            status=report.status,
            result=result,
            error=report.error_message if report.status == "failed" else None,
            created_at=report.created_at,
            updated_at=report.updated_at,
        )
    except SQLAlchemyError as exc:
        logger.exception("Unable to retrieve job_id=%s", job_id)
        raise HTTPException(status_code=503, detail="Job status temporarily unavailable") from exc
