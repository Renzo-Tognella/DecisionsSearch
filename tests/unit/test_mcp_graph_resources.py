from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.interfaces.mcp.resources import register_resources


@dataclass
class FakeMCPApp:
    resources: dict[str, object] = field(default_factory=dict)

    def resource(self, uri: str):  # noqa: ANN201
        def decorator(func):
            self.resources[uri] = func
            return func

        return decorator


@dataclass
class FakeGraphCatalogService:
    async def list_projects(self) -> list[dict]:
        return [{"id": "proj-1", "slug": "core", "name": "Core"}]

    async def get_project(self, identifier: str) -> dict | None:
        if identifier == "core":
            return {"id": "proj-1", "slug": "core", "name": "Core"}
        return None

    async def list_categories(self) -> list[dict]:
        return [
            {"id": "cat-1", "slug": "design-rule", "name": "Design Rule", "project_id": "proj-1"},
            {"id": "cat-2", "slug": "other", "name": "Other", "project_id": "proj-2"},
        ]

    async def list_domains(self) -> list[dict]:
        return [
            {"id": "dom-1", "slug": "billing", "name": "Billing", "project_id": "core"},
            {"id": "dom-2", "slug": "ops", "name": "Ops", "project_id": "proj-2"},
        ]


@dataclass
class FakeGraphOperationsService:
    async def catalog_summary(self) -> dict:
        return {"projects": {"count": 1}, "categories": {"count": 2}, "domains": {"count": 2}}

    async def list_allowed_relations(self) -> list[str]:
        return ["RELATED_TO", "DEPENDS_ON"]


@dataclass
class FakeContainer:
    graph_catalog: object
    graph_operations: object


def test_register_resources_exposes_graph_catalog_snapshots() -> None:
    app = FakeMCPApp()
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
    )

    register_resources(app, container)

    expected = {
        "graph://projects",
        "graph://project/{project_slug}/categories",
        "graph://project/{project_slug}/domains",
        "graph://catalog/summary",
        "graph://relations/allowed",
    }

    assert expected.issubset(app.resources)

    projects = json.loads(asyncio.run(app.resources["graph://projects"]()))
    categories = json.loads(asyncio.run(app.resources["graph://project/{project_slug}/categories"]("core")))
    domains = json.loads(asyncio.run(app.resources["graph://project/{project_slug}/domains"]("core")))
    summary = json.loads(asyncio.run(app.resources["graph://catalog/summary"]()))
    allowed = json.loads(asyncio.run(app.resources["graph://relations/allowed"]()))

    assert projects == [{"id": "proj-1", "slug": "core", "name": "Core"}]
    assert categories == [{"id": "cat-1", "slug": "design-rule", "name": "Design Rule", "project_id": "proj-1"}]
    assert domains == [{"id": "dom-1", "slug": "billing", "name": "Billing", "project_id": "core"}]
    assert summary == {"projects": {"count": 1}, "categories": {"count": 2}, "domains": {"count": 2}}
    assert allowed == ["RELATED_TO", "DEPENDS_ON"]


def test_resources_surface_service_errors_as_json_error_payloads() -> None:
    @dataclass
    class FailingGraphCatalogService(FakeGraphCatalogService):
        async def list_projects(self) -> list[dict]:
            raise MemoryServiceError("catalog unavailable")

    app = FakeMCPApp()
    container = FakeContainer(
        graph_catalog=FailingGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
    )

    register_resources(app, container)

    payload = json.loads(asyncio.run(app.resources["graph://projects"]()))

    assert payload == {"error": "catalog unavailable", "type": "MemoryServiceError"}
