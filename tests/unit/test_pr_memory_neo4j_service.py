from __future__ import annotations

from dataclasses import dataclass, field

from decisionssearch.domain import PRMemory
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService


@dataclass
class FakeRecord:
    payload: dict

    def __getitem__(self, key):  # noqa: ANN001, ANN201
        return self.payload[key]

    def data(self):  # noqa: ANN201
        return dict(self.payload)


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


@dataclass
class FakePRGraph:
    pr_nodes: list[dict] = field(default_factory=list)
    area_links: list[tuple[str, str]] = field(default_factory=list)

    def upsert_pr(self, payload: dict) -> None:
        self.pr_nodes = [node for node in self.pr_nodes if node["memory_id"] != payload["memory_id"]]
        self.pr_nodes.append(dict(payload))

    def add_area_link(self, memory_id: str, area: str) -> None:
        link = (memory_id, area)
        if link not in self.area_links:
            self.area_links.append(link)

    def query_prs(
        self,
        *,
        project: str,
        repo: str | None = None,
        pr_number: int | None = None,
        changed_file_contains: str | None = None,
    ) -> list[dict]:
        rows = [node for node in self.pr_nodes if node["project"] == project]
        if repo is not None:
            rows = [node for node in rows if node["repo"] == repo]
        if pr_number is not None:
            rows = [node for node in rows if node["pr_number"] == pr_number]
        if changed_file_contains is not None:
            rows = [
                node
                for node in rows
                if any(changed_file_contains in path for path in node["changed_files"])
            ]
        rows.sort(key=lambda node: node["pr_number"], reverse=True)
        return [{"pr": row} for row in rows]

    def related_candidates(
        self,
        *,
        project: str,
        memory_id: str,
        changed_files: list[str],
        areas: list[str],
        limit: int,
    ) -> list[dict]:
        rows: list[dict] = []
        for node in self.pr_nodes:
            if node["project"] != project or node["memory_id"] == memory_id:
                continue
            overlapping_files = [path for path in node.get("changed_files", []) if path in changed_files]
            overlapping_areas = [area for area in node.get("areas", []) if area in areas]
            if not overlapping_files and not overlapping_areas:
                continue
            reason = (
                f"shared files: {overlapping_files[0]}; shared area: {overlapping_areas[0]}"
                if overlapping_files and overlapping_areas
                else (
                    f"shared file: {overlapping_files[0]}"
                    if overlapping_files
                    else f"shared area: {overlapping_areas[0]}"
                )
            )
            score = (len(overlapping_files) * 3) + len(overlapping_areas)
            rows.append(
                {
                    "memory_id": node["memory_id"],
                    "repo": node["repo"],
                    "pr_number": node["pr_number"],
                    "title": node["title"],
                    "reason": reason,
                    "relation_type": "RELATED_TO",
                    "score": score,
                }
            )
        rows.sort(key=lambda row: (-row["score"], -row["pr_number"]))
        return rows[:limit]


class FakeSession:
    def __init__(self, graph: FakePRGraph):
        self.graph = graph
        self.calls: list[tuple[str, dict]] = []

    async def run(self, query, **params):  # noqa: ANN001
        normalized = " ".join(query.split())
        self.calls.append((normalized, params))

        if "MERGE (m:PRMemory {memory_id: $memory_id})" in normalized:
            self.graph.upsert_pr(params)
            return FakeResult([])

        if "MERGE (a:Area {name: $area})" in normalized and "MERGE (m)-[:TOUCHES_AREA]->(a)" in normalized:
            self.graph.add_area_link(params["memory_id"], params["area"])
            return FakeResult([])

        if "MATCH (m:PRMemory)" in normalized and "RETURN m { .* } AS pr" in normalized:
            return FakeResult(
                self.graph.query_prs(
                    project=params["project"],
                    repo=params["repo"],
                    pr_number=params["pr_number"],
                    changed_file_contains=params["changed_file_contains"],
                )
            )

        if "MATCH (m:PRMemory)" in normalized and "m.memory_id AS memory_id" in normalized:
            return FakeResult(
                self.graph.related_candidates(
                    project=params["project"],
                    memory_id=params["memory_id"],
                    changed_files=params["changed_files"],
                    areas=params["areas"],
                    limit=params["limit"],
                )
            )

        raise AssertionError(f"Unexpected query: {normalized}")


class FakeSessionContext:
    def __init__(self, session: FakeSession):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeDriver:
    def __init__(self, graph: FakePRGraph | None = None):
        self.graph = graph or FakePRGraph()
        self.session_instance = FakeSession(self.graph)

    def session(self):
        return FakeSessionContext(self.session_instance)

    async def close(self):
        return None


def _patch_driver(monkeypatch, driver: FakeDriver) -> None:
    monkeypatch.setattr("decisionssearch.infrastructure.persistence.neo4j.neo4j_service.AsyncGraphDatabase.driver", lambda *a, **k: driver)


def test_upsert_pr_memory_persists_node_and_area_links(monkeypatch) -> None:
    fake_driver = FakeDriver()
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    memory = PRMemory(
        memory_id="pr-memory-14",
        project="EXAMPLE_PROJECT",
        repo="ExampleProject",
        pr_number=14,
        title="feat: sync emails via LLM and upsert proposals",
        summary="Implements sync and upsert flow.",
        changed_files=["app/services/email/sync_service.rb", "config/routes.rb"],
        areas=["backend", "email"],
        pr_url="https://github.com/org/repo/pull/14",
        work_item_url="https://company.atlassian.net/browse/ENG-14",
        status="merged",
    )

    asyncio.run(service.upsert_pr_memory(memory))

    assert fake_driver.graph.pr_nodes[0]["repo"] == "ExampleProject"
    assert fake_driver.graph.pr_nodes[0]["pr_number"] == 14
    assert ("pr-memory-14", "backend") in fake_driver.graph.area_links
    assert ("pr-memory-14", "email") in fake_driver.graph.area_links
    assert any("PRMemory" in query for query, _ in fake_driver.session_instance.calls)
    assert any("TOUCHES_AREA" in query for query, _ in fake_driver.session_instance.calls)


def test_query_pr_memory_by_identity_returns_rows(monkeypatch) -> None:
    graph = FakePRGraph(
        pr_nodes=[
            {
                "memory_id": "pr-memory-14",
                "project": "EXAMPLE_PROJECT",
                "repo": "ExampleProject",
                "pr_number": 14,
                "title": "feat: sync emails via LLM and upsert proposals",
                "summary": "Implements sync and upsert flow.",
                "changed_files": ["app/services/email/sync_service.rb", "config/routes.rb"],
                "areas": ["backend", "email"],
                "touches_frontend": False,
                "touches_backend": True,
            }
        ]
    )
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    rows = asyncio.run(
        service.query_pr_memories(
            project="EXAMPLE_PROJECT",
            repo="ExampleProject",
            pr_number=14,
        )
    )

    assert rows[0]["repo"] == "ExampleProject"
    assert rows[0]["pr_number"] == 14


def test_find_related_pr_candidates_returns_ranked_matches(monkeypatch) -> None:
    graph = FakePRGraph(
        pr_nodes=[
            {
                "memory_id": "pr-memory-14",
                "project": "EXAMPLE_PROJECT",
                "repo": "ExampleProject",
                "pr_number": 14,
                "title": "feat: sync emails via LLM and upsert proposals",
                "summary": "Implements sync and upsert flow.",
                "changed_files": ["app/models/company.rb", "app/services/email/sync_service.rb"],
                "areas": ["backend", "email"],
            },
            {
                "memory_id": "pr-memory-99",
                "project": "EXAMPLE_PROJECT",
                "repo": "ExampleDashboard",
                "pr_number": 2,
                "title": "fix: align proposal workflow contracts",
                "summary": "Frontend follow-up.",
                "changed_files": ["lib/api.ts"],
                "areas": ["frontend", "email"],
            },
            {
                "memory_id": "pr-memory-23",
                "project": "EXAMPLE_PROJECT",
                "repo": "ExampleProject",
                "pr_number": 23,
                "title": "feat(api): normalize proposal services and email sync",
                "summary": "Catalog updates.",
                "changed_files": ["app/models/company.rb", "app/services/email/ingest_messages_service.rb"],
                "areas": ["backend", "email", "catalog"],
            },
        ]
    )
    fake_driver = FakeDriver(graph=graph)
    _patch_driver(monkeypatch, fake_driver)
    service = Neo4jService()

    import asyncio

    rows = asyncio.run(
        service.find_related_pr_candidates(
            PRMemory(
                memory_id="pr-memory-14",
                project="EXAMPLE_PROJECT",
                repo="ExampleProject",
                pr_number=14,
                title="feat: sync emails via LLM and upsert proposals",
                summary="Implements sync and upsert flow.",
                changed_files=["app/models/company.rb", "app/services/email/sync_service.rb"],
                areas=["backend", "email"],
                pr_url="https://github.com/org/repo/pull/14",
                work_item_url="https://company.atlassian.net/browse/ENG-14",
            )
        )
    )

    assert rows[0]["repo"] == "ExampleProject"
    assert rows[0]["pr_number"] == 23
    assert rows[0]["score"] >= rows[1]["score"]
