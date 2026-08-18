from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from decisionssearch.domain import CreatePRMemoryCommand
from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.interfaces.mcp.tools import register_tools


PR_MEMORY_RELATIONS = {"IMPLEMENTS", "EVIDENCES", "MODIFIES"}


@dataclass
class FakeNeo4jForPRCrossRef:
    pr_link_calls: list[dict] = field(default_factory=list)
    pr_linked_memories_calls: list[dict] = field(default_factory=list)
    memory_linked_prs_calls: list[dict] = field(default_factory=list)
    upsert_pr_calls: list[dict] = field(default_factory=list)
    find_related_candidates_calls: list = field(default_factory=list)

    async def link_pr_to_memory(
        self,
        pr_memory_id: str,
        memory_id: str,
        relation_type: str,
        rationale: str = "",
    ) -> None:
        if relation_type not in PR_MEMORY_RELATIONS:
            raise MemoryServiceError(
                "Relacao invalida entre PR e MemoryItem",
                context={"relation_type": relation_type},
            )
        self.pr_link_calls.append(
            {
                "pr_memory_id": pr_memory_id,
                "memory_id": memory_id,
                "relation_type": relation_type,
                "rationale": rationale,
            }
        )

    async def query_pr_linked_memories(self, pr_memory_id: str) -> list[dict]:
        self.pr_linked_memories_calls.append({"pr_memory_id": pr_memory_id})
        return [
            {
                "memory_id": "mem-br-001",
                "title": "Guard Clauses Pattern",
                "category": "BusinessRule",
                "relation_type": "IMPLEMENTS",
                "rationale": "PR implements this rule",
            }
        ]

    async def query_memory_linked_prs(self, memory_id: str) -> list[dict]:
        self.memory_linked_prs_calls.append({"memory_id": memory_id})
        return [
            {
                "memory_id": "pr-abc123",
                "repo": "core-app",
                "pr_number": 42,
                "title": "Add guard clauses",
                "relation_type": "IMPLEMENTS",
            }
        ]

    async def upsert_pr_memory(self, memory) -> None:
        self.upsert_pr_calls.append(memory.model_dump(mode="json"))

    async def find_related_pr_candidates(self, memory, limit: int = 3) -> list[dict]:
        self.find_related_candidates_calls.append(memory.memory_id)
        return []


@dataclass
class FakePRMemoryService:
    neo4j: FakeNeo4jForPRCrossRef

    async def link_pr_to_memory(
        self,
        pr_memory_id: str,
        memory_id: str,
        relation_type: str = "IMPLEMENTS",
        rationale: str = "",
    ) -> dict:
        await self.neo4j.link_pr_to_memory(
            pr_memory_id=pr_memory_id,
            memory_id=memory_id,
            relation_type=relation_type,
            rationale=rationale,
        )
        return {
            "pr_memory_id": pr_memory_id,
            "memory_id": memory_id,
            "relation_type": relation_type,
            "status": "linked",
        }

    async def query_pr_linked_memories(self, pr_memory_id: str) -> list[dict]:
        return await self.neo4j.query_pr_linked_memories(pr_memory_id)

    async def query_memory_linked_prs(self, memory_id: str) -> list[dict]:
        return await self.neo4j.query_memory_linked_prs(memory_id)

    async def create_pr_memory(self, command: CreatePRMemoryCommand) -> dict:
        from decisionssearch.application.pr_memory.pr_memory_service import generate_pr_memory_id
        from decisionssearch.domain import PRMemory

        memory = PRMemory(
            memory_id=generate_pr_memory_id(command.project, command.repo, command.pr_number),
            **command.model_dump(),
        )
        await self.neo4j.upsert_pr_memory(memory)
        return memory.model_dump(mode="json")

    async def query_pr_memories(self, **kwargs) -> list[dict]:
        return []


@dataclass
class FakeMCPApp:
    tools: dict[str, object] = field(default_factory=dict)

    def tool(self, name: str | None = None):
        def decorator(func):
            self.tools[name or func.__name__] = func
            return func
        return decorator


@dataclass
class FakeGraphCatalogService:
    async def list_projects(self) -> list[dict]:
        return []

    async def create_project(self, command) -> dict:
        return {}

    async def update_project(self, command) -> dict:
        return {}

    async def create_category(self, command) -> dict:
        return {}

    async def update_category(self, command) -> dict:
        return {}

    async def create_domain(self, command) -> dict:
        return {}

    async def update_domain(self, command) -> dict:
        return {}


@dataclass
class FakeGraphOperationsService:
    async def create_relation(self, command) -> None:
        pass

    async def delete_relation(self, command) -> None:
        pass


@dataclass
class FakeCatalogCsvService:
    async def export_catalog_csv_bundle(self) -> dict:
        return {"schema_version": "1", "projects_csv": "", "categories_csv": "", "domains_csv": "", "relations_csv": ""}

    async def import_catalog_csv_bundle(self, bundle) -> dict:
        return {"status": "ok"}


@dataclass
class FakeManualMemoryAuthoringService:
    async def create_manual_memory(self, command):
        return {"memory_id": "mem-1"}


@dataclass
class FakeContainer:
    pr_memory: FakePRMemoryService
    graph_catalog: FakeGraphCatalogService = field(default_factory=FakeGraphCatalogService)
    graph_operations: FakeGraphOperationsService = field(default_factory=FakeGraphOperationsService)
    catalog_csv: FakeCatalogCsvService = field(default_factory=FakeCatalogCsvService)
    manual_memory_authoring: FakeManualMemoryAuthoringService = field(default_factory=FakeManualMemoryAuthoringService)

    # Stubs for other services that tools.py references
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


def _make_fixtures():
    neo4j = FakeNeo4jForPRCrossRef()
    pr_memory = FakePRMemoryService(neo4j=neo4j)
    container = FakeContainer(pr_memory=pr_memory)
    app = FakeMCPApp()
    register_tools(app, container)
    return app, container, neo4j


def test_pr_link_memory_tool_delegates_to_service() -> None:
    app, container, neo4j = _make_fixtures()

    assert "memory.pr.link_memory" in app.tools, (
        "Tool memory.pr.link_memory must be registered"
    )

    result = asyncio.run(
        app.tools["memory.pr.link_memory"](
            pr_memory_id="pr-abc",
            memory_id="mem-br-001",
            relation_type="IMPLEMENTS",
            rationale="PR implements guard clauses rule",
        )
    )

    assert result["status"] == "linked"
    assert result["pr_memory_id"] == "pr-abc"
    assert result["memory_id"] == "mem-br-001"
    assert result["relation_type"] == "IMPLEMENTS"
    assert neo4j.pr_link_calls[0]["pr_memory_id"] == "pr-abc"


def test_pr_link_memory_rejects_invalid_relation_type() -> None:
    app, container, neo4j = _make_fixtures()

    result = asyncio.run(
        app.tools["memory.pr.link_memory"](
            pr_memory_id="pr-abc",
            memory_id="mem-br-001",
            relation_type="INVALID_RELATION",
        )
    )

    assert "error" in result
    assert result["type"] == "MemoryServiceError"


def test_pr_query_linked_memories_tool() -> None:
    app, container, neo4j = _make_fixtures()

    assert "memory.pr.linked_memories" in app.tools, (
        "Tool memory.pr.linked_memories must be registered"
    )

    result = asyncio.run(
        app.tools["memory.pr.linked_memories"](pr_memory_id="pr-abc")
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["memory_id"] == "mem-br-001"
    assert result[0]["relation_type"] == "IMPLEMENTS"


def test_memory_query_linked_prs_tool() -> None:
    app, container, neo4j = _make_fixtures()

    assert "memory.linked_prs" in app.tools, (
        "Tool memory.linked_prs must be registered"
    )

    result = asyncio.run(
        app.tools["memory.linked_prs"](memory_id="mem-br-001")
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["pr_number"] == 42
    assert result[0]["relation_type"] == "IMPLEMENTS"
