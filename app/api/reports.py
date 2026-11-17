import logging
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.report import Report
from app.models.user import User
from app.schemas.report import ReportAccepted, ReportCreate, ReportRead
from app.workers.tasks import process_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["Reports"])

@router.post("", response_model=ReportAccepted, status_code=status.HTTP_202_ACCEPTED)
def submit_report(
    payload: ReportCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if current_user.role != "radiologist":
        raise HTTPException(status_code=403, detail="Only radiologists can upload reports")

    report = Report(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        report_text=payload.report_text,
        status="queued",
    )
    try:
        db.add(report)
        db.commit()  # Save a durable job before publishing it to the queue.
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Could not persist report")
        raise HTTPException(status_code=503, detail="Could not save report") from exc

    try:
        # Only pass an ID to Celery; do not put medical text into Redis messages.
        process_report.apply_async(args=[str(report.id)], task_id=str(report.id))
    except Exception as exc:
        # This covers ordinary broker send failures, not every possible network ambiguity.
        logger.exception("Failed to enqueue report %s", report.id)
        try:
            report.status = "failed"
            report.error_message = "Could not enqueue background processing"
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            logger.exception("Could not persist queue failure for report %s", report.id)
        raise HTTPException(status_code=503, detail="Could not queue report processing") from exc

    return ReportAccepted(job_id=report.id, status="queued")

@router.get("", response_model=list[ReportRead])
def list_reports(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    statement = select(Report)
    if current_user.role != "admin":
        statement = statement.where(Report.owner_id == current_user.id)
    statement = statement.order_by(Report.created_at.desc(), Report.id.desc()).limit(limit).offset(offset)
    return db.scalars(statement).all()

@router.get("/{report_id}", response_model=ReportRead)
def get_report(
    report_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    report = db.get(Report, report_id)
    if report is None or (current_user.role != "admin" and report.owner_id != current_user.id):
        raise HTTPException(status_code=404, detail="Report not found")
    return report
