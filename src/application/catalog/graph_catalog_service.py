from __future__ import annotations

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
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService


class GraphCatalogService:
    """CRUD simples para nos estruturais do catalogo."""

    def __init__(self, neo4j: Neo4jService):
        self.neo4j = neo4j

    async def create_project(self, command: CreateProjectCommand) -> dict:
        node_id = generate_catalog_id("project", command.slug)
        node = ProjectNode(
            id=node_id,
            slug=command.slug,
            name=command.name,
            description=command.description,
            status=command.status,
            aliases=command.aliases,
            tags=command.tags,
        )
        await self.neo4j.upsert_project_node(node)
        return node.model_dump(mode="json")

    async def update_project(self, command: UpdateProjectCommand) -> dict:
        node = ProjectNode(
            id=command.id,
            slug=command.slug,
            name=command.name,
            description=command.description,
            status=command.status,
            aliases=command.aliases,
            tags=command.tags,
        )
        await self.neo4j.upsert_project_node(node)
        return node.model_dump(mode="json")

    async def list_projects(self) -> list[dict]:
        return await self.neo4j.list_project_nodes()

    async def get_project(self, identifier: str) -> dict | None:
        return self._find_node(await self.list_projects(), identifier)

    async def delete_project(self, identifier: str) -> None:
        await self.neo4j.delete_catalog_node(node_id=identifier, kind="project")

    async def create_category(self, command: CreateCategoryCommand) -> dict:
        node_id = generate_catalog_id("category", command.slug, scope=command.project_id)
        node = CategoryNode(
            id=node_id,
            slug=command.slug,
            name=command.name,
            description=command.description,
            status=command.status,
            aliases=command.aliases,
            tags=command.tags,
            project_id=command.project_id,
        )
        await self.neo4j.upsert_category_node(node)
        return node.model_dump(mode="json")

    async def update_category(self, command: UpdateCategoryCommand) -> dict:
        node = CategoryNode(
            id=command.id,
            slug=command.slug,
            name=command.name,
            description=command.description,
            status=command.status,
            aliases=command.aliases,
            tags=command.tags,
            project_id=command.project_id,
        )
        await self.neo4j.upsert_category_node(node)
        return node.model_dump(mode="json")

    async def list_categories(self) -> list[dict]:
        return await self.neo4j.list_category_nodes()

    async def get_category(self, identifier: str) -> dict | None:
        return self._find_node(await self.list_categories(), identifier)

    async def delete_category(self, identifier: str) -> None:
        await self.neo4j.delete_catalog_node(node_id=identifier, kind="category")

    async def create_domain(self, command: CreateDomainCommand) -> dict:
        node_id = generate_catalog_id("domain", command.slug, scope=command.project_id)
        node = DomainNode(
            id=node_id,
            slug=command.slug,
            name=command.name,
            description=command.description,
            status=command.status,
            aliases=command.aliases,
            tags=command.tags,
            project_id=command.project_id,
        )
        await self.neo4j.upsert_domain_node(node)
        return node.model_dump(mode="json")

    async def update_domain(self, command: UpdateDomainCommand) -> dict:
        node = DomainNode(
            id=command.id,
            slug=command.slug,
            name=command.name,
            description=command.description,
            status=command.status,
            aliases=command.aliases,
            tags=command.tags,
            project_id=command.project_id,
        )
        await self.neo4j.upsert_domain_node(node)
        return node.model_dump(mode="json")

    async def list_domains(self) -> list[dict]:
        return await self.neo4j.list_domain_nodes()

    async def get_domain(self, identifier: str) -> dict | None:
        return self._find_node(await self.list_domains(), identifier)

    async def delete_domain(self, identifier: str) -> None:
        await self.neo4j.delete_catalog_node(node_id=identifier, kind="domain")

    @staticmethod
    def _find_node(rows: list[dict], identifier: str) -> dict | None:
        needle = identifier.strip()
        for row in rows:
            if any(row.get(field) == needle for field in ("id", "slug")):
                return row
        return None
