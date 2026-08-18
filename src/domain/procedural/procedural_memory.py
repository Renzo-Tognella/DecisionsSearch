from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ProceduralMemory(BaseModel):
    procedure_id: str = Field(description="Unique procedure identifier")
    project: str
    task_type: str = Field(description="Category of task this procedure solves")
    steps: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    tools_required: list[str] = Field(default_factory=list)
    success_rate: float = Field(ge=0.0, le=1.0, default=1.0)
    usage_count: int = 0
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
