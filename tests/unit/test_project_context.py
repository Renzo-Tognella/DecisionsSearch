from __future__ import annotations

import asyncio

from decisionssearch.application.memory.context_resolver import ContextResolver
from decisionssearch.application.memory.project_context import current_project, resolve_project


def test_current_project_uses_git_root_name(tmp_path):
    project_root = tmp_path / "billing-service"
    nested = project_root / "src" / "application"
    (project_root / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)

    assert current_project(nested) == "billing-service"


def test_project_environment_override_has_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("DECISIONSSEARCH_PROJECT", "configured-project")

    assert current_project(tmp_path / "ignored-folder") == "configured-project"
    assert resolve_project("explicit-project", cwd=tmp_path / "ignored-folder") == "configured-project"


def test_resolve_project_uses_folder_when_no_explicit_project(tmp_path, monkeypatch):
    monkeypatch.delenv("DECISIONSSEARCH_PROJECT", raising=False)
    workspace = tmp_path / "orders-api"
    workspace.mkdir()

    assert resolve_project(cwd=workspace) == "orders-api"


def test_context_resolver_does_not_infer_project_from_payload(tmp_path, monkeypatch):
    monkeypatch.delenv("DECISIONSSEARCH_PROJECT", raising=False)
    workspace = tmp_path / "orders-api"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    context = asyncio.run(
        ContextResolver(neo4j=None).resolve(
            "A regra do projeto RETUSD exige validação de contrato",
            domain_hint=None,
        )
    )

    assert context["project"] == "orders-api"
