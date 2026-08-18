from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TelemetryEvent:
    event_type: str
    memory_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict = field(default_factory=dict)


class TelemetryService:
    def __init__(self):
        self.events: list[TelemetryEvent] = []

    def record_retrieval(self, memory_id: str) -> None:
        self.events.append(TelemetryEvent("retrieval", memory_id))

    def record_acceptance(self, memory_id: str) -> None:
        self.events.append(TelemetryEvent("acceptance", memory_id))

    def record_rejection(self, memory_id: str, reason: str = "") -> None:
        self.events.append(TelemetryEvent("rejection", memory_id, context={"reason": reason}))

    def record_feedback(self, memory_id: str, score: float) -> None:
        self.events.append(TelemetryEvent("feedback", memory_id, context={"score": score}))

    def get_usage_stats(self, memory_id: str) -> dict:
        selected = [event for event in self.events if event.memory_id == memory_id]
        feedbacks = [
            event.context.get("score", 0.0)
            for event in selected
            if event.event_type == "feedback"
        ]
        avg_feedback = (sum(feedbacks) / len(feedbacks)) if feedbacks else 0.0
        return {
            "total_retrievals": sum(1 for event in selected if event.event_type == "retrieval"),
            "total_acceptances": sum(1 for event in selected if event.event_type == "acceptance"),
            "total_rejections": sum(1 for event in selected if event.event_type == "rejection"),
            "avg_feedback": round(avg_feedback, 4),
        }
