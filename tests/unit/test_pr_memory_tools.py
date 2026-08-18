from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from decisionssearch.domain import CreatePRMemoryCommand
from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.interfaces.mcp.tools import register_tools


@dataclass
class FakeMCPApp:
    tools: dict[str, object] = field(default_factory=dict)

    def tool(self, name: str | None = None):  # noqa: ANN201
        def decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return decorator


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
    catalog_csv: object = None
    graph_catalog: object = None
    graph_operations: object = None
    manual_memory_authoring: object = None


def test_register_tools_exposes_pr_memory_tools() -> None:
    app = FakeMCPApp()
    container = FakeContainer(pr_memory=FakePRMemoryService())

    register_tools(app, container)

    assert "memory.pr.create" in app.tools
    assert "memory.pr.query" in app.tools


def test_memory_pr_create_delegates_to_pr_memory_service() -> None:
    app = FakeMCPApp()
    container = FakeContainer(pr_memory=FakePRMemoryService())
    register_tools(app, container)

    result = asyncio.run(
        app.tools["memory.pr.create"](
            project="EXAMPLE_PROJECT",
            repo="ExampleProject",
            pr_number=14,
            title="feat: sync emails via LLM and upsert proposals",
            summary="Implements sync and upsert flow.",
            changed_files=["app/services/email/sync_service.rb"],
            pr_url="https://github.com/org/repo/pull/14",
            work_item_url="https://company.atlassian.net/browse/ENG-14",
            areas=["backend"],
        )
    )

    assert result["repo"] == "ExampleProject"
    assert result["related_pr_candidates"] == []
    assert container.pr_memory.create_calls[0] == CreatePRMemoryCommand(
        project="EXAMPLE_PROJECT",
        repo="ExampleProject",
        pr_number=14,
        title="feat: sync emails via LLM and upsert proposals",
        summary="Implements sync and upsert flow.",
        changed_files=["app/services/email/sync_service.rb"],
        pr_url="https://github.com/org/repo/pull/14",
        work_item_url="https://company.atlassian.net/browse/ENG-14",
        areas=["backend"],
    )


def test_memory_pr_query_delegates_to_pr_memory_service() -> None:
    app = FakeMCPApp()
    container = FakeContainer(pr_memory=FakePRMemoryService())
    register_tools(app, container)

    result = asyncio.run(
        app.tools["memory.pr.query"](
            project="EXAMPLE_PROJECT",
            repo="ExampleProject",
            pr_number=14,
            changed_file_contains="sync_service",
        )
    )

    assert result[0]["repo"] == "ExampleProject"
    assert container.pr_memory.query_calls[0] == {
        "project": "EXAMPLE_PROJECT",
        "repo": "ExampleProject",
        "pr_number": 14,
        "changed_file_contains": "sync_service",
    }


def test_pr_memory_tools_surface_service_errors_as_error_dicts() -> None:
    app = FakeMCPApp()
    container = FakeContainer(pr_memory=FakePRMemoryService(next_error=MemoryServiceError("pr failed")))
    register_tools(app, container)

    create_result = asyncio.run(
        app.tools["memory.pr.create"](
            project="EXAMPLE_PROJECT",
            repo="ExampleProject",
            pr_number=14,
            title="feat: sync emails via LLM and upsert proposals",
            summary="Implements sync and upsert flow.",
            changed_files=["app/services/email/sync_service.rb"],
            pr_url="https://github.com/org/repo/pull/14",
            work_item_url="https://company.atlassian.net/browse/ENG-14",
            areas=["backend"],
        )
    )
    query_result = asyncio.run(app.tools["memory.pr.query"](project="EXAMPLE_PROJECT"))

    assert create_result == {"error": "pr failed", "type": "MemoryServiceError"}
    assert query_result == {"error": "pr failed", "type": "MemoryServiceError"}
