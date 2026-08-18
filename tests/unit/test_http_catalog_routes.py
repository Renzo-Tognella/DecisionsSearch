from __future__ import annotations

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from decisionssearch.domain import (
    AdmissionError,
    CatalogConflictError,
    CatalogImportError,
    CatalogNotFoundError,
    CreateCategoryCommand,
    CreateDomainCommand,
    CreateManualMemoryCommand,
    CreateProjectCommand,
    CreateRelationCommand,
    DeleteRelationCommand,
    MemoryServiceError,
    UpdateProjectCommand,
)
from decisionssearch.interfaces.http.http_app import create_http_app


@dataclass
class FakeGraphCatalogService:
    projects: list[dict] = field(default_factory=list)
    categories: list[dict] = field(default_factory=list)
    domains: list[dict] = field(default_factory=list)
    create_project_calls: list[CreateProjectCommand] = field(default_factory=list)
    update_project_calls: list[UpdateProjectCommand] = field(default_factory=list)
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
        self.projects = [item for item in self.projects if item["id"] != row["id"]]
        self.projects.append(row)
        return row

    async def update_project(self, command: UpdateProjectCommand) -> dict:
        self.update_project_calls.append(command)
        row = {
            "id": command.id,
            "slug": command.slug,
            "name": command.name,
            "description": command.description,
            "status": command.status,
            "aliases": command.aliases,
            "tags": command.tags,
        }
        self.projects = [item for item in self.projects if item["id"] != row["id"]]
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
        self.categories = [item for item in self.categories if item["id"] != row["id"]]
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
        self.domains = [item for item in self.domains if item["id"] != row["id"]]
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

    async def list_relations(self) -> list[dict]:
        return list(self.relations)


@dataclass
class FakeManualMemoryAuthoringService:
    calls: list[CreateManualMemoryCommand] = field(default_factory=list)
    next_error: Exception | None = None

    async def create_manual_memory(self, command: CreateManualMemoryCommand):
        self.calls.append(command)
        if self.next_error is not None:
            raise self.next_error

        return {
            "memory_id": "mem-1",
            "project": command.project,
            "category": command.category,
            "domain": command.domain,
            "modules": command.modules,
            "title": command.title,
            "summary": command.summary,
            "details": command.details,
            "examples": command.examples,
            "alternatives_considered": command.alternatives_considered,
            "event_date": command.event_date or None,
            "status": "active",
        }


@dataclass
class FakeCatalogCsvService:
    next_error: Exception | None = None

    async def export_catalog_csv_bundle(self) -> dict[str, str]:
        if self.next_error is not None:
            raise self.next_error
        return {
            "schema_version": "1",
            "projects_csv": "id,slug,name,description,status,aliases,tags\n",
            "categories_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
            "domains_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
            "relations_csv": "source_id,source_kind,relation_type,target_id,target_kind,rationale\n",
        }

    async def import_catalog_csv_bundle(self, bundle: dict[str, str]) -> dict[str, object]:
        if self.next_error is not None:
            raise self.next_error
        return {
            "status": "ok",
            "schema_version": bundle["schema_version"],
            "imported": {"projects": 0, "categories": 0, "domains": 0, "relations": 0},
        }


@dataclass
class FakeContainer:
    graph_catalog: FakeGraphCatalogService
    graph_operations: FakeGraphOperationsService
    catalog_csv: FakeCatalogCsvService
    manual_memory_authoring: FakeManualMemoryAuthoringService


def _make_client(container: FakeContainer) -> TestClient:
    app = create_http_app(container)
    return TestClient(app, raise_server_exceptions=False)


def test_catalog_routes_translate_payloads_and_return_json() -> None:
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(
            projects=[{"id": "proj-existing", "slug": "existing", "name": "Existing"}],
        ),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )
    client = _make_client(container)

    response = client.get("/catalog/projects")
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "proj-existing",
            "slug": "existing",
            "name": "Existing",
            "description": "",
            "status": "active",
            "aliases": [],
            "tags": [],
            "project_id": None,
        }
    ]

    response = client.post(
        "/catalog/projects",
        json={
            "slug": " Core-Platform ",
            "name": "Core Platform",
            "description": "Main project",
            "aliases": [" Core ", "core", "Core"],
            "tags": [" Platform ", "platform"],
        },
    )
    assert response.status_code == 200
    assert response.json()["slug"] == "core-platform"
    assert response.json()["aliases"] == ["Core", "core"]
    assert container.graph_catalog.create_project_calls[0].slug == "core-platform"

    response = client.patch(
        "/catalog/projects/proj-1",
        json={
            "slug": " Core-Platform ",
            "name": "Core Platform v2",
            "description": "Updated",
            "aliases": ["Core"],
            "tags": ["Platform"],
        },
    )
    assert response.status_code == 200
    assert response.json()["id"] == "proj-1"
    assert container.graph_catalog.update_project_calls[0].id == "proj-1"

    response = client.get("/catalog/categories")
    assert response.status_code == 200
    assert response.json() == []

    response = client.post(
        "/catalog/categories",
        json={
            "slug": "design-rule",
            "name": "Design Rule",
            "description": "Guideline",
            "project_id": "proj-1",
            "aliases": ["Rule"],
            "tags": ["architecture"],
        },
    )
    assert response.status_code == 200
    assert response.json()["project_id"] == "proj-1"
    assert container.graph_catalog.create_category_calls[0].project_id == "proj-1"

    response = client.get("/catalog/domains")
    assert response.status_code == 200
    assert response.json() == []

    response = client.post(
        "/catalog/domains",
        json={
            "slug": "billing",
            "name": "Billing",
            "description": "Finance domain",
            "project_id": "proj-1",
            "aliases": ["Finance"],
            "tags": ["money"],
        },
    )
    assert response.status_code == 200
    assert response.json()["project_id"] == "proj-1"
    assert container.graph_catalog.create_domain_calls[0].project_id == "proj-1"

    response = client.post(
        "/catalog/relations",
        json={
            "source_id": "proj-1",
            "source_kind": "project",
            "relation_type": "RELATED_TO",
            "target_id": "cat-1",
            "target_kind": "category",
            "rationale": "link",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert container.graph_operations.create_calls[0].relation_type == "RELATED_TO"

    response = client.request(
        "DELETE",
        "/catalog/relations",
        json={
            "source_id": "proj-1",
            "source_kind": "project",
            "relation_type": "RELATED_TO",
            "target_id": "cat-1",
            "target_kind": "category",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert container.graph_operations.delete_calls[0].target_id == "cat-1"


def test_catalog_routes_map_real_service_memory_errors_to_structured_http_errors() -> None:
    class FailingGraphCatalogService(FakeGraphCatalogService):
        async def list_projects(self) -> list[dict]:
            raise MemoryServiceError("Falha ao listar projetos do catalogo no Neo4j: timeout")

        async def create_category(self, command: CreateCategoryCommand) -> dict:
            raise MemoryServiceError(
                "Falha ao persistir categoria no Neo4j: Projeto pai nao encontrado para o catalogo",
                context={"project_id": command.project_id},
            )

        async def create_domain(self, command: CreateDomainCommand) -> dict:
            raise MemoryServiceError(
                "Falha ao persistir dominio no Neo4j: Projeto pai nao encontrado para o catalogo",
                context={"project_id": command.project_id},
            )

    class FailingGraphOperationsService(FakeGraphOperationsService):
        async def create_relation(self, command: CreateRelationCommand) -> None:
            raise MemoryServiceError(
                "Falha ao criar relacao do catalogo no Neo4j: Tipo de no catalogo invalido",
                context={
                    "source_id": command.source_id,
                    "source_kind": command.source_kind,
                    "relation_type": command.relation_type,
                    "target_id": command.target_id,
                    "target_kind": command.target_kind,
                },
            )

        async def delete_relation(self, command: DeleteRelationCommand) -> None:
            raise MemoryServiceError(
                "Falha ao remover relacao do catalogo no Neo4j: Relacao do catalogo nao encontrada para remocao",
                context={
                    "source_id": command.source_id,
                    "source_kind": command.source_kind,
                    "relation_type": command.relation_type,
                    "target_id": command.target_id,
                    "target_kind": command.target_kind,
                },
            )

    container = FakeContainer(
        graph_catalog=FailingGraphCatalogService(),
        graph_operations=FailingGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )
    client = _make_client(container)

    response = client.get("/catalog/projects")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "catalog_unavailable"
    assert response.json()["detail"]["operation"] == "list_projects"

    response = client.post(
        "/catalog/categories",
        json={
            "slug": "design-rule",
            "name": "Design Rule",
            "description": "Guideline",
            "project_id": "proj-missing",
            "aliases": ["Rule"],
            "tags": ["architecture"],
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "catalog_project_not_found"
    assert response.json()["detail"]["resource"] == "category"

    response = client.post(
        "/catalog/domains",
        json={
            "slug": "billing",
            "name": "Billing",
            "description": "Finance domain",
            "project_id": "proj-missing",
            "aliases": ["Finance"],
            "tags": ["money"],
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "catalog_project_not_found"
    assert response.json()["detail"]["resource"] == "domain"

    response = client.post(
        "/catalog/relations",
        json={
            "source_id": "proj-1",
            "source_kind": "invalid-kind",
            "relation_type": "RELATED_TO",
            "target_id": "cat-1",
            "target_kind": "category",
            "rationale": "link",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "catalog_invalid_kind"
    assert response.json()["detail"]["resource"] == "relation"

    response = client.request(
        "DELETE",
        "/catalog/relations",
        json={
            "source_id": "proj-1",
            "source_kind": "project",
            "relation_type": "RELATED_TO",
            "target_id": "cat-1",
            "target_kind": "category",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "catalog_relation_not_found"
    assert response.json()["detail"]["resource"] == "relation"


def test_manual_memory_route_propagates_new_fields() -> None:
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )
    client = _make_client(container)

    response = client.post(
        "/memories/manual",
        json={
            "project": "CORE",
            "category": "ArchitecturalDecision",
            "domain": ["Infrastructure"],
            "modules": ["faturamento", "TUSD"],
            "title": "Use PostgreSQL",
            "summary": "Chose PostgreSQL over alternatives",
            "details": "Selected PostgreSQL for relational workloads.",
            "alternatives_considered": [
                "MongoDB — descartado por falta de joins complexos",
            ],
            "event_date": "2026-04-22T10:00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["modules"] == ["faturamento", "TUSD"]
    assert body["alternatives_considered"] == [
        "MongoDB — descartado por falta de joins complexos",
    ]
    assert body["event_date"] is not None
    command = container.manual_memory_authoring.calls[0]
    assert command.modules == ["faturamento", "TUSD"]
    assert command.alternatives_considered == [
        "MongoDB — descartado por falta de joins complexos",
    ]


def test_manual_memory_route_defaults_project_to_workspace_folder(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DECISIONSSEARCH_PROJECT", raising=False)
    project_dir = tmp_path / "billing-service"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )
    client = _make_client(container)

    response = client.post(
        "/memories/manual",
        json={
            "category": "DesignRule",
            "title": "Cache key",
            "summary": "Include the tenant in the cache key",
        },
    )

    assert response.status_code == 200
    assert response.json()["project"] == "billing-service"
    assert container.manual_memory_authoring.calls[0].project == "billing-service"


def test_manual_memory_route_rejects_architectural_decision_without_alternatives() -> None:
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )
    client = _make_client(container)

    response = client.post(
        "/memories/manual",
        json={
            "project": "CORE",
            "category": "ArchitecturalDecision",
            "title": "Use PostgreSQL",
            "summary": "Chose PostgreSQL",
            "details": "Selected PostgreSQL.",
        },
    )

    assert response.status_code == 422
    assert container.manual_memory_authoring.calls == []


def test_manual_memory_route_rejects_code_pattern_without_examples() -> None:
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )
    client = _make_client(container)

    response = client.post(
        "/memories/manual",
        json={
            "project": "CORE",
            "category": "CodePattern",
            "title": "Guard Clauses",
            "summary": "Use guard clauses",
            "details": "Prefer early returns.",
        },
    )

    assert response.status_code == 422
    assert container.manual_memory_authoring.calls == []


def test_manual_memory_route_maps_admission_error_to_http_error() -> None:
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FakeManualMemoryAuthoringService(
            next_error=AdmissionError(
                "A autoria manual foi rejeitada pela admissao",
                gate="manual_authoring",
                candidate_title="Forms Pattern",
                context={"status": "rejected"},
            )
        ),
    )
    client = _make_client(container)

    response = client.post(
        "/memories/manual",
        json={
            "project": "CORE",
            "category": "DesignRule",
            "domain": ["Billing"],
            "title": "Forms Pattern",
            "summary": "Use forms for writes",
            "details": "Keep writes centralized",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["gate"] == "manual_authoring"
    assert response.json()["detail"]["context"]["status"] == "rejected"


def test_catalog_routes_map_not_found_and_conflict_errors() -> None:
    class FailingCatalogService(FakeGraphCatalogService):
        async def update_project(self, command: UpdateProjectCommand) -> dict:
            raise CatalogNotFoundError(
                "project not found",
                resource="project",
                identifier=command.id,
            )

    class FailingManualMemoryService(FakeManualMemoryAuthoringService):
        async def create_manual_memory(self, command: CreateManualMemoryCommand):
            raise CatalogConflictError(
                "duplicate",
                resource="project",
                identifier=command.project,
            )

    container = FakeContainer(
        graph_catalog=FailingCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(),
        manual_memory_authoring=FailingManualMemoryService(),
    )
    client = _make_client(container)

    response = client.patch(
        "/catalog/projects/proj-404",
        json={"slug": "core-platform", "name": "Core Platform"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["resource"] == "project"

    response = client.post(
        "/memories/manual",
        json={
            "project": "CORE",
            "category": "DesignRule",
            "domain": ["Billing"],
            "title": "Forms Pattern",
            "summary": "Use forms for writes",
            "details": "Keep writes centralized",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["resource"] == "project"


def test_catalog_csv_routes_surface_import_validation_errors() -> None:
    container = FakeContainer(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
        catalog_csv=FakeCatalogCsvService(
            next_error=CatalogImportError(
                "schema_version invalida para importacao do catalogo",
                source="bundle",
            )
        ),
        manual_memory_authoring=FakeManualMemoryAuthoringService(),
    )
    client = _make_client(container)

    response = client.post(
        "/catalog/import/csv",
        json={
            "schema_version": "999",
            "projects_csv": "id,slug,name,description,status,aliases,tags\n",
            "categories_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
            "domains_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
            "relations_csv": "source_id,source_kind,relation_type,target_id,target_kind,rationale\n",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "catalog_import_error"
    assert response.json()["detail"]["source"] == "bundle"
