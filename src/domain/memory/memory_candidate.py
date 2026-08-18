from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class EvidenceRef(BaseModel):
    type: str = Field(description="commit, diff, conversation, document")
    ref: str = Field(description="Referencia da evidencia")
    snippet: str = Field(default="", description="Trecho relevante")

    @field_validator("ref", "snippet", "type", mode="before")
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        return value.strip()


class MemoryCandidate(BaseModel):
    project: str
    type: str = Field(
        description="FeatureDescription, BusinessRule, ArchitecturalDecision, DesignPattern, DesignRule, CodePattern",
    )
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
    tags: list[str] = Field(default_factory=list)
    proposed_weight: float = Field(ge=0.0, le=1.0, default=0.5)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    source_event_id: str = ""

    @field_validator(
        "details",
        "objective",
        "trigger",
        "architectural_rationale",
        "project",
        "summary",
        "title",
        "type",
        mode="before",
    )
    @classmethod
    def strip_required_text_fields(cls, value: str) -> str:
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
        "tags",
        mode="before",
    )
    @classmethod
    def normalize_string_lists(cls, value: list[str] | None) -> list[str]:
        if value is None:
            return []
        return [item.strip() for item in value if item.strip()]
