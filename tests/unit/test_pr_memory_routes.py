from __future__ import annotations

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from decisionssearch.domain import CreatePRMemoryCommand
from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.interfaces.http.http_app import create_http_app


@dataclass
class FakePRMemoryService:
    create_calls: list[CreatePRMemoryCommand] = field(default_factory=list)
    query_calls: list[dict] = field(default_factory=list)
    next_error: Exception | None = None

    async def create_pr_memory(self, command: CreatePRMemoryCommand) -> dict:
        self.create_calls.append(command)
        if self.next_error is not None:
            raise self.next_error
        return {
            "memory_id": "pr-memory-14",
            "project": command.project,
            "repo": command.repo,
            "pr_number": command.pr_number,
            "title": command.title,
            "summary": command.summary,
            "changed_files": command.changed_files,
            "pr_url": command.pr_url,
            "work_item_url": command.work_item_url,
            "work_item_summary": command.work_item_summary,
            "event_date": command.event_date,
            "areas": command.areas,
            "touches_frontend": "frontend" in command.areas,
            "touches_backend": "backend" in command.areas,
            "related_pr_candidates": [],
        }

    async def query_pr_memories(
        self,
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
        if self.next_error is not None:
            raise self.next_error
        return [
            {
                "memory_id": "pr-memory-14",
                "project": project,
                "repo": repo or "ExampleProject",
                "pr_number": pr_number or 14,
                "title": "feat: sync emails via LLM and upsert proposals",
                "summary": "Implements sync and upsert flow.",
                "changed_files": ["app/services/email/sync_service.rb"],
                "areas": ["backend"],
                "touches_frontend": False,
                "touches_backend": True,
            }
        ]


@dataclass
class FakeContainer:
    pr_memory: FakePRMemoryService


def _make_client(container: FakeContainer) -> TestClient:
    return TestClient(create_http_app(container), raise_server_exceptions=False)


def test_create_pr_memory_route_returns_json() -> None:
    client = _make_client(FakeContainer(pr_memory=FakePRMemoryService()))

    response = client.post(
        "/pr-memories",
        json={
            "project": "EXAMPLE_PROJECT",
            "repo": "ExampleProject",
            "pr_number": 14,
            "title": "feat: sync emails via LLM and upsert proposals",
            "summary": "Implements sync and upsert flow.",
            "changed_files": ["app/services/email/sync_service.rb"],
            "pr_url": "https://github.com/org/repo/pull/14",
            "work_item_url": "https://company.atlassian.net/browse/ENG-14",
            "areas": ["backend"],
        },
    )

    assert response.status_code == 200
    assert response.json()["repo"] == "ExampleProject"
    assert response.json()["related_pr_candidates"] == []


def test_query_pr_memory_route_filters_by_repo() -> None:
    container = FakeContainer(pr_memory=FakePRMemoryService())
    client = _make_client(container)

    response = client.get("/pr-memories", params={"project": "EXAMPLE_PROJECT", "repo": "ExampleProject"})

    assert response.status_code == 200
    assert response.json()[0]["repo"] == "ExampleProject"
    assert container.pr_memory.query_calls[0] == {
        "project": "EXAMPLE_PROJECT",
        "repo": "ExampleProject",
        "pr_number": None,
        "changed_file_contains": None,
    }


def test_pr_memory_routes_map_service_errors() -> None:
    client = _make_client(
        FakeContainer(
            pr_memory=FakePRMemoryService(next_error=MemoryServiceError("pr memory unavailable"))
        )
    )

    response = client.get("/pr-memories", params={"project": "EXAMPLE_PROJECT"})

    assert response.status_code == 503
    assert response.json()["detail"]["resource"] == "pr_memory"


def test_create_pr_memory_route_rejects_missing_pr_url_with_422() -> None:
    client = _make_client(FakeContainer(pr_memory=FakePRMemoryService()))

    response = client.post(
        "/pr-memories",
        json={
            "project": "EXAMPLE_PROJECT",
            "repo": "ExampleProject",
            "pr_number": 14,
            "title": "feat: sync",
            "summary": "Sync flow.",
            "changed_files": ["app/file.rb"],
            "work_item_url": "https://company.atlassian.net/browse/ENG-14",
            "areas": ["backend"],
        },
    )

    assert response.status_code == 422


def test_create_pr_memory_route_propagates_new_fields() -> None:
    container = FakeContainer(pr_memory=FakePRMemoryService())
    client = _make_client(container)

    response = client.post(
        "/pr-memories",
        json={
            "project": "EXAMPLE_PROJECT",
            "repo": "ExampleProject",
            "pr_number": 14,
            "title": "feat: sync",
            "summary": "Sync flow.",
            "changed_files": ["app/file.rb"],
            "pr_url": "https://github.com/org/repo/pull/14",
            "work_item_url": "https://company.atlassian.net/browse/ENG-14",
            "work_item_summary": "Card about email sync",
            "event_date": "2026-04-22T10:00:00",
            "areas": ["backend"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["work_item_summary"] == "Card about email sync"
    assert body["event_date"] == "2026-04-22T10:00:00"
    command = container.pr_memory.create_calls[0]
    assert command.work_item_summary == "Card about email sync"
    assert command.event_date == "2026-04-22T10:00:00"
