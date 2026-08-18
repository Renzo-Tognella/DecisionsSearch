from __future__ import annotations

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from decisionssearch.domain import CreateCategoryCommand, CreateDomainCommand, CreateProjectCommand, CreateRelationCommand
from decisionssearch.interfaces.http.http_app import create_http_app


@dataclass
class InMemoryGraphCatalogService:
    projects: list[dict] = field(default_factory=lambda: [{"id": "proj-core", "slug": "core", "name": "Core", "description": "Main project", "status": "active", "aliases": ["CORE"], "tags": ["platform"]}])
    categories: list[dict] = field(default_factory=lambda: [{"id": "cat-design-rule", "slug": "design-rule", "name": "Design Rule", "description": "Guideline", "status": "active", "aliases": ["Rule"], "tags": ["architecture"], "project_id": "proj-core"}])
    domains: list[dict] = field(default_factory=lambda: [{"id": "dom-billing", "slug": "billing", "name": "Billing", "description": "Finance", "status": "active", "aliases": ["Finance"], "tags": ["money"], "project_id": "proj-core"}])

    async def list_projects(self) -> list[dict]:
        return list(self.projects)

    async def list_categories(self) -> list[dict]:
        return list(self.categories)

    async def list_domains(self) -> list[dict]:
        return list(self.domains)

    async def create_project(self, command: CreateProjectCommand) -> dict:
        row = {
            "id": f"proj-{command.slug}",
            "slug": command.slug,
            "name": command.name,
            "description": command.description,
            "status": command.status,
            "aliases": command.aliases,
            "tags": command.tags,
        }
        self.projects.append(row)
        return row

    async def create_category(self, command: CreateCategoryCommand) -> dict:
        row = {
            "id": f"cat-{command.slug}",
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

    async def create_domain(self, command: CreateDomainCommand) -> dict:
        row = {
            "id": f"dom-{command.slug}",
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
class InMemoryGraphOperationsService:
    relations: list[dict] = field(
        default_factory=lambda: [
            {
                "source_id": "proj-core",
                "source_kind": "project",
                "relation_type": "HAS_CATEGORY",
                "target_id": "cat-design-rule",
                "target_kind": "category",
                "rationale": "seed",
            }
        ]
    )

    async def list_relations(self) -> list[dict]:
        return list(self.relations)

    async def create_relation(self, command: CreateRelationCommand) -> None:
        self.relations.append(
            {
                "source_id": command.source_id,
                "source_kind": command.source_kind,
                "relation_type": command.relation_type,
                "target_id": command.target_id,
                "target_kind": command.target_kind,
                "rationale": command.rationale,
            }
        )


@dataclass
class FakeContainer:
    graph_catalog: InMemoryGraphCatalogService
    graph_operations: InMemoryGraphOperationsService
    catalog_csv: object


def test_catalog_csv_roundtrip_over_http() -> None:
    from decisionssearch.application.catalog.catalog_csv_service import CatalogCsvService

    source_catalog = InMemoryGraphCatalogService()
    source_operations = InMemoryGraphOperationsService()
    source_container = FakeContainer(
        graph_catalog=source_catalog,
        graph_operations=source_operations,
        catalog_csv=CatalogCsvService(graph_catalog=source_catalog, graph_operations=source_operations),
    )

    source_app = create_http_app(source_container)

    with TestClient(source_app) as source_client:
        export_response = source_client.get("/catalog/export/csv")

    assert export_response.status_code == 200
    bundle = export_response.json()
    assert bundle["schema_version"] == "1"
    assert "projects_csv" in bundle

    target_catalog = InMemoryGraphCatalogService(projects=[], categories=[], domains=[])
    target_operations = InMemoryGraphOperationsService(relations=[])
    target_container = FakeContainer(
        graph_catalog=target_catalog,
        graph_operations=target_operations,
        catalog_csv=CatalogCsvService(graph_catalog=target_catalog, graph_operations=target_operations),
    )

    target_app = create_http_app(target_container)

    with TestClient(target_app) as target_client:
        import_response = target_client.post("/catalog/import/csv", json=bundle)
        projects_response = target_client.get("/catalog/projects")
        categories_response = target_client.get("/catalog/categories")
        domains_response = target_client.get("/catalog/domains")

    assert import_response.status_code == 200
    assert import_response.json()["imported"] == {
        "projects": 1,
        "categories": 1,
        "domains": 1,
        "relations": 1,
    }
    assert projects_response.status_code == 200
    assert projects_response.json()[0]["slug"] == "core"
    assert categories_response.json()[0]["project_id"] == "proj-core"
    assert domains_response.json()[0]["project_id"] == "proj-core"
