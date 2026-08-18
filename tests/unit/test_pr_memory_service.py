from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from decisionssearch.domain import CreatePRMemoryCommand, PRMemory
from decisionssearch.application.pr_memory.pr_memory_service import PRMemoryService


@dataclass
class FakeNeo4j:
    upsert_calls: list[PRMemory] = field(default_factory=list)
    query_calls: list[dict] = field(default_factory=list)
    query_results: list[dict] = field(default_factory=list)
    related_results: list[dict] = field(default_factory=list)

    async def upsert_pr_memory(self, memory: PRMemory) -> None:
        self.upsert_calls.append(memory)

    async def query_pr_memories(
        self,
        *,
        project: str,
        repo: str | None = None,
        pr_number: int | None = None,
        changed_file_contains: str | None = None,
    ) -> list[dict]:
        self.query_calls.append(
            {
                "project": project,
                "repo": repo,
                "pr_number": pr_number,
                "changed_file_contains": changed_file_contains,
            }
        )
        return list(self.query_results)

    async def find_related_pr_candidates(self, memory: PRMemory, limit: int = 3) -> list[dict]:
        return list(self.related_results[:limit])


def test_create_pr_memory_generates_stable_memory_id() -> None:
    neo4j = FakeNeo4j(
        related_results=[
            {
                "memory_id": "pr-memory-12",
                "repo": "ExampleDashboard",
                "pr_number": 2,
                "title": "fix: align proposal workflow contracts",
                "reason": "shared area: proposals",
                "relation_type": "RELATED_TO",
                "score": 1,
            }
        ]
    )
    service = PRMemoryService(neo4j=neo4j)

    created = asyncio.run(
        service.create_pr_memory(
            CreatePRMemoryCommand(
                project="EXAMPLE_PROJECT",
                repo="ExampleProject",
                pr_number=14,
                title="feat: sync emails via LLM and upsert proposals",
                summary="Implements sync and upsert flow.",
                changed_files=["app/services/email/sync_service.rb"],
                areas=["backend"],
                pr_url="https://github.com/org/repo/pull/14",
                work_item_url="https://company.atlassian.net/browse/ENG-14",
            )
        )
    )

    assert created["memory_id"]
    assert created["repo"] == "ExampleProject"
    assert created["touches_backend"] is True
    assert created["related_pr_candidates"][0]["repo"] == "ExampleDashboard"
    assert neo4j.upsert_calls[0].memory_id == created["memory_id"]


def test_query_pr_memory_delegates_to_neo4j() -> None:
    neo4j = FakeNeo4j(
        query_results=[
            {
                "memory_id": "pr-memory-14",
                "project": "EXAMPLE_PROJECT",
                "repo": "ExampleProject",
                "pr_number": 14,
                "title": "feat: sync emails via LLM and upsert proposals",
                "summary": "Implements sync and upsert flow.",
                "changed_files": ["app/services/email/sync_service.rb"],
                "areas": ["backend"],
                "touches_frontend": False,
                "touches_backend": True,
            }
        ]
    )
    service = PRMemoryService(neo4j=neo4j)

    rows = asyncio.run(service.query_pr_memories(project="EXAMPLE_PROJECT", repo="ExampleProject"))

    assert rows == neo4j.query_results
    assert neo4j.query_calls[0] == {
        "project": "EXAMPLE_PROJECT",
        "repo": "ExampleProject",
        "pr_number": None,
        "changed_file_contains": None,
    }
