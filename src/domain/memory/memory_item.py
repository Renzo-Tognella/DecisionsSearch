import hashlib
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from decisionssearch.domain.shared.branch import DEFAULT_BRANCH, normalize_branch


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"
    EVIDENCE_ONLY = "evidence_only"


class MemoryItem(BaseModel):
    memory_id: str = Field(description="Hash canonico: project+type+title")
    project: str
    category: str
    branch: str = Field(default=DEFAULT_BRANCH, description="Ramo lógico da memória")
    domain: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    title: str
    summary: str
    details: str = ""
    objective: str = ""
    trigger: str = ""
    stakeholders: list[str] = Field(default_factory=list)
    action_triggers: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    architectural_rationale: str = ""
    examples: list[str] = Field(default_factory=list)
    alternatives_considered: list[str] = Field(default_factory=list)
    event_date: datetime | None = None
    status: MemoryStatus = MemoryStatus.PROPOSED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    valid_at: datetime = Field(default_factory=utc_now)
    invalid_at: datetime | None = None
    access_count: int = 0
    weight_manual: float = Field(ge=0.0, le=1.0, default=0.5)
    weight_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    weight_usage: float = Field(ge=0.0, le=1.0, default=0.0)
    weight_feedback: float = Field(ge=0.0, le=1.0, default=0.0)
    weight_contextual: float = Field(ge=0.0, le=1.0, default=0.5)
    last_accessed_at: datetime | None = None
    significance: float = Field(ge=0.0, le=1.0, default=0.5)
    effective_weight: float = Field(ge=0.0, le=1.0, default=0.5)
    source_hash: str = ""
    evidence_count: int = 0

    @staticmethod
    def generate_id(project: str, type: str, title: str) -> str:
        normalized = f"{project.strip()}:{type.strip()}:{title.lower().strip()}"
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    @field_validator(
        "category",
        "details",
        "objective",
        "trigger",
        "architectural_rationale",
        "memory_id",
        "project",
        "source_hash",
        "summary",
        "title",
        mode="before",
    )
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator(
        "domain",
        "modules",
        "stakeholders",
        "action_triggers",
        "related_files",
        "business_rules",
        "examples",
        "alternatives_considered",
        mode="before",
    )
    @classmethod
    def normalize_string_lists(cls, value: list[str] | None) -> list[str]:
        if value is None:
            return []
        return [item.strip() for item in value if item.strip()]

    @field_validator("branch", mode="before")
    @classmethod
    def normalize_branch_field(cls, value: str | None) -> str:
        return normalize_branch(value or "") or DEFAULT_BRANCH
