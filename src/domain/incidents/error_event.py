from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ErrorSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ErrorStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    WONT_FIX = "wontfix"
    DUPLICATE = "duplicate"


class StackFrame(BaseModel):
    file: str
    line: int = 0
    function: str = ""


class ErrorEvent(BaseModel):
    error_id: str = Field(default_factory=lambda: str(__import__("uuid").uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error_type: str
    error_message: str
    stack_trace: str = ""
    stack_frames: list[StackFrame] = Field(default_factory=list)
    stack_trace_hash: str = ""
    severity: ErrorSeverity = ErrorSeverity.HIGH
    service: str
    environment: str = "production"
    status: ErrorStatus = ErrorStatus.OPEN
    count: int = 1
    first_seen: str = ""
    last_seen: str = ""
    resolved_at: str | None = None
    resolution_notes: str = ""
    host: str = ""
    request_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""

    def model_post_init(self, __context):
        if not self.stack_trace_hash and self.stack_trace:
            import hashlib
            normalized = "".join(self.stack_trace.split())
            self.stack_trace_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        if not self.first_seen:
            self.first_seen = self.timestamp
        if not self.last_seen:
            self.last_seen = self.timestamp
        if not self.stack_frames and self.stack_trace:
            self.stack_frames = self._parse_stack_frames(self.stack_trace)

    @staticmethod
    def _parse_stack_frames(trace: str) -> list[StackFrame]:
        import re
        frames = []
        pattern = re.compile(r'File\s+"([^"]+)",\s+line\s+(\d+)(?:,\s+in\s+(\w+))?')
        for m in pattern.finditer(trace):
            frames.append(StackFrame(
                file=m.group(1), line=int(m.group(2)),
                function=m.group(3) or "",
            ))
        return frames


class ErrorPattern(BaseModel):
    name: str
    error_type: str
    occurrence_count: int = 0
    sample_message: str = ""
    services: list[str] = Field(default_factory=list)
    severity: ErrorSeverity = ErrorSeverity.HIGH
    observations: list[str] = Field(default_factory=list)
