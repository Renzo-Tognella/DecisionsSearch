from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class FakeNeo4jForBiTemporal:
    query_at_calls: list[dict] = field(default_factory=list)

    async def query_at_point_in_time(
        self,
        project: str,
        point_in_time: datetime,
        category: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        self.query_at_calls.append(
            {
                "project": project,
                "point_in_time": point_in_time,
                "category": category,
                "limit": limit,
            }
        )
        return [
            {
                "memory": {
                    "memory_id": "mem-001",
                    "title": "Guard Clauses Pattern",
                    "status": "active",
                    "effective_weight": 0.8,
                    "valid_at": "2025-01-01T00:00:00Z",
                    "invalid_at": None,
                },
                "related_titles": [],
            }
        ]


@dataclass
class FakeMCPApp:
    tools: dict[str, object] = field(default_factory=dict)

    def tool(self, name: str | None = None):
        def decorator(func):
            self.tools[name or func.__name__] = func
            return func
        return decorator


def test_memory_query_at_tool_is_registered() -> None:
    from decisionssearch.interfaces.mcp.tools import register_tools

    app = FakeMCPApp()

    @dataclass
    class FakeContainer:
        pr_memory: object = None
        graph_catalog: object = None
        graph_operations: object = None
        catalog_csv: object = None
        manual_memory_authoring: object = None
        search: object = None
        telemetry: object = None
        sanitization: object = None
        resolver: object = None
        extraction: object = None
        admission: object = None
        persistence: object = None
        neo4j: object = None
        qdrant: object = None
        landing_zone: object = None
        audit: object = None
        weight: object = None
        consolidation: object = None

    container = FakeContainer()
    register_tools(app, container)

    assert "memory.query_at" in app.tools, (
        "Tool memory.query_at must be registered for temporal queries"
    )


def test_neo4j_service_has_query_at_method() -> None:
    from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService

    assert hasattr(Neo4jService, "query_at_point_in_time"), (
        "Neo4jService must have query_at_point_in_time method"
    )


def test_fake_neo4j_query_at_returns_temporal_snapshot() -> None:
    neo4j = FakeNeo4jForBiTemporal()
    point = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = asyncio.run(
        neo4j.query_at_point_in_time(
            project="CORE",
            point_in_time=point,
            category="BusinessRule",
        )
    )

    assert len(result) == 1
    assert result[0]["memory"]["title"] == "Guard Clauses Pattern"
    assert neo4j.query_at_calls[0]["project"] == "CORE"
    assert neo4j.query_at_calls[0]["point_in_time"] == point
    assert neo4j.query_at_calls[0]["category"] == "BusinessRule"
