from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class AuditService:
    def __init__(self, log_file: str = "data/audit/audit.jsonl"):
        self.log_path = Path(log_file)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_tool_call(
        self,
        tool_name: str,
        params: dict,
        result: dict,
        user: str = "agent",
    ) -> None:
        self._write(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "tool_call",
                "tool": tool_name,
                "user": user,
                "params": params,
                "result_status": result.get("status", "unknown"),
            }
        )

    def log_memory_change(
        self,
        action: str,
        memory_id: str,
        changes: dict,
        rationale: str = "",
    ) -> None:
        self._write(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "memory_change",
                "action": action,
                "memory_id": memory_id,
                "changes": changes,
                "rationale": rationale,
            }
        )

    def _write(self, entry: dict) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
