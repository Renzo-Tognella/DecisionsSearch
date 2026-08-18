from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.testclient import TestClient

from decisionssearch.domain import CreateCategoryCommand, CreateDomainCommand, CreateProjectCommand, CreateRelationCommand, DeleteRelationCommand
from decisionssearch.interfaces.http.asgi import create_asgi_app
from decisionssearch.interfaces.http.http_app import create_http_app


@dataclass
class FakeGraphCatalogService:
    projects: list[dict] = field(default_factory=lambda: [{"id": "proj-1", "slug": "core", "name": "Core"}])
    categories: list[dict] = field(default_factory=lambda: [{"id": "cat-1", "slug": "design-rule", "name": "Design Rule", "project_id": "proj-1"}])
    domains: list[dict] = field(default_factory=lambda: [{"id": "dom-1", "slug": "billing", "name": "Billing", "project_id": "proj-1"}])
    create_project_calls: list[CreateProjectCommand] = field(default_factory=list)
    create_category_calls: list[CreateCategoryCommand] = field(default_factory=list)
    create_domain_calls: list[CreateDomainCommand] = field(default_factory=list)

    async def list_projects(self) -> list[dict]:
        return list(self.projects)

    async def create_project(self, command: CreateProjectCommand) -> dict:
        self.create_project_calls.append(command)
        row = {
            "id": "proj-core-platform",
            "slug": command.slug,
            "name": command.name,
            "description": command.description,
            "status": command.status,
            "aliases": command.aliases,
            "tags": command.tags,
        }
        self.projects.append(row)
        return row

    async def list_categories(self) -> list[dict]:
        return list(self.categories)

    async def create_category(self, command: CreateCategoryCommand) -> dict:
        self.create_category_calls.append(command)
        row = {
            "id": "cat-design-rule",
            "slug": command.slug,
            "name": command.name,
            "description": command.description,
            "status": command.status,
            "aliases": command.aliases,
            "tags": command.tags,
            "project_id": command.project_id,
        }
        self.categories.append(row)
        return row

    async def list_domains(self) -> list[dict]:
        return list(self.domains)

    async def create_domain(self, command: CreateDomainCommand) -> dict:
        self.create_domain_calls.append(command)
        row = {
            "id": "dom-billing",
            "slug": command.slug,
            "name": command.name,
            "description": command.description,
            "status": command.status,
            "aliases": command.aliases,
            "tags": command.tags,
            "project_id": command.project_id,
        }
        self.domains.append(row)
        return row


@dataclass
class FakeGraphOperationsService:
    create_calls: list[CreateRelationCommand] = field(default_factory=list)
    delete_calls: list[DeleteRelationCommand] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)

    async def create_relation(self, command: CreateRelationCommand) -> None:
        self.create_calls.append(command)

    async def delete_relation(self, command: DeleteRelationCommand) -> None:
        self.delete_calls.append(command)
        return None

    async def list_relations(self) -> list[dict]:
        return list(self.relations)


@dataclass
class FakeManualMemoryAuthoringService:
    async def create_manual_memory(self, command):
        return {
            "memory_id": "mem-1",
            "project": command.project,
            "category": command.category,
            "domain": command.domain,
            "title": command.title,
            "summary": command.summary,
            "details": command.details,
            "status": "active",
        }


@dataclass
class FakeCatalogCsvService:
    async def export_catalog_csv_bundle(self) -> dict[str, str]:
        return {
            "schema_version": "1",
            "projects_csv": "id,slug,name,description,status,aliases,tags\n",
            "categories_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
            "domains_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
            "relations_csv": "source_id,source_kind,relation_type,target_id,target_kind,rationale\n",
        }

    async def import_catalog_csv_bundle(self, bundle: dict[str, str]) -> dict[str, object]:
        return {
            "status": "ok",
            "schema_version": bundle["schema_version"],
            "imported": {"projects": 0, "categories": 0, "domains": 0, "relations": 0},
        }


@dataclass
class FakeContainer:
    graph_catalog: FakeGraphCatalogService
    graph_operations: FakeGraphOperationsService
    catalog_csv: object
    manual_memory_authoring: FakeManualMemoryAuthoringService


def test_http_api_is_served_under_api_prefix() -> None:
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )
    http_app = create_http_app(container)
    mcp_app = FastAPI()

    @mcp_app.get("/")
    async def root() -> dict[str, str]:
        return {"status": "mcp-ok"}

    app = create_asgi_app(container=container, http_app=http_app, mcp_app=mcp_app)

    with TestClient(app) as client:
        health_response = client.get("/api/health")
        projects_response = client.get("/api/catalog/projects")
        categories_response = client.get("/api/catalog/categories")
        domains_response = client.get("/api/catalog/domains")
        create_response = client.post(
            "/api/catalog/projects",
            json={
                "slug": "Core-Platform",
                "name": "Core Platform",
                "description": "Main project",
            },
        )
        create_category_response = client.post(
            "/api/catalog/categories",
            json={
                "slug": "design-rule",
                "name": "Design Rule",
                "description": "Guideline",
                "project_id": "proj-1",
            },
        )
        create_domain_response = client.post(
            "/api/catalog/domains",
            json={
                "slug": "billing",
                "name": "Billing",
                "description": "Finance domain",
                "project_id": "proj-1",
            },
        )
        create_relation_response = client.post(
            "/api/catalog/relations",
            json={
                "source_id": "proj-1",
                "source_kind": "project",
                "relation_type": "RELATED_TO",
                "target_id": "cat-1",
                "target_kind": "category",
                "rationale": "link",
            },
        )
        delete_relation_response = client.request(
            "DELETE",
            "/api/catalog/relations",
            json={
                "source_id": "proj-1",
                "source_kind": "project",
                "relation_type": "RELATED_TO",
                "target_id": "cat-1",
                "target_kind": "category",
            },
        )
        memory_response = client.post(
            "/api/memories/manual",
            json={
                "project": "CORE",
                "category": "DesignRule",
                "domain": ["Billing"],
                "title": "Forms Pattern",
                "summary": "Use forms for writes",
                "details": "Keep writes centralized",
            },
        )

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert projects_response.status_code == 200
    assert projects_response.json()[0]["slug"] == "core"
    assert categories_response.status_code == 200
    assert categories_response.json()[0]["slug"] == "design-rule"
    assert domains_response.status_code == 200
    assert domains_response.json()[0]["slug"] == "billing"
    assert create_response.status_code == 200
    assert create_response.json()["slug"] == "core-platform"
    assert create_category_response.status_code == 200
    assert create_category_response.json()["project_id"] == "proj-1"
    assert create_domain_response.status_code == 200
    assert create_domain_response.json()["project_id"] == "proj-1"
    assert create_relation_response.status_code == 200
    assert create_relation_response.json() == {"status": "ok"}
    assert delete_relation_response.status_code == 200
    assert delete_relation_response.json() == {"status": "ok"}
    assert memory_response.status_code == 200
    assert memory_response.json()["memory_id"] == "mem-1"
