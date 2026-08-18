from __future__ import annotations

import asyncio
import json

from decisionssearch.application.governance.tool_telemetry_service import ToolTelemetryService, result_size


def test_hash_args_stable_and_order_independent():
    t = ToolTelemetryService()
    assert t.hash_args({"a": 1, "b": 2}) == t.hash_args({"b": 2, "a": 1})
    assert t.hash_args({"a": 1}) != t.hash_args({"a": 2})


def test_result_size():
    assert result_size([1, 2, 3]) == 3
    assert result_size({"x": 1}) == 1
    assert result_size(None) == 0


def test_record_tool_call_writes_jsonl(tmp_path):
    path = tmp_path / "tool_usage.jsonl"
    t = ToolTelemetryService(path=str(path))
    t.record_tool_call("memory.query", "abc123", 12.5, 3, None)
    t.record_tool_call("memory.query", "def456", 4.0, 0, "ValueError")
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["tool"] == "memory.query"
    assert first["result_size"] == 3
    assert first["error"] is None


def test_instrumentation_records_call_and_preserves_schema(tmp_path):
    from mcp.server.fastmcp import FastMCP

    from decisionssearch.interfaces.mcp.tools import _instrument_tools

    path = tmp_path / "u.jsonl"
    telemetry = ToolTelemetryService(path=str(path))
    app = FastMCP("test")
    _instrument_tools(app, telemetry)

    @app.tool(name="demo.echo")
    async def echo(value: str) -> dict:
        """echo de teste"""
        return {"value": value}

    tools = asyncio.run(app.list_tools())
    assert any(getattr(tl, "name", "") == "demo.echo" for tl in tools)
    props = (tools[0].inputSchema or {}).get("properties", {})
    assert "value" in props  # schema preservado pelo functools.wraps

    asyncio.run(app.call_tool("demo.echo", {"value": "hi"}))
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["tool"] == "demo.echo"
    assert rec["error"] is None
