from __future__ import annotations

from pathlib import Path

from scripts.post_commit_memory_hook import _repository_from_remote, read_session


def test_repository_from_github_remotes():
    assert _repository_from_remote("git@github.com:acme/decisionssearch.git") == "acme/decisionssearch"
    assert _repository_from_remote("https://github.com/acme/decisionssearch.git") == "acme/decisionssearch"


def test_read_session_prefers_explicit_file(tmp_path: Path):
    explicit = tmp_path / "current-session.md"
    explicit.write_text("Decisão da sessão", encoding="utf-8")

    content, session_id = read_session(tmp_path, str(explicit))

    assert content == "Decisão da sessão"
    assert session_id == "current-session"
