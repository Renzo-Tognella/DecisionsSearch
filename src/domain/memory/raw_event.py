from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceKind(StrEnum):
    CONVERSATION = "conversation"
    COMMIT = "commit"
    DIFF = "diff"
    PR = "pull_request"
    DOCUMENT = "document"
    GUIDELINE = "guideline"
    ANNOTATION = "annotation"
    TOOL_OUTPUT = "tool_output"


class RawEvent(BaseModel):
    event_id: str = Field(description="UUID unico do evento")
    source_kind: SourceKind
    payload: str = Field(description="Conteudo bruto original")
    project_hint: str | None = Field(default=None, description="Projeto sugerido")
    domain_hint: str | None = Field(default=None, description="Dominio sugerido")
    author: str | None = None
    correlation_id: str | None = Field(default=None, description="ID da tarefa de origem")
    metadata: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "author",
        "correlation_id",
        "domain_hint",
        "event_id",
        "payload",
        "project_hint",
        mode="before",
    )
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
