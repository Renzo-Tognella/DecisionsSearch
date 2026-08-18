"""Resolve the project partition from the agent's working directory."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ENV_VAR = "DECISIONSSEARCH_PROJECT"


def _clean_project(value: str | None) -> str:
    return str(value or "").strip()


def _project_root(path: Path) -> Path:
    """Return the repository root when ``path`` is inside a Git checkout."""

    resolved = path.expanduser().resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            return candidate
    return resolved


def current_project(cwd: str | Path | None = None) -> str:
    """Return the project tag for the current agent workspace.

    ``DECISIONSSEARCH_PROJECT`` is an explicit deployment override. Otherwise
    the name of the Git repository root is used; for non-Git workspaces the
    current directory name is used. Resolving this at call time keeps a long-
    running MCP process correct when its working directory changes.
    """

    configured = _clean_project(os.getenv(PROJECT_ENV_VAR))
    if configured:
        return configured

    workspace = _project_root(Path(cwd) if cwd is not None else Path.cwd())
    project = _clean_project(workspace.name)
    if not project:
        raise ValueError(
            "Não foi possível determinar o projeto pela pasta de trabalho; "
            f"configure {PROJECT_ENV_VAR}."
        )
    return project


def resolve_project(project: str | None = None, *, cwd: str | Path | None = None) -> str:
    """Resolve an optional project while keeping the workspace as the default."""

    configured = _clean_project(os.getenv(PROJECT_ENV_VAR))
    if configured:
        return configured
    explicit = _clean_project(project)
    return explicit or current_project(cwd)
