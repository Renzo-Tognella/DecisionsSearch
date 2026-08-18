from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class NotificationType(StrEnum):
    ERROR_ALERT = "error_alert"
    DAILY_SUMMARY = "daily_summary"
    PR_ACTIVITY = "pr_activity"
    INVESTIGATION = "investigation"


class NotificationSeverity(StrEnum):
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class NotificationEnvelope(BaseModel):
    notification_id: str = Field(default_factory=lambda: str(__import__("uuid").uuid4()))
    type: NotificationType
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    title: str = Field(max_length=256)
    body: str = Field(max_length=4000)
    severity: NotificationSeverity = NotificationSeverity.INFO
    url: str = ""
    urls: list[dict[str, str]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    batch_key: str = ""
