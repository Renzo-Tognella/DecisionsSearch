from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from decisionssearch.interfaces.mcp.tools import register_tools


@dataclass
class FakeMCPApp:
    tools: dict[str, object] = field(default_factory=dict)

    def tool(self, name: str | None = None):
        def decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return decorator


@dataclass
class FakeSanitization:
    validated: list[str] = field(default_factory=list)
    sanitized: list[str] = field(default_factory=list)

    def validate_payload_size(self, payload: str) -> None:
        self.validated.append(payload)

    def sanitize(self, payload: str) -> str:
        self.sanitized.append(payload)
        return f"sanitized:{payload}"


@dataclass
class FakeResolver:
    calls: list[dict] = field(default_factory=list)

    async def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "project": kwargs["project_hint"],
            "domain": [],
            "probable_category": "DesignRule",
        }


@dataclass
class FakeExtraction:
    calls: list[dict] = field(default_factory=list)

    async def extract_candidates(self, **kwargs):
        self.calls.append(kwargs)
        return []


@dataclass
class FakeLandingZone:
    events: list[object] = field(default_factory=list)

    def append_raw_event(self, event) -> None:
        self.events.append(event)


@dataclass
class FakeAudit:
    tool_calls: list[tuple] = field(default_factory=list)

    def log_tool_call(self, *args) -> None:
        self.tool_calls.append(args)


@dataclass
class FakeContainer:
    sanitization: FakeSanitization
    resolver: FakeResolver
    extraction: FakeExtraction
    landing_zone: FakeLandingZone
    audit: FakeAudit


def test_ingest_raw_tags_event_and_extraction_with_workspace_project(tmp_path, monkeypatch):
    monkeypatch.delenv("DECISIONSSEARCH_PROJECT", raising=False)
    project_dir = tmp_path / "billing-service"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    container = FakeContainer(
        sanitization=FakeSanitization(),
        resolver=FakeResolver(),
        extraction=FakeExtraction(),
        landing_zone=FakeLandingZone(),
        audit=FakeAudit(),
    )
    app = FakeMCPApp()
    register_tools(app, container)

    result = asyncio.run(
        app.tools["memory.ingest_raw"](
            source_kind="document",
            payload="Use a tenant-qualified cache key",
        )
    )

    assert result["status"] == "received"
    assert result["context"]["project"] == "billing-service"
    assert container.resolver.calls[0]["project_hint"] == "billing-service"
    assert container.landing_zone.events[0].project_hint == "billing-service"
    assert container.extraction.calls[0]["project"] == "billing-service"
    assert container.extraction.calls[0]["content"] == "sanitized:Use a tenant-qualified cache key"
