from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from decisionssearch.domain.catalog.catalog_validation import normalize_required_text


class PRMemoryRelatedCandidate(BaseModel):
    memory_id: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    title: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    relation_type: str = "RELATED_TO"
    score: int = Field(ge=1)

    @field_validator("memory_id", "repo", "title", "reason", "relation_type", mode="before")
    @classmethod
    def normalize_required_fields(cls, value: object, info) -> str:
        return normalize_required_text(value, info.field_name)
