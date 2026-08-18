"""Entry point do hook Git pós-commit.

Uso direto (útil para testar):

    python -m scripts.post_commit_memory_hook --repo /caminho/projeto --dry-run

O hook instalado chama este módulo em background e ignora qualquer falha para
que indisponibilidade de LLM, GitHub ou banco nunca invalide um commit local.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from decisionssearch.bootstrap.container import create_container
from decisionssearch.application.memory.commit_memory_hook import (
    CommitContext,
    CommitMemoryCaptureService,
    JsonlCaptureState,
    PostCommitMemoryContext,
    PullRequestContext,
)

logger = logging.getLogger("decisionssearch.post_commit_memory_hook")


def _run_git(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _run_json_command(repo: Path, command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode != 0:
        return {}
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _repository_from_remote(remote: str) -> str:
    remote = remote.strip().removesuffix(".git")
    if remote.startswith("git@github.com:"):
        return remote.split(":", 1)[1]
    marker = "github.com/"
    if marker in remote:
        parts = [part for part in remote.split(marker, 1)[1].split("/") if part]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    return remote.rsplit("/", 1)[-1]


def collect_commit_context(repo: Path) -> CommitContext:
    sha = _run_git(repo, "rev-parse", "HEAD")
    subject = _run_git(repo, "log", "-1", "--format=%s")
    body = _run_git(repo, "log", "-1", "--format=%b")
    author = _run_git(repo, "log", "-1", "--format=%an <%ae>")
    branch = _run_git(repo, "branch", "--show-current")
    remote = _run_git(repo, "config", "--get", "remote.origin.url")
    changed_files = tuple(
        line for line in _run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha).splitlines()
        if line.strip()
    )
    diff = _run_git(repo, "show", "--format=", "--stat", "--no-ext-diff", sha)
    return CommitContext(
        sha=sha,
        subject=subject,
        body=body,
        author=author,
        branch=branch,
        repository=_repository_from_remote(remote),
        changed_files=changed_files,
        diff=diff,
    )


def collect_pull_request(repo: Path, repository: str = "") -> PullRequestContext:
    data = _run_json_command(
        repo,
        [
            "gh",
            "pr",
            "view",
            "--json",
            "number,title,url,body,state,headRefName,baseRefName,files",
        ],
    )
    if not data:
        return PullRequestContext(repository=repository)

    files = data.get("files") or []
    changed_files = tuple(
        str(item.get("path", "")).strip()
        for item in files
        if isinstance(item, dict) and str(item.get("path", "")).strip()
    )
    number = data.get("number")
    try:
        number = int(number) if number is not None else None
    except (TypeError, ValueError):
        number = None
    return PullRequestContext(
        number=number,
        repository=repository,
        title=str(data.get("title", "")),
        url=str(data.get("url", "")),
        body=str(data.get("body", "")),
        state=str(data.get("state", "")),
        head_branch=str(data.get("headRefName", "")),
        base_branch=str(data.get("baseRefName", "")),
        changed_files=changed_files,
    )


def read_session(repo: Path, explicit_path: str = "") -> tuple[str, str]:
    configured = explicit_path or os.getenv("DECISIONSSEARCH_SESSION_FILE", "")
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        [
            repo / ".decisionssearch" / "session.md",
            repo / ".decisionssearch" / "session.txt",
            repo / "data" / "session.md",
        ]
    )
    for path in candidates:
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8"), path.stem
        except OSError:
            continue
    return "", ""


def build_context(repo: Path, project: str = "", session_file: str = "") -> PostCommitMemoryContext:
    commit = collect_commit_context(repo)
    session_text, inferred_session_id = read_session(repo, session_file)
    project = project or os.getenv("DECISIONSSEARCH_PROJECT", "") or repo.name
    pull_request = collect_pull_request(repo, commit.repository)
    return PostCommitMemoryContext(
        project=project,
        session_text=session_text,
        session_id=os.getenv("DECISIONSSEARCH_SESSION_ID", "") or inferred_session_id,
        commit=commit,
        pull_request=pull_request,
    )


async def run_capture(
    context: PostCommitMemoryContext,
    *,
    state_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    container = create_container()
    try:
        service = CommitMemoryCaptureService(
            extraction=container.extraction,
            admission=container.admission,
            persistence=container.persistence,
            sanitization=container.sanitization,
            state=JsonlCaptureState(state_path),
        )
        return await service.capture(context, dry_run=dry_run)
    finally:
        await container.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="raiz do repositório")
    parser.add_argument("--project", default="", help="namespace do projeto no DecisionsSearch")
    parser.add_argument("--session-file", default="", help="arquivo com a sessão atual")
    parser.add_argument(
        "--state-path",
        default="",
        help="JSONL de idempotência (default: <repo>/.decisionssearch/commit-memory-state.jsonl)",
    )
    parser.add_argument("--dry-run", action="store_true", help="não persistir, apenas avaliar")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.getenv("DECISIONSSEARCH_COMMIT_MEMORY_LOG_LEVEL", "WARNING"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    repo = Path(args.repo).resolve()
    context = build_context(repo, project=args.project, session_file=args.session_file)
    state_path = Path(args.state_path).resolve() if args.state_path else repo / ".decisionssearch" / "commit-memory-state.jsonl"
    try:
        result = asyncio.run(run_capture(context, state_path=state_path, dry_run=args.dry_run))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:  # fail-open: a hook nunca invalida o commit
        logger.warning("Hook pós-commit ignorado: %s", error)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "collect_commit_context",
    "collect_pull_request",
    "read_session",
    "build_context",
    "main",
]
