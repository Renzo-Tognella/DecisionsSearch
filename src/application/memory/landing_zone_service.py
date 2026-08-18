from __future__ import annotations

import json
from pathlib import Path

from decisionssearch.domain.memory.raw_event import RawEvent


class LandingZoneService:
    """Persistencia de RawEvent em JSONL para rastreabilidade."""

    def __init__(self, base_dir: str = "data/landing_zone"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.raw_events_path = self.base_dir / "raw_events.jsonl"

    def append_raw_event(self, event: RawEvent) -> None:
        with self.raw_events_path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")

    def read_raw_events(self, limit: int = 100) -> list[RawEvent]:
        if not self.raw_events_path.exists():
            return []

        lines = self.raw_events_path.read_text(encoding="utf-8").splitlines()
        selected = lines[-limit:]
        events: list[RawEvent] = []
        for line in selected:
            if not line.strip():
                continue
            events.append(RawEvent(**json.loads(line)))
        return events
