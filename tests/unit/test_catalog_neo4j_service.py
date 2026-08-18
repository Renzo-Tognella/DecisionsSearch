from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from decisionssearch.domain import CategoryNode, DomainNode, MemoryServiceError, ProjectNode
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService


@dataclass
class FakeRecord:
    payload: dict

    def data(self) -> dict:
        return self.payload

    def get(self, key, default=None):  # noqa: ANN001,ANN201
        return self.payload.get(key, default)

    def __getitem__(self, key):  # noqa: ANN001,ANN201
        return self.payload[key]


class FakeResult:
    def __init__(self, rows: list[dict] | None = None):
        self.rows = rows or []

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self.rows):
            raise StopAsyncIteration
        row = FakeRecord(self.rows[self._index])
        self._index += 1
        return row

    async def single(self):
        if not self.rows:
            return None
        return FakeRecord(self.rows[0])


@dataclass
class FakeGraph:
    nodes: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)

    def add_node(self, label: str, **props) -> dict:
        node = {"label": label, "aliases": [], "tags": [], "status": "active", **props}
        self.nodes.append(node)
        return node

    def add_relation(
        self,
        source_label: str,
        source_identity: str,
        relation_type: str,
        target_label: str,
        target_identity: str,
        rationale: str = "",
    ) -> bool:
        source = self.find_node(source_label, source_identity)
        target = self.find_node(target_label, target_identity)
        if not source or not target:
            return False

        relation = {
            "source_label": source_label,
            "source_identity": source_identity,
            "target_label": target_label,
            "target_identity": target_identity,
            "type": relation_type,
            "rationale": rationale,
        }
        if relation not in self.relations:
            self.relations.append(relation)
        return True

    def delete_relation(
        self,
        source_label: str,
        source_identity: str,
        relation_type: str,
        target_label: str,
        target_identity: str,
    ) -> bool:
        before = len(self.relations)
        self.relations = [
            relation
            for relation in self.relations
            if not (
                relation["source_label"] == source_label
                and relation["source_identity"] == source_identity
                and relation["type"] == relation_type
                and relation["target_label"] == target_label
                and relation["target_identity"] == target_identity
            )
        ]
        return len(self.relations) != before

    def find_node(self, label: str, identity: str) -> dict | None:
        for node in self.nodes:
            if node["label"] != label:
                continue
            if identity in {node.get("id"), node.get("name"), node.get("slug"), node.get("memory_id")}:
                return node
        return None

    def identity_row(self, node: dict) -> dict:
        row = {
            "id": node.get("id"),
            "slug": node.get("slug"),
            "name": node.get("name"),
            "description": node.get("description", ""),
            "status": node.get("status", "active"),
            "aliases": list(node.get("aliases", [])),
            "tags": list(node.get("tags", [])),
        }
        if node["label"] != "Project":
            row["project_id"] = node.get("project_id")
        return row

    def list_nodes(self, label: str) -> list[dict]:
        nodes = [node for node in self.nodes if node["label"] == label]
        nodes.sort(key=lambda node: node.get("name") or node.get("slug") or node.get("id") or "")
        return [self.identity_row(node) for node in nodes]

    def resolve(self, label: str, identity: str) -> dict | None:
        node = self.find_node(label, identity)
        return self.identity_row(node) if node else None

    def resolve_any(self, label: str, identities: tuple[str | None, ...]) -> dict | None:
        for identity in identities:
            if not identity:
                continue
            node = self.find_node(label, identity)
            if node:
                return self.identity_row(node)
        return None

    def upsert_node(self, label: str, params: dict) -> dict:
        identity = params["identity_id"]
        node = self.find_node(label, identity) or self.find_node(label, params["identity_name"]) or self.find_node(label, params["identity_slug"])
        if not node:
            node = self.add_node(
                label,
                id=None,
                slug=None,
                name=params["name"],
                description="",
                aliases=[],
                tags=[],
            )

        node["id"] = params["identity_id"]
        node["slug"] = params["identity_slug"]
        node["name"] = params.get("name", node.get("name"))
        node["description"] = params.get("description", "")
        node["status"] = params.get("status", "active")
        node["aliases"] = list(params.get("aliases", []))
        node["tags"] = list(params.get("tags", []))
        if "project_id" in params:
            node["project_id"] = params["project_id"]
        return node

    def update_project_link(self, source_identity: str, relation_type: str, target_identity: str) -> bool:
        return self.add_relation(
            "Project",
            source_identity,
            relation_type,
            "Category" if relation_type == "HAS_CATEGORY" else "Domain",
            target_identity,
        )

    def node_relation_types(self, label: str, identity: str) -> tuple[list[str], int]:
        relation_types: set[str] = set()
        memory_edges = 0
        for relation in self.relations:
            source = self.find_node(relation["source_label"], relation["source_identity"])
            target = self.find_node(relation["target_label"], relation["target_identity"])
            if not source or not target:
                continue
            node = self.find_node(label, identity)
            if not node:
                continue
            involved = source is node or target is node
            if not involved:
                continue
            relation_types.add(relation["type"])
            other = target if source is node else source
            if other["label"] == "MemoryItem":
                memory_edges += 1
        return sorted(relation_types), memory_edges

    def delete_node(self, label: str, identity: str) -> bool:
        node = self.find_node(label, identity)
        if not node:
            return False
        self.nodes = [candidate for candidate in self.nodes if candidate is not node]
        self.relations = [
            relation
            for relation in self.relations
            if not (
                (relation["source_label"] == label and relation["source_identity"] == identity)
                or (relation["target_label"] == label and relation["target_identity"] == identity)
            )
        ]
        return True


class FakeSession:
    def __init__(self, graph: FakeGraph, should_fail: bool = False):
        self.graph = graph
        self.should_fail = should_fail
        self.calls: list[tuple[str, dict]] = []

    async def run(self, query, **params):  # noqa: ANN001
        if self.should_fail:
            raise RuntimeError("neo4j down")

        normalized = " ".join(query.split())
        self.calls.append((normalized, params))

        if "MATCH (p:Project)" in normalized and "RETURN p.id AS id" in normalized and "SET" not in normalized and "MERGE" not in normalized:
            return FakeResult(self.graph.list_nodes("Project"))

        if "MATCH (c:Category)" in normalized and "RETURN c.id AS id" in normalized and "SET" not in normalized and "MERGE" not in normalized:
            return FakeResult(self.graph.list_nodes("Category"))

        if "MATCH (d:Domain)" in normalized and "RETURN d.id AS id" in normalized and "SET" not in normalized and "MERGE" not in normalized:
            return FakeResult(self.graph.list_nodes("Domain"))

        if "collect(DISTINCT type(r)) AS relation_types" in normalized:
            label = "Project" if "MATCH (n:Project)" in normalized else "Category" if "MATCH (n:Category)" in normalized else "Domain"
            identity = params["node_id"]
            relation_types, memory_edges = self.graph.node_relation_types(label, identity)
            allowed = set(params.get("allowed_relations", []))
            if memory_edges:
                return FakeResult([])
            if any(relation_type not in allowed for relation_type in relation_types):
                return FakeResult([])
            node = self.graph.find_node(label, identity)
            if not node:
                return FakeResult([])
            if self.graph.delete_node(label, identity):
                return FakeResult([{"deleted": 1}])
            return FakeResult([])

        if "DETACH DELETE n" in normalized and "RETURN 1 AS deleted" in normalized:
            label = "Project" if "MATCH (n:Project)" in normalized else "Category" if "MATCH (n:Category)" in normalized else "Domain"
            if self.graph.delete_node(label, params["node_id"]):
                return FakeResult([{"deleted": 1}])
            return FakeResult([])

        if "MERGE (a)-[r:`" in normalized:
            relation_type = params["relation_type"]
            source_label = "Project" if "MATCH (a:Project)" in normalized else "Category" if "MATCH (a:Category)" in normalized else "Domain"
            target_label = "Project" if "MATCH (b:Project)" in normalized else "Category" if "MATCH (b:Category)" in normalized else "Domain"
            source_identity = params["source_identity"]
            target_identity = params["target_identity"]
            if self.graph.add_relation(source_label, source_identity, relation_type, target_label, target_identity, params.get("rationale", "")):
                return FakeResult([{"created": 1}])
            return FakeResult([])

        if "MATCH (a)-[r:`" in normalized and "DELETE r" in normalized:
            relation_type = params["relation_type"]
            source_label = "Project" if "MATCH (a:Project)" in normalized else "Category" if "MATCH (a:Category)" in normalized else "Domain"
            target_label = "Project" if "MATCH (b:Project)" in normalized else "Category" if "MATCH (b:Category)" in normalized else "Domain"
            if self.graph.delete_relation(source_label, params["source_identity"], relation_type, target_label, params["target_identity"]):
                return FakeResult([{"deleted": 1}])
            return FakeResult([])

        if "MATCH (n:Project)" in normalized and "WHERE n.id = $identity_id OR n.name = $identity_name OR n.slug = $identity_slug" in normalized and "LIMIT 1" in normalized:
            resolved = self.graph.resolve_any(
                "Project",
                (params["identity_id"], params["identity_name"], params["identity_slug"]),
            )
            return FakeResult([resolved] if resolved else [])

        if "MATCH (n:Category)" in normalized and "WHERE n.id = $identity_id OR n.name = $identity_name OR n.slug = $identity_slug" in normalized and "LIMIT 1" in normalized:
            resolved = self.graph.resolve_any(
                "Category",
                (params["identity_id"], params["identity_name"], params["identity_slug"]),
            )
            return FakeResult([resolved] if resolved else [])

        if "MATCH (n:Domain)" in normalized and "WHERE n.id = $identity_id OR n.name = $identity_name OR n.slug = $identity_slug" in normalized and "LIMIT 1" in normalized:
            resolved = self.graph.resolve_any(
                "Domain",
                (params["identity_id"], params["identity_name"], params["identity_slug"]),
            )
            return FakeResult([resolved] if resolved else [])

        if "MATCH (n:Project)" in normalized and "SET n.id = coalesce(n.id, $identity_id)" in normalized:
            node = self.graph.upsert_node("Project", params)
            return FakeResult([self.graph.identity_row(node)])

        if "MATCH (n:Category)" in normalized and "SET n.id = coalesce(n.id, $identity_id)" in normalized:
            node = self.graph.upsert_node("Category", params)
            return FakeResult([self.graph.identity_row(node)])

        if "MATCH (n:Domain)" in normalized and "SET n.id = coalesce(n.id, $identity_id)" in normalized:
            node = self.graph.upsert_node("Domain", params)
            return FakeResult([self.graph.identity_row(node)])

        if "MERGE (n:Project {name: $name})" in normalized:
            node = self.graph.upsert_node("Project", params)
            return FakeResult([self.graph.identity_row(node)])

        if "MERGE (n:Category {name: $name})" in normalized:
            node = self.graph.upsert_node("Category", params)
            return FakeResult([self.graph.identity_row(node)])

        if "MERGE (n:Domain {name: $name})" in normalized:
            node = self.graph.upsert_node("Domain", params)
            return FakeResult([self.graph.identity_row(node)])

        if "MERGE (p)-[:HAS_CATEGORY]->(c)" in normalized:
            if self.graph.add_relation(
                "Project",
                params["project_identity"],
                "HAS_CATEGORY",
                "Category",
                params["category_id"],
            ):
                return FakeResult([{"linked": 1}])
            return FakeResult([])

        if "MERGE (p)-[:HAS_DOMAIN]->(d)" in normalized:
            if self.graph.add_relation(
                "Project",
                params["project_identity"],
                "HAS_DOMAIN",
                "Domain",
                params["domain_id"],
            ):
                return FakeResult([{"linked": 1}])
            return FakeResult([])

        raise AssertionError(f"Unexpected query: {normalized}")


class FakeSessionContext:
    def __init__(self, session: FakeSession):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeDriver:
    def __init__(self, graph: FakeGraph | None = None, should_fail: bool = False):
        self.graph = graph or FakeGraph()
        self.session_instance = FakeSession(self.graph, should_fail=should_fail)

    def session(self):
        return FakeSessionContext(self.session_instance)

    async def close(self):
        return None


def _patch_driver(monkeypatch, driver: FakeDriver) -> None:
    monkeypatch.setattr("decisionssearch.infrastructure.persistence.neo4j.neo4j_service.AsyncGraphDatabase.driver", lambda *a, **k: driver)


def test_upsert_project_node_reuses_legacy_project_node_without_duplication(monkeypatch) -> None:
    graph = FakeGraph()
    graph.add_node("Project", name="Core Platform", description="Legacy project")
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    asyncio.run(
        service.upsert_project_node(
            ProjectNode(
                id="proj-1",
                slug="core-platform",
                name="Core Platform",
                description="Main project",
                aliases=["Core", "Core Platform"],
                tags=["Platform"],
            )
        )
    )

    assert len([node for node in graph.nodes if node["label"] == "Project"]) == 1
    project = graph.find_node("Project", "Core Platform")
    assert project["id"] == "proj-1"
    assert project["slug"] == "core-platform"
    assert project["description"] == "Main project"
    assert project["aliases"] == ["Core", "Core Platform"]
    assert project["tags"] == ["Platform"]
    assert not any("MERGE (n:Project {name: $name})" in query for query, _ in fake_driver.session_instance.calls)


def test_list_project_nodes_returns_flat_entities(monkeypatch) -> None:
    graph = FakeGraph()
    graph.add_node("Project", id="proj-1", slug="core-platform", name="Core Platform", description="Main", aliases=["Core"], tags=["Platform"])
    graph.add_node("Project", id="proj-2", slug="ops-platform", name="Ops Platform", description="Ops", aliases=[], tags=[])
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    result = asyncio.run(service.list_project_nodes())

    assert result == [
        {
            "id": "proj-1",
            "slug": "core-platform",
            "name": "Core Platform",
            "description": "Main",
            "status": "active",
            "aliases": ["Core"],
            "tags": ["Platform"],
        },
        {
            "id": "proj-2",
            "slug": "ops-platform",
            "name": "Ops Platform",
            "description": "Ops",
            "status": "active",
            "aliases": [],
            "tags": [],
        },
    ]


@pytest.mark.parametrize(
    "label,method_name,expected",
    [
        (
            "Category",
            "list_category_nodes",
            [
                {
                    "id": "cat-1",
                    "slug": "design-rule",
                    "name": "Design Rule",
                    "description": "Rule",
                    "status": "active",
                    "aliases": ["Rule"],
                    "tags": ["architecture"],
                    "project_id": "proj-1",
                }
            ],
        ),
        (
            "Domain",
            "list_domain_nodes",
            [
                {
                    "id": "dom-1",
                    "slug": "billing",
                    "name": "Billing",
                    "description": "Domain",
                    "status": "active",
                    "aliases": ["Finance"],
                    "tags": [],
                    "project_id": "proj-1",
                }
            ],
        ),
    ],
)
def test_scoped_listings_return_flat_entities(label, method_name, expected, monkeypatch) -> None:
    graph = FakeGraph()
    graph.add_node("Project", id="proj-1", slug="core-platform", name="Core Platform")
    graph.add_node(label, **expected[0])
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    result = asyncio.run(getattr(service, method_name)())

    assert result == expected


@pytest.mark.parametrize("factory", [CategoryNode, DomainNode])
def test_scoped_nodes_require_existing_parent_and_do_not_create_placeholder_projects(factory, monkeypatch) -> None:
    graph = FakeGraph()
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    node = factory(
        id="node-1",
        slug="design-node",
        name="Design Node",
        project_id="proj-1",
        aliases=["Node"],
        tags=["architecture"],
    )

    import asyncio

    with pytest.raises(MemoryServiceError):
        asyncio.run(
            service.upsert_category_node(node) if isinstance(node, CategoryNode) else service.upsert_domain_node(node)
        )

    assert graph.nodes == []
    assert graph.relations == []


def test_create_catalog_relation_fails_when_target_is_missing(monkeypatch) -> None:
    graph = FakeGraph()
    graph.add_node("Project", id="proj-1", slug="core-platform", name="Core Platform")
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    with pytest.raises(MemoryServiceError):
        asyncio.run(
            service.create_catalog_relation(
                source_id="proj-1",
                source_kind="project",
                relation_type="RELATED_TO",
                target_id="cat-1",
                target_kind="category",
                rationale="link",
            )
        )

    assert graph.relations == []
    assert len(fake_driver.session_instance.calls) == 1


def test_create_catalog_relation_succeeds_when_endpoints_exist(monkeypatch) -> None:
    graph = FakeGraph()
    graph.add_node("Project", id="proj-1", slug="core-platform", name="Core Platform")
    graph.add_node("Category", id="cat-1", slug="design-rule", name="Design Rule")
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    asyncio.run(
        service.create_catalog_relation(
            source_id="proj-1",
            source_kind="project",
            relation_type="RELATED_TO",
            target_id="cat-1",
            target_kind="category",
            rationale="link",
        )
    )

    assert graph.relations == [
        {
            "source_label": "Project",
            "source_identity": "proj-1",
            "target_label": "Category",
            "target_identity": "cat-1",
            "type": "RELATED_TO",
            "rationale": "link",
        }
    ]


def test_delete_catalog_relation_fails_when_relation_is_missing(monkeypatch) -> None:
    graph = FakeGraph()
    graph.add_node("Project", id="proj-1", slug="core-platform", name="Core Platform")
    graph.add_node("Category", id="cat-1", slug="design-rule", name="Design Rule")
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    with pytest.raises(MemoryServiceError):
        asyncio.run(
            service.delete_catalog_relation(
                source_id="proj-1",
                source_kind="project",
                relation_type="RELATED_TO",
                target_id="cat-1",
                target_kind="category",
            )
        )

    assert graph.relations == []
    assert len(fake_driver.session_instance.calls) == 1


def test_delete_catalog_node_refuses_memoryitem_links(monkeypatch) -> None:
    graph = FakeGraph()
    graph.add_node("Project", id="proj-1", slug="core-platform", name="Core Platform")
    graph.add_node("MemoryItem", memory_id="m1", name="Memory")
    graph.add_relation("Project", "proj-1", "RELATED_TO", "MemoryItem", "m1")
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    with pytest.raises(MemoryServiceError):
        asyncio.run(service.delete_catalog_node("proj-1", "project"))

    assert graph.find_node("Project", "proj-1") is not None
    assert len(fake_driver.session_instance.calls) == 1


def test_delete_catalog_node_allows_structural_only_subgraph(monkeypatch) -> None:
    graph = FakeGraph()
    graph.add_node("Project", id="proj-1", slug="core-platform", name="Core Platform")
    graph.add_node("Category", id="cat-1", slug="design-rule", name="Design Rule")
    graph.add_relation("Project", "proj-1", "HAS_CATEGORY", "Category", "cat-1")
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    asyncio.run(service.delete_catalog_node("proj-1", "project"))

    assert graph.find_node("Project", "proj-1") is None
    assert graph.find_node("Category", "cat-1") is not None
    assert graph.relations == []


def test_catalog_relation_whitelist_is_exposed(monkeypatch) -> None:
    fake_driver = FakeDriver(graph=FakeGraph())
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    relations = asyncio.run(service.list_allowed_relations())

    assert relations == sorted(
        [
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
