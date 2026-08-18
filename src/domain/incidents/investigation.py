from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class InvestigationStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class Investigation(BaseModel):
    investigation_id: str = Field(default_factory=lambda: str(__import__("uuid").uuid4()))
    error_id: str
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    status: InvestigationStatus = InvestigationStatus.IN_PROGRESS
    investigator: str = "decisionssearch-autonomous-agent"
    hypothesis: str = ""
    findings: str = ""
    root_cause_type: str = ""
    root_cause_id: str = ""
    fix_pr_url: str = ""
    confidence: float = 0.0
    sources_used: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    status: str  # "fixed", "needs_human", "unclear"
    root_cause: str = ""
    fix_description: str = ""
    files_modified: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    suspect_pr_identified: str | None = None
    risks: list[str] = Field(default_factory=list)
    testing_notes: str = ""
