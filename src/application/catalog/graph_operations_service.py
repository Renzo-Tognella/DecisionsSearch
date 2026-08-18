from __future__ import annotations

from decisionssearch.domain import CreateRelationCommand, DeleteRelationCommand
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService


class GraphOperationsService:
    """Operacoes relacionais e snapshot do catalogo."""

    def __init__(self, neo4j: Neo4jService):
        self.neo4j = neo4j

    async def create_relation(self, command: CreateRelationCommand) -> None:
        await self.neo4j.create_catalog_relation(
            source_id=command.source_id,
            source_kind=command.source_kind,
            relation_type=command.relation_type,
            target_id=command.target_id,
            target_kind=command.target_kind,
            rationale=command.rationale,
        )

    async def delete_relation(self, command: DeleteRelationCommand) -> None:
        await self.neo4j.delete_catalog_relation(
            source_id=command.source_id,
            source_kind=command.source_kind,
            relation_type=command.relation_type,
            target_id=command.target_id,
            target_kind=command.target_kind,
        )

    async def list_allowed_relations(self) -> list[str]:
        return await self.neo4j.list_allowed_relations()

    async def list_relations(self) -> list[dict]:
        return await self.neo4j.list_catalog_relations()

    async def catalog_summary(self) -> dict:
        projects = await self.neo4j.list_project_nodes()
        categories = await self.neo4j.list_category_nodes()
        domains = await self.neo4j.list_domain_nodes()
        allowed_relations = await self.list_allowed_relations()
        relations = await self.list_relations()

        return {
            "projects": {"count": len(projects), "items": projects},
            "categories": {"count": len(categories), "items": categories},
            "domains": {"count": len(domains), "items": domains},
            "relations": {"count": len(relations), "items": relations},
            "allowed_relations": allowed_relations,
        }
