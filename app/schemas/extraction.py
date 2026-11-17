"""Strict, application-owned contract for an LLM extraction result."""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    modality: str = Field(min_length=1, max_length=80)
    body_part: str = Field(min_length=1, max_length=120)
    findings: list[str] = Field(min_length=1, max_length=30)
    impression: str = Field(min_length=1, max_length=4000)
    is_critical: bool
    critical_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_findings_and_reason(self):
        if any(not item.strip() or len(item) > 1000 for item in self.findings):
            raise ValueError("Findings must be nonempty and at most 1000 characters")
        if self.is_critical and not (self.critical_reason and self.critical_reason.strip()):
            raise ValueError("A critical result must include a reason")
        if not self.is_critical and self.critical_reason:
            raise ValueError("Noncritical results must have null critical_reason")
        return self
