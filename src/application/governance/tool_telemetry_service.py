"""Telemetria append-only de chamadas de tool MCP (G7 do plano de melhorias).

Complementa o `TelemetryService` (que mede retrieval/acceptance/feedback de
memórias) com o que faltava: **qual tool MCP foi chamada**, com qual hash de
args, latência, tamanho do resultado e erro. Sem isso, decisões como consolidar
tools (C2) ou tunar o scorer (C4) são apostas.

Privacy: grava o **hash** dos args, nunca os valores (args podem conter PII).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


def result_size(result: object) -> int:
    """Tamanho 'lógico' do resultado: nº de itens (lista) ou 1 (dict/escalar)."""
    if isinstance(result, list):
        return len(result)
    if result is None:
        return 0
    return 1


class ToolTelemetryService:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("TOOL_TELEMETRY_PATH", "data/tool_usage.jsonl"))
        self._lock = threading.Lock()

    @staticmethod
    def hash_args(args: dict) -> str:
        try:
            payload = json.dumps(args, sort_keys=True, default=str)
        except Exception:
            payload = str(args)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def record_tool_call(
        self,
        tool_name: str,
        args_hash: str,
        latency_ms: float,
        result_size: int,
        error: str | None = None,
    ) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool_name,
            "args_hash": args_hash,
            "latency_ms": round(latency_ms, 2),
            "result_size": result_size,
            "error": error,
        }
        line = json.dumps(record, ensure_ascii=False)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except Exception:
            # Telemetria nunca deve derrubar uma tool.
            pass
