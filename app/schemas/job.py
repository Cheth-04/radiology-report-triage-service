"""Public job-status contract: no report text or internal traceback is exposed."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "processing", "done", "failed"]


class JobResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    modality: str
    body_part: str
    findings: list[str]
    impression: str
    is_critical: bool
    critical_reason: str | None


class JobRead(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    result: JobResult | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
