from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class EpisodeStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class EpisodicMemory(BaseModel):
    episode_id: str = Field(description="Unique episode identifier")
    project: str
    task_description: str
    approach: str = ""
    outcome: EpisodeStatus = EpisodeStatus.COMPLETED
    lessons: list[str] = Field(default_factory=list)
    related_memory_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
