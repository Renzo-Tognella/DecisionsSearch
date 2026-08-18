from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from decisionssearch.domain import CatalogImportError, CreateCategoryCommand, CreateDomainCommand, CreateProjectCommand, CreateRelationCommand
from decisionssearch.application.catalog.catalog_csv_service import CatalogCsvService


@dataclass
class FakeGraphCatalogService:
    projects: list[dict] = field(default_factory=list)
    categories: list[dict] = field(default_factory=list)
    domains: list[dict] = field(default_factory=list)
    create_project_calls: list[CreateProjectCommand] = field(default_factory=list)
    create_category_calls: list[CreateCategoryCommand] = field(default_factory=list)
    create_domain_calls: list[CreateDomainCommand] = field(default_factory=list)

    async def list_projects(self) -> list[dict]:
        return list(self.projects)

    async def list_categories(self) -> list[dict]:
        return list(self.categories)

    async def list_domains(self) -> list[dict]:
        return list(self.domains)

    async def create_project(self, command: CreateProjectCommand) -> dict:
        self.create_project_calls.append(command)
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
        self.create_category_calls.append(command)
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
        self.create_domain_calls.append(command)
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
class FakeGraphOperationsService:
    relations: list[dict] = field(default_factory=list)
    create_relation_calls: list[CreateRelationCommand] = field(default_factory=list)

    async def list_relations(self) -> list[dict]:
        return list(self.relations)

    async def create_relation(self, command: CreateRelationCommand) -> None:
        self.create_relation_calls.append(command)
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


def test_export_bundle_contains_schema_and_consistent_csv_payloads() -> None:
    graph_catalog = FakeGraphCatalogService(
        projects=[
            {
                "id": "proj-core",
                "slug": "core",
                "name": "Core",
                "description": "Main project",
                "status": "active",
                "aliases": ["CORE", "Core Platform"],
                "tags": ["platform", "core"],
            }
        ],
        categories=[
            {
                "id": "cat-design-rule",
                "slug": "design-rule",
                "name": "Design Rule",
                "description": "Guideline",
                "status": "active",
                "aliases": ["Rule"],
                "tags": ["architecture"],
                "project_id": "proj-core",
            }
        ],
        domains=[
            {
                "id": "dom-billing",
                "slug": "billing",
                "name": "Billing",
                "description": "Finance",
                "status": "active",
                "aliases": ["Finance"],
                "tags": ["money"],
                "project_id": "proj-core",
            }
        ],
    )
    graph_operations = FakeGraphOperationsService(
        relations=[
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
    service = CatalogCsvService(graph_catalog=graph_catalog, graph_operations=graph_operations)

    bundle = asyncio.run(service.export_catalog_csv_bundle())

    assert bundle["schema_version"] == service.SCHEMA_VERSION
    assert "id,slug,name,description,status,aliases,tags" in bundle["projects_csv"]
    assert "proj-core,core,Core,Main project,active,CORE|Core Platform,platform|core" in bundle["projects_csv"]
    assert "project_id" in bundle["categories_csv"]
    assert "relation_type" in bundle["relations_csv"]


def test_import_bundle_validates_all_rows_before_persisting() -> None:
    service = CatalogCsvService(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
    )

    with pytest.raises(CatalogImportError, match="schema_version"):
        asyncio.run(
            service.import_catalog_csv_bundle(
                {
                    "schema_version": "999",
                    "projects_csv": "id,slug,name,description,status,aliases,tags\n",
                    "categories_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
                    "domains_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
                    "relations_csv": "source_id,source_kind,relation_type,target_id,target_kind,rationale\n",
                }
            )
        )

    with pytest.raises(CatalogImportError, match="colunas obrigatorias"):
        asyncio.run(
            service.import_catalog_csv_bundle(
                {
                    "schema_version": service.SCHEMA_VERSION,
                    "projects_csv": "slug,name\ncore,Core\n",
                    "categories_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
                    "domains_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
                    "relations_csv": "source_id,source_kind,relation_type,target_id,target_kind,rationale\n",
                }
            )
        )

    with pytest.raises(CatalogImportError, match="slug"):
        asyncio.run(
            service.import_catalog_csv_bundle(
                {
                    "schema_version": service.SCHEMA_VERSION,
                    "projects_csv": "id,slug,name,description,status,aliases,tags\nproj-core,Core Space,Core,,,," "\n",
                    "categories_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
                    "domains_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
                    "relations_csv": "source_id,source_kind,relation_type,target_id,target_kind,rationale\n",
                }
            )
        )


def test_import_bundle_rejects_missing_project_or_relation_references() -> None:
    service = CatalogCsvService(
        graph_catalog=FakeGraphCatalogService(),
        graph_operations=FakeGraphOperationsService(),
    )

    with pytest.raises(CatalogImportError, match="project_id"):
        asyncio.run(
            service.import_catalog_csv_bundle(
                {
                    "schema_version": service.SCHEMA_VERSION,
                    "projects_csv": "id,slug,name,description,status,aliases,tags\n",
                    "categories_csv": (
                        "id,slug,name,description,status,aliases,tags,project_id\n"
                        "cat-design-rule,design-rule,Design Rule,,,,,proj-missing\n"
                    ),
                    "domains_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
                    "relations_csv": "source_id,source_kind,relation_type,target_id,target_kind,rationale\n",
                }
            )
        )

    with pytest.raises(CatalogImportError, match="referencia"):
        asyncio.run(
            service.import_catalog_csv_bundle(
                {
                    "schema_version": service.SCHEMA_VERSION,
                    "projects_csv": "id,slug,name,description,status,aliases,tags\nproj-core,core,Core,,,,\n",
                    "categories_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
                    "domains_csv": "id,slug,name,description,status,aliases,tags,project_id\n",
                    "relations_csv": (
                        "source_id,source_kind,relation_type,target_id,target_kind,rationale\n"
                        "proj-missing,project,RELATED_TO,proj-core,project,broken\n"
                    ),
                }
            )
        )


def test_import_bundle_persists_projects_categories_domains_and_relations() -> None:
    graph_catalog = FakeGraphCatalogService()
    graph_operations = FakeGraphOperationsService()
    service = CatalogCsvService(graph_catalog=graph_catalog, graph_operations=graph_operations)

    result = asyncio.run(
        service.import_catalog_csv_bundle(
            {
                "schema_version": service.SCHEMA_VERSION,
                "projects_csv": (
                    "id,slug,name,description,status,aliases,tags\n"
                    "proj-core,core,Core,Main project,active,CORE|Core Platform,platform|core\n"
                ),
                "categories_csv": (
                    "id,slug,name,description,status,aliases,tags,project_id\n"
                    "cat-design-rule,design-rule,Design Rule,Guideline,active,Rule,architecture,proj-core\n"
                ),
                "domains_csv": (
                    "id,slug,name,description,status,aliases,tags,project_id\n"
                    "dom-billing,billing,Billing,Finance,active,Finance,money,proj-core\n"
                ),
                "relations_csv": (
                    "source_id,source_kind,relation_type,target_id,target_kind,rationale\n"
                    "proj-core,project,RELATED_TO,dom-billing,domain,important\n"
                ),
            }
        )
    )

    assert result == {
        "status": "ok",
        "schema_version": service.SCHEMA_VERSION,
        "imported": {
            "projects": 1,
            "categories": 1,
            "domains": 1,
            "relations": 1,
        },
    }
    assert graph_catalog.create_project_calls == [CreateProjectCommand(slug="core", name="Core", description="Main project", aliases=["CORE", "Core Platform"], tags=["platform", "core"])]
    assert graph_catalog.create_category_calls == [CreateCategoryCommand(slug="design-rule", name="Design Rule", description="Guideline", project_id="proj-core", aliases=["Rule"], tags=["architecture"])]
    assert graph_catalog.create_domain_calls == [CreateDomainCommand(slug="billing", name="Billing", description="Finance", project_id="proj-core", aliases=["Finance"], tags=["money"])]
    assert graph_operations.create_relation_calls == [
        CreateRelationCommand(
            source_id="proj-core",
            source_kind="project",
            relation_type="RELATED_TO",
            target_id="dom-billing",
            target_kind="domain",
            rationale="important",
        )
    ]
