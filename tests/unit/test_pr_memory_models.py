import pytest
from pydantic import ValidationError

from decisionssearch.domain import CreatePRMemoryCommand, PRMemory

_REQUIRED_PR_FIELDS = {
    "pr_url": "https://github.com/org/repo/pull/14",
    "work_item_url": "https://company.atlassian.net/browse/ENG-1234",
}


def test_create_pr_memory_command_normalizes_changed_files_and_areas() -> None:
    command = CreatePRMemoryCommand(
        project="EXAMPLE_PROJECT",
        repo="ExampleProject",
        pr_number=14,
        title="feat: sync emails via LLM and upsert proposals",
        summary="Implements sync and upsert flow.",
        changed_files=[
            " app/services/email/sync_service.rb ",
            "app/services/email/sync_service.rb",
            "config/routes.rb",
        ],
        areas=[" backend ", "backend", "email"],
        **_REQUIRED_PR_FIELDS,
    )

    assert command.changed_files == [
        "app/services/email/sync_service.rb",
        "config/routes.rb",
    ]
    assert command.areas == ["backend", "email"]


def test_create_pr_memory_command_requires_summary_and_changed_files() -> None:
    with pytest.raises(ValidationError):
        CreatePRMemoryCommand(
            project="EXAMPLE_PROJECT",
            repo="ExampleProject",
            pr_number=14,
            title="feat: sync emails via LLM and upsert proposals",
            summary="",
            changed_files=[],
            **_REQUIRED_PR_FIELDS,
        )


def test_create_pr_memory_command_requires_pr_url() -> None:
    with pytest.raises(ValidationError):
        CreatePRMemoryCommand(
            project="EXAMPLE_PROJECT",
            repo="ExampleProject",
            pr_number=14,
            title="feat: sync",
            summary="Sync flow.",
            changed_files=["app/file.rb"],
            pr_url="",
            work_item_url="https://company.atlassian.net/browse/ENG-1234",
        )


def test_create_pr_memory_command_requires_work_item_url() -> None:
    with pytest.raises(ValidationError):
        CreatePRMemoryCommand(
            project="EXAMPLE_PROJECT",
            repo="ExampleProject",
            pr_number=14,
            title="feat: sync",
            summary="Sync flow.",
            changed_files=["app/file.rb"],
            pr_url="https://github.com/org/repo/pull/14",
            work_item_url="",
        )


def test_create_pr_memory_command_accepts_new_optional_fields() -> None:
    command = CreatePRMemoryCommand(
        project="EXAMPLE_PROJECT",
        repo="ExampleProject",
        pr_number=14,
        title="feat: sync",
        summary="Sync flow.",
        changed_files=["app/file.rb"],
        work_item_summary="Card about email sync",
        event_date="2026-04-22T10:00:00",
        **_REQUIRED_PR_FIELDS,
    )

    assert command.work_item_summary == "Card about email sync"
    assert command.event_date == "2026-04-22T10:00:00"


def test_pr_memory_derives_frontend_backend_flags_from_areas() -> None:
    memory = PRMemory(
        memory_id="pr-memory-1",
        project="EXAMPLE_PROJECT",
        repo="ExampleDashboard",
        pr_number=6,
        title="feat: expand dashboard and reports ux metrics",
        summary="Expands dashboard UX.",
        changed_files=["app/(portal)/reports/page.tsx", "lib/api.ts"],
        areas=["frontend", "reports"],
        **_REQUIRED_PR_FIELDS,
    )

    assert memory.touches_frontend is True
    assert memory.touches_backend is False


def test_pr_memory_accepts_generic_work_item_fields() -> None:
    memory = PRMemory(
        memory_id="pr-memory-14",
        project="EXAMPLE_PROJECT",
        repo="ExampleProject",
        pr_number=14,
        title="feat: sync emails via LLM and upsert proposals",
        summary="Implements sync and upsert flow.",
        changed_files=["app/services/email/sync_service.rb"],
        areas=["backend"],
        pr_url="https://github.com/org/repo/pull/14",
        work_item_id="ENG-1234",
        work_item_url="https://company.atlassian.net/browse/ENG-1234",
        work_item_provider="jira",
    )

    assert memory.work_item_id == "ENG-1234"
    assert memory.work_item_provider == "jira"


def test_pr_memory_accepts_new_fields() -> None:
    memory = PRMemory(
        memory_id="pr-memory-14",
        project="EXAMPLE_PROJECT",
        repo="ExampleProject",
        pr_number=14,
        title="feat: sync",
        summary="Sync flow.",
        changed_files=["app/file.rb"],
        work_item_summary="Card summary",
        event_date="2026-04-22T10:00:00",
        **_REQUIRED_PR_FIELDS,
    )

    assert memory.work_item_summary == "Card summary"
    assert memory.event_date == "2026-04-22T10:00:00"
