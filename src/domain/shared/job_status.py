from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class JobRun(BaseModel):
    job_name: str
    run_id: str = Field(default_factory=lambda: str(__import__("uuid").uuid4()))
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    status: str = "running"  # running, completed, failed
    error: str | None = None
    result_summary: dict[str, Any] | None = None


class JobDefinition(BaseModel):
    name: str
    trigger_type: str = ""  # interval, cron
    trigger_value: str = ""
    next_run: str | None = None
    last_run: JobRun | None = None
    is_paused: bool = False
