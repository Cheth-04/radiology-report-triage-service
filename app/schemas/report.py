import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class ReportCreate(BaseModel):
    report_text: str = Field(min_length=10, max_length=20000)

    @field_validator("report_text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Report text cannot be blank")
        return value.strip()

class ReportAccepted(BaseModel):
    job_id: uuid.UUID
    status: Literal["queued"]

class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    owner_id: uuid.UUID
    report_text: str
    status: Literal["queued", "processing", "done", "failed"]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
