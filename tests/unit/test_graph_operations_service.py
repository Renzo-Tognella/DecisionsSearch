from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from decisionssearch.domain import CreateRelationCommand, DeleteRelationCommand
from decisionssearch.application.catalog.graph_operations_service import GraphOperationsService


@dataclass
class FakeNeo4j:
    create_calls: list[dict] = field(default_factory=list)
    delete_calls: list[dict] = field(default_factory=list)
    allowed_relations: list[str] = field(
        default_factory=lambda: [
            "CONFLICTS_WITH",
            "DEPRECATES",
            "DEPENDS_ON",
            "EVOLVES_FROM",
            "HAS_CATEGORY",
            "HAS_DOMAIN",
            "RELATED_TO",
            "REFINES",
        ]
    )
    projects: list[dict] = field(default_factory=list)
    categories: list[dict] = field(default_factory=list)
    domains: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)

    async def create_catalog_relation(
        self,
        source_id: str,
        source_kind: str,
        relation_type: str,
        target_id: str,
        target_kind: str,
        rationale: str = "",
    ) -> None:
        self.create_calls.append(
            {
                "source_id": source_id,
                "source_kind": source_kind,
                "relation_type": relation_type,
                "target_id": target_id,
                "target_kind": target_kind,
                "rationale": rationale,
            }
        )

    async def delete_catalog_relation(
        self,
        source_id: str,
        source_kind: str,
        relation_type: str,
        target_id: str,
        target_kind: str,
    ) -> None:
        self.delete_calls.append(
            {
                "source_id": source_id,
                "source_kind": source_kind,
                "relation_type": relation_type,
                "target_id": target_id,
                "target_kind": target_kind,
            }
        )

    async def list_allowed_relations(self) -> list[str]:
        return list(self.allowed_relations)

    async def list_catalog_relations(self) -> list[dict]:
        return list(self.relations)

    async def list_project_nodes(self) -> list[dict]:
        return list(self.projects)

    async def list_category_nodes(self) -> list[dict]:
        return list(self.categories)

    async def list_domain_nodes(self) -> list[dict]:
        return list(self.domains)


def test_relation_operations_delegate_to_neo4j() -> None:
    neo4j = FakeNeo4j()
    service = GraphOperationsService(neo4j=neo4j)

    asyncio.run(
        service.create_relation(
            CreateRelationCommand(
                source_id="proj-1",
                source_kind="project",
                relation_type="RELATED_TO",
                target_id="cat-1",
                target_kind="category",
                rationale="link",
            )
        )
    )
    asyncio.run(
        service.delete_relation(
            DeleteRelationCommand(
                source_id="proj-1",
                source_kind="project",
                relation_type="RELATED_TO",
                target_id="cat-1",
                target_kind="category",
            )
        )
    )

    assert neo4j.create_calls == [
        {
            "source_id": "proj-1",
            "source_kind": "project",
            "relation_type": "RELATED_TO",
            "target_id": "cat-1",
            "target_kind": "category",
            "rationale": "link",
        }
    ]
    assert neo4j.delete_calls == [
        {
            "source_id": "proj-1",
            "source_kind": "project",
            "relation_type": "RELATED_TO",
            "target_id": "cat-1",
            "target_kind": "category",
        }
    ]


def test_allowed_relations_and_catalog_summary_use_neo4j_snapshot() -> None:
    neo4j = FakeNeo4j(
        projects=[
            {"id": "proj-1", "slug": "core-platform", "name": "Core Platform"},
            {"id": "proj-2", "slug": "ops-platform", "name": "Ops Platform"},
        ],
        categories=[{"id": "cat-1", "slug": "design-rule", "name": "Design Rule"}],
        domains=[{"id": "dom-1", "slug": "billing", "name": "Billing"}],
        relations=[
            {
                "source_id": "proj-1",
                "source_kind": "project",
                "relation_type": "HAS_CATEGORY",
                "target_id": "cat-1",
                "target_kind": "category",
                "rationale": "seed",
            }
        ],
    )
    service = GraphOperationsService(neo4j=neo4j)

    assert asyncio.run(service.list_allowed_relations()) == neo4j.allowed_relations
    assert asyncio.run(service.list_relations()) == neo4j.relations

    summary = asyncio.run(service.catalog_summary())

    assert summary == {
        "projects": {
            "count": 2,
            "items": neo4j.projects,
        },
        "categories": {
            "count": 1,
            "items": neo4j.categories,
        },
        "domains": {
            "count": 1,
            "items": neo4j.domains,
        },
        "relations": {
            "count": 1,
            "items": neo4j.relations,
        },
        "allowed_relations": neo4j.allowed_relations,
    }
