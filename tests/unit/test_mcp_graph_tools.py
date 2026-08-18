from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from decisionssearch.domain import (
    CatalogImportError,
    CreateCategoryCommand,
    CreateDomainCommand,
    CreateManualMemoryCommand,
    CreateProjectCommand,
    CreateRelationCommand,
    DeleteRelationCommand,
    MemoryItem,
    UpdateCategoryCommand,
    UpdateDomainCommand,
    UpdateProjectCommand,
)
from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.interfaces.mcp.tools import register_tools


@dataclass
class FakeMCPApp:
    tools: dict[str, object] = field(default_factory=dict)

    def tool(self, name: str | None = None):  # noqa: ANN201
        def decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return decorator


@dataclass
class FakeGraphCatalogService:
    create_project_calls: list[CreateProjectCommand] = field(default_factory=list)
    update_project_calls: list[UpdateProjectCommand] = field(default_factory=list)
    create_category_calls: list[CreateCategoryCommand] = field(default_factory=list)
    update_category_calls: list[UpdateCategoryCommand] = field(default_factory=list)
    create_domain_calls: list[CreateDomainCommand] = field(default_factory=list)
    update_domain_calls: list[UpdateDomainCommand] = field(default_factory=list)

    async def create_project(self, command: CreateProjectCommand) -> dict:
        self.create_project_calls.append(command)
        return {"id": "proj-1", "slug": command.slug, "name": command.name}

    async def update_project(self, command: UpdateProjectCommand) -> dict:
        self.update_project_calls.append(command)
        return {"id": command.id, "slug": command.slug, "name": command.name}

    async def list_projects(self) -> list[dict]:
        return [{"id": "proj-1", "slug": "core", "name": "Core"}]

    async def create_category(self, command: CreateCategoryCommand) -> dict:
        self.create_category_calls.append(command)
        return {"id": "cat-1", "slug": command.slug, "name": command.name, "project_id": command.project_id}

    async def update_category(self, command: UpdateCategoryCommand) -> dict:
        self.update_category_calls.append(command)
        return {"id": command.id, "slug": command.slug, "name": command.name, "project_id": command.project_id}

    async def create_domain(self, command: CreateDomainCommand) -> dict:
        self.create_domain_calls.append(command)
        return {"id": "dom-1", "slug": command.slug, "name": command.name, "project_id": command.project_id}

    async def update_domain(self, command: UpdateDomainCommand) -> dict:
        self.update_domain_calls.append(command)
        return {"id": command.id, "slug": command.slug, "name": command.name, "project_id": command.project_id}


@dataclass
class FakeGraphOperationsService:
    create_calls: list[CreateRelationCommand] = field(default_factory=list)
    delete_calls: list[DeleteRelationCommand] = field(default_factory=list)

    async def create_relation(self, command: CreateRelationCommand) -> None:
        self.create_calls.append(command)

    async def delete_relation(self, command: DeleteRelationCommand) -> None:
        self.delete_calls.append(command)


@dataclass
class FakeManualMemoryAuthoringService:
    calls: list[CreateManualMemoryCommand] = field(default_factory=list)
    next_error: Exception | None = None

    async def create_manual_memory(self, command: CreateManualMemoryCommand) -> MemoryItem:
        self.calls.append(command)
        if self.next_error is not None:
            raise self.next_error
        return MemoryItem(
            memory_id="mem-1",
            project=command.project,
            category=command.category,
            domain=command.domain,
            title=command.title,
            summary=command.summary,
            details=command.details,
        )


@dataclass
class FakeCatalogCsvService:
    export_calls: int = 0
    import_calls: list[dict[str, str]] = field(default_factory=list)

    async def export_catalog_csv_bundle(self) -> dict[str, str]:
        self.export_calls += 1
        return {
            "schema_version": "1",
            "projects_csv": "id,slug,name,description,status,aliases,tags\n",
            "categories_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
            "domains_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
            "relations_csv": "source_id,source_kind,relation_type,target_id,target_kind,rationale\n",
        }

    async def import_catalog_csv_bundle(self, bundle: dict[str, str]) -> dict[str, object]:
        self.import_calls.append(bundle)
        if bundle["schema_version"] == "fail":
            raise CatalogImportError("invalid bundle", source="bundle")
        return {
            "status": "ok",
            "schema_version": bundle["schema_version"],
            "imported": {"projects": 1, "categories": 0, "domains": 0, "relations": 0},
        }


@dataclass
class FakeContainer:
    graph_catalog: FakeGraphCatalogService
    graph_operations: FakeGraphOperationsService
    catalog_csv: FakeCatalogCsvService
    manual_memory_authoring: FakeManualMemoryAuthoringService


def test_register_tools_exposes_graph_catalog_and_manual_memory_tools() -> None:
    app = FakeMCPApp()
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )

    register_tools(app, container)

    expected = {
        "graph.project.create",
        "graph.catalog.export_csv",
        "graph.catalog.import_csv",
        "graph.project.update",
        "graph.project.list",
        "graph.category.create",
        "graph.category.update",
        "graph.domain.create",
        "graph.domain.update",
        "graph.relation.create",
        "graph.relation.delete",
        "memory.manual.create",
    }

    assert expected.issubset(app.tools)


def test_graph_tools_delegate_to_shared_services() -> None:
    app = FakeMCPApp()
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )
    register_tools(app, container)

    exported_bundle = asyncio.run(app.tools["graph.catalog.export_csv"]())
    imported_bundle = asyncio.run(
        app.tools["graph.catalog.import_csv"](
            schema_version="1",
            projects_csv="id,slug,name,description,status,aliases,tags\nproj-1,core,Core,,,,\n",
        )
    )
    created_project = asyncio.run(app.tools["graph.project.create"](slug="core", name="Core"))
    updated_project = asyncio.run(app.tools["graph.project.update"](id="proj-1", slug="core", name="Core v2"))
    listed_projects = asyncio.run(app.tools["graph.project.list"]())
    created_category = asyncio.run(
        app.tools["graph.category.create"](slug="design-rule", name="Design Rule", project_id="proj-1")
    )
    updated_category = asyncio.run(
        app.tools["graph.category.update"](
            id="cat-1",
            slug="design-rule",
            name="Design Rule v2",
            project_id="proj-1",
        )
    )
    created_domain = asyncio.run(
        app.tools["graph.domain.create"](slug="billing", name="Billing", project_id="proj-1")
    )
    updated_domain = asyncio.run(
        app.tools["graph.domain.update"](id="dom-1", slug="billing", name="Billing v2", project_id="proj-1")
    )
    relation_created = asyncio.run(
        app.tools["graph.relation.create"](
            source_id="proj-1",
            source_kind="project",
            relation_type="RELATED_TO",
            target_id="cat-1",
            target_kind="category",
            rationale="link",
        )
    )
    relation_deleted = asyncio.run(
        app.tools["graph.relation.delete"](
            source_id="proj-1",
            source_kind="project",
            relation_type="RELATED_TO",
            target_id="cat-1",
            target_kind="category",
        )
    )
    manual_memory = asyncio.run(
        app.tools["memory.manual.create"](
            project="CORE",
            category="DesignRule",
            domain=["Billing"],
            title="Forms Pattern",
            summary="Use forms for writes",
            details="Keep writes centralized",
        )
    )

    assert exported_bundle["schema_version"] == "1"
    assert imported_bundle["status"] == "ok"
    assert created_project["id"] == "proj-1"
    assert updated_project["id"] == "proj-1"
    assert listed_projects == [{"id": "proj-1", "slug": "core", "name": "Core"}]
    assert created_category["project_id"] == "proj-1"
    assert updated_category["id"] == "cat-1"
    assert created_domain["project_id"] == "proj-1"
    assert updated_domain["id"] == "dom-1"
    assert relation_created == {"status": "linked"}
    assert relation_deleted == {"status": "deleted"}
    assert manual_memory["memory_id"] == "mem-1"

    assert container.graph_catalog.create_project_calls[0] == CreateProjectCommand(slug="core", name="Core")
    assert container.catalog_csv.import_calls[0]["schema_version"] == "1"
    assert container.graph_catalog.update_project_calls[0] == UpdateProjectCommand(
        id="proj-1",
        slug="core",
        name="Core v2",
    )
    assert container.graph_catalog.create_category_calls[0] == CreateCategoryCommand(
        slug="design-rule",
        name="Design Rule",
        project_id="proj-1",
    )
    assert container.graph_catalog.update_category_calls[0] == UpdateCategoryCommand(
        id="cat-1",
        slug="design-rule",
        name="Design Rule v2",
        project_id="proj-1",
    )
    assert container.graph_catalog.create_domain_calls[0] == CreateDomainCommand(
        slug="billing",
        name="Billing",
        project_id="proj-1",
    )
    assert container.graph_catalog.update_domain_calls[0] == UpdateDomainCommand(
        id="dom-1",
        slug="billing",
        name="Billing v2",
        project_id="proj-1",
    )
    assert container.graph_operations.create_calls[0] == CreateRelationCommand(
        source_id="proj-1",
        source_kind="project",
        relation_type="RELATED_TO",
        target_id="cat-1",
        target_kind="category",
        rationale="link",
    )
    assert container.graph_operations.delete_calls[0] == DeleteRelationCommand(
        source_id="proj-1",
        source_kind="project",
        relation_type="RELATED_TO",
        target_id="cat-1",
        target_kind="category",
    )
    assert container.manual_memory_authoring.calls[0] == CreateManualMemoryCommand(
        project="CORE",
        category="DesignRule",
        domain=["Billing"],
        title="Forms Pattern",
        summary="Use forms for writes",
        details="Keep writes centralized",
    )


def test_graph_tools_surface_service_errors_as_error_dicts() -> None:
    app = FakeMCPApp()
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(
            next_error=MemoryServiceError("manual failed")
        ),
    )
    register_tools(app, container)

    result = asyncio.run(
        app.tools["memory.manual.create"](
            project="CORE",
            category="DesignRule",
            title="Forms Pattern",
            summary="Use forms for writes",
        )
    )

    assert result == {"error": "manual failed", "type": "MemoryServiceError"}

    csv_result = asyncio.run(app.tools["graph.catalog.import_csv"](schema_version="fail"))

    assert csv_result == {"error": "invalid bundle", "type": "CatalogImportError"}
