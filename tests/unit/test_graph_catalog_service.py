from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from decisionssearch.domain import (
    CategoryNode,
    CreateCategoryCommand,
    CreateDomainCommand,
    CreateProjectCommand,
    DomainNode,
    ProjectNode,
    UpdateCategoryCommand,
    UpdateDomainCommand,
    UpdateProjectCommand,
)
from decisionssearch.domain.catalog.catalog_validation import generate_catalog_id
from decisionssearch.application.catalog.graph_catalog_service import GraphCatalogService


@dataclass
class FakeNeo4j:
    project_nodes: list[dict] = field(default_factory=list)
    category_nodes: list[dict] = field(default_factory=list)
    domain_nodes: list[dict] = field(default_factory=list)
    project_calls: list[ProjectNode] = field(default_factory=list)
    category_calls: list[CategoryNode] = field(default_factory=list)
    domain_calls: list[DomainNode] = field(default_factory=list)

    async def upsert_project_node(self, node: ProjectNode) -> None:
        self.project_calls.append(node)
        row = node.model_dump(mode="json")
        self.project_nodes = [item for item in self.project_nodes if item["id"] != row["id"]]
        self.project_nodes.append(row)

    async def upsert_category_node(self, node: CategoryNode) -> None:
        self.category_calls.append(node)
        row = node.model_dump(mode="json")
        self.category_nodes = [item for item in self.category_nodes if item["id"] != row["id"]]
        self.category_nodes.append(row)

    async def upsert_domain_node(self, node: DomainNode) -> None:
        self.domain_calls.append(node)
        row = node.model_dump(mode="json")
        self.domain_nodes = [item for item in self.domain_nodes if item["id"] != row["id"]]
        self.domain_nodes.append(row)

    async def list_project_nodes(self) -> list[dict]:
        return list(self.project_nodes)

    async def list_category_nodes(self) -> list[dict]:
        return list(self.category_nodes)

    async def list_domain_nodes(self) -> list[dict]:
        return list(self.domain_nodes)


def test_create_and_update_project_delegate_to_neo4j() -> None:
    neo4j = FakeNeo4j()
    service = GraphCatalogService(neo4j=neo4j)

    created = asyncio.run(
        service.create_project(
            CreateProjectCommand(
                slug="core-platform",
                name="Core Platform",
                description="Main project",
                aliases=[" Core ", "core"],
                tags=[" Platform ", "platform"],
            )
        )
    )
    updated = asyncio.run(
        service.update_project(
            UpdateProjectCommand(
                id="proj-1",
                slug="core-platform",
                name="Core Platform V2",
                description="Updated project",
                aliases=["Core"],
                tags=["Platform"],
            )
        )
    )

    assert neo4j.project_calls == [
        ProjectNode(
            id=generate_catalog_id("project", "core-platform"),
            slug="core-platform",
            name="Core Platform",
            description="Main project",
            aliases=["Core", "core"],
            tags=["Platform"],
        ),
        ProjectNode(
            id="proj-1",
            slug="core-platform",
            name="Core Platform V2",
            description="Updated project",
            aliases=["Core"],
            tags=["Platform"],
        ),
    ]
    assert created["id"] == generate_catalog_id("project", "core-platform")
    assert updated["id"] == "proj-1"
    assert asyncio.run(service.get_project("proj-1"))["name"] == "Core Platform V2"
    assert asyncio.run(service.get_project("core-platform"))["id"] == generate_catalog_id(
        "project",
        "core-platform",
    )
    assert asyncio.run(service.list_projects()) == neo4j.project_nodes


def test_create_project_generates_stable_id_distinct_from_slug() -> None:
    neo4j = FakeNeo4j()
    service = GraphCatalogService(neo4j=neo4j)
    command = CreateProjectCommand(slug="core-platform", name="Core Platform")

    created_first = asyncio.run(service.create_project(command))
    created_second = asyncio.run(service.create_project(command))

    assert created_first["id"] == created_second["id"]
    assert created_first["id"] != command.slug


def test_create_category_and_domain_generate_stable_ids_distinct_from_slug() -> None:
    neo4j = FakeNeo4j()
    service = GraphCatalogService(neo4j=neo4j)

    category_command = CreateCategoryCommand(
        slug="design-rule",
        name="Design Rule",
        project_id="proj-1",
    )
    domain_command = CreateDomainCommand(
        slug="billing",
        name="Billing",
        project_id="proj-1",
    )

    category_first = asyncio.run(service.create_category(category_command))
    category_second = asyncio.run(service.create_category(category_command))
    domain_first = asyncio.run(service.create_domain(domain_command))
    domain_second = asyncio.run(service.create_domain(domain_command))

    assert category_first["id"] == category_second["id"]
    assert category_first["id"] != category_command.slug
    assert domain_first["id"] == domain_second["id"]
    assert domain_first["id"] != domain_command.slug


def test_create_update_and_search_category_delegate_to_neo4j() -> None:
    neo4j = FakeNeo4j()
    service = GraphCatalogService(neo4j=neo4j)

    created = asyncio.run(
        service.create_category(
            CreateCategoryCommand(
                slug="design-rule",
                name="Design Rule",
                description="Guideline",
                project_id="proj-1",
                aliases=["Rule"],
                tags=["architecture"],
            )
        )
    )
    updated = asyncio.run(
        service.update_category(
            UpdateCategoryCommand(
                id="cat-1",
                slug="design-rule",
                name="Design Rule V2",
                description="Updated",
                project_id="proj-1",
                aliases=["Rule"],
                tags=["architecture"],
            )
        )
    )

    assert neo4j.category_calls == [
        CategoryNode(
            id=generate_catalog_id("category", "design-rule", scope="proj-1"),
            slug="design-rule",
            name="Design Rule",
            description="Guideline",
            project_id="proj-1",
            aliases=["Rule"],
            tags=["architecture"],
        ),
        CategoryNode(
            id="cat-1",
            slug="design-rule",
            name="Design Rule V2",
            description="Updated",
            project_id="proj-1",
            aliases=["Rule"],
            tags=["architecture"],
        ),
    ]
    assert created["id"] == generate_catalog_id("category", "design-rule", scope="proj-1")
    assert created["project_id"] == "proj-1"
    assert updated["id"] == "cat-1"
    assert asyncio.run(service.get_category("cat-1"))["name"] == "Design Rule V2"
    assert asyncio.run(service.get_category("design-rule"))["id"] == generate_catalog_id(
        "category",
        "design-rule",
        scope="proj-1",
    )
    assert asyncio.run(service.list_categories()) == neo4j.category_nodes


def test_get_project_category_and_domain_return_none_when_missing_or_name_only() -> None:
    neo4j = FakeNeo4j(
        project_nodes=[{"id": "proj-1", "slug": "core-platform", "name": "Core Platform"}],
        category_nodes=[{"id": "cat-1", "slug": "design-rule", "name": "Design Rule"}],
        domain_nodes=[{"id": "dom-1", "slug": "billing", "name": "Billing"}],
    )
    service = GraphCatalogService(neo4j=neo4j)

    assert asyncio.run(service.get_project("missing")) is None
    assert asyncio.run(service.get_project("Core Platform")) is None
    assert asyncio.run(service.get_category("missing")) is None
    assert asyncio.run(service.get_category("Design Rule")) is None
    assert asyncio.run(service.get_domain("missing")) is None
    assert asyncio.run(service.get_domain("Billing")) is None


def test_create_update_and_search_domain_delegate_to_neo4j() -> None:
    neo4j = FakeNeo4j()
    service = GraphCatalogService(neo4j=neo4j)

    created = asyncio.run(
        service.create_domain(
            CreateDomainCommand(
                slug="billing",
                name="Billing",
                description="Finance domain",
                project_id="proj-1",
                aliases=["Finance"],
                tags=["money"],
            )
        )
    )
    updated = asyncio.run(
        service.update_domain(
            UpdateDomainCommand(
                id="dom-1",
                slug="billing",
                name="Billing V2",
                description="Updated",
                project_id="proj-1",
                aliases=["Finance"],
                tags=["money"],
            )
        )
    )

    assert neo4j.domain_calls == [
        DomainNode(
            id=generate_catalog_id("domain", "billing", scope="proj-1"),
            slug="billing",
            name="Billing",
            description="Finance domain",
            project_id="proj-1",
            aliases=["Finance"],
            tags=["money"],
        ),
        DomainNode(
            id="dom-1",
            slug="billing",
            name="Billing V2",
            description="Updated",
            project_id="proj-1",
            aliases=["Finance"],
            tags=["money"],
        ),
    ]
    assert created["id"] == generate_catalog_id("domain", "billing", scope="proj-1")
    assert created["project_id"] == "proj-1"
    assert updated["id"] == "dom-1"
    assert asyncio.run(service.get_domain("dom-1"))["name"] == "Billing V2"
    assert asyncio.run(service.get_domain("billing"))["id"] == generate_catalog_id(
        "domain",
        "billing",
        scope="proj-1",
    )
    assert asyncio.run(service.list_domains()) == neo4j.domain_nodes


def test_delete_project_category_and_domain_delegate_to_neo4j() -> None:
    @dataclass
    class DeletableNeo4j(FakeNeo4j):
        delete_calls: list[tuple[str, str]] = field(default_factory=list)

        async def delete_catalog_node(self, node_id: str, kind: str) -> None:
            self.delete_calls.append((node_id, kind))

    neo4j = DeletableNeo4j()
    service = GraphCatalogService(neo4j=neo4j)

    asyncio.run(service.delete_project("proj-1"))
    asyncio.run(service.delete_category("cat-1"))
    asyncio.run(service.delete_domain("dom-1"))

    assert neo4j.delete_calls == [
        ("proj-1", "project"),
        ("cat-1", "category"),
        ("dom-1", "domain"),
    ]
