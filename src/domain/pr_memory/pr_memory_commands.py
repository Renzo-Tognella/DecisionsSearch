from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from decisionssearch.domain.catalog.catalog_validation import normalize_optional_text, normalize_required_text


def _normalize_unique_strings(value: object, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    else:
        try:
            items = list(value)
        except TypeError as error:
            raise ValueError(f"{field_name} must be an iterable of strings") from error

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} items must be strings")
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return normalized


class CreatePRMemoryCommand(BaseModel):
    project: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    objective: str = ""
    changed_files: list[str] = Field(default_factory=list)
    pr_url: str = Field(min_length=1)
    branch: str = ""
    work_item_id: str = ""
    work_item_url: str = Field(min_length=1)
    work_item_summary: str = ""
    work_item_provider: str = ""
    areas: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    status: str = "open"
    merged_at: str = ""
    event_date: str = ""

    @field_validator(
        "project", "repo", "title", "summary",
        "pr_url", "work_item_url",
        mode="before",
    )
    @classmethod
    def normalize_required_fields(cls, value: object, info) -> str:
        return normalize_required_text(value, info.field_name)

    @field_validator(
        "objective",
        "branch",
        "work_item_id",
        "work_item_summary",
        "work_item_provider",
        "status",
        "merged_at",
        "event_date",
        mode="before",
    )
    @classmethod
    def normalize_optional_fields(cls, value: object, info) -> str:
        return normalize_optional_text(value, info.field_name)

    @field_validator("changed_files", "areas", "authors", mode="before")
    @classmethod
    def normalize_lists(cls, value: object, info) -> list[str]:
        normalized = _normalize_unique_strings(value, info.field_name)
        if info.field_name == "changed_files" and not normalized:
            raise ValueError("changed_files cannot be empty")
        return normalized
