from __future__ import annotations

from types import SimpleNamespace

import pytest

from decisionssearch.domain.memory.memory_candidate import EvidenceRef, MemoryCandidate
from decisionssearch.application.memory.admission_gates import AdmissionResult
from decisionssearch.application.memory.commit_memory_hook import (
    CommitContext,
    CommitMemoryCaptureService,
    JsonlCaptureState,
    PostCommitMemoryContext,
    PullRequestContext,
)
from decisionssearch.application.memory.extraction_service import ExtractionService


def _context() -> PostCommitMemoryContext:
    return PostCommitMemoryContext(
        project="DecisionsSearch",
        session_id="session-42",
        session_text="Foi decidido separar a busca por arquivo da busca semântica do resumo.",
        commit=CommitContext(
            sha="abc123",
            subject="Improve PR memory retrieval",
            branch="feat/pr-memory",
            repository="acme/decisionssearch",
            changed_files=("services/pr_memory_service.py", "tests/unit/test_pr_memory.py"),
            diff="2 files changed, 30 insertions(+), 8 deletions(-)",
        ),
        pull_request=PullRequestContext(
            number=17,
            repository="acme/decisionssearch",
            title="Improve PR memory retrieval",
            url="https://github.com/acme/decisionssearch/pull/17",
            body="The file filter is structural and the summary is semantic.",
            changed_files=("services/pr_memory_service.py",),
        ),
    )


class FakeExtraction:
    _structured_client = object()

    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []

    async def extract_candidates(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.candidates


class FakeAdmission:
    async def evaluate(self, candidate):
        return AdmissionResult(status="active", action="create", reason="durable")


class FakePersistence:
    def __init__(self):
        self.calls = []

    async def persist(self, candidate, admission):
        self.calls.append((candidate, admission))
        return SimpleNamespace(memory_id="memory-1")


def _candidate() -> MemoryCandidate:
    return MemoryCandidate(
        project="DecisionsSearch",
        type="ArchitecturalDecision",
        title="Separar filtro estrutural e ranking semântico de PRs.",
        summary="A busca de PRs está filtrando arquivos estruturalmente e ranqueando o resumo semanticamente.",
        details="A decisão está reduzindo concorrentes irrelevantes durante a investigação de regressões.",
        architectural_rationale="A separação está preservando a precisão do arquivo sem perder a intenção da pergunta.",
        alternatives_considered=["Usar somente busca semântica global."],
        proposed_weight=0.8,
        evidence=[EvidenceRef(type="conversation", ref="session:session-42", snippet="decisão")],
    )


def test_extraction_prompt_contains_non_forcing_memory_contract():
    service = ExtractionService.__new__(ExtractionService)

    prompt = service._system_prompt("DecisionsSearch", None)

    assert "<memory_awareness>" in prompt
    assert "no_memory" in prompt
    assert "não force" in prompt.lower()


@pytest.mark.asyncio
async def test_no_memory_is_a_valid_post_commit_result(tmp_path):
    extraction = FakeExtraction([])
    persistence = FakePersistence()
    service = CommitMemoryCaptureService(
        extraction=extraction,
        admission=FakeAdmission(),
        persistence=persistence,
        state=JsonlCaptureState(tmp_path / "state.jsonl"),
    )

    result = await service.capture(_context())

    assert result["decision"] == "no_memory"
    assert result["status"] == "no_memory"
    assert persistence.calls == []


@pytest.mark.asyncio
async def test_commit_capture_sends_session_and_pr_to_llm_and_persists(tmp_path):
    extraction = FakeExtraction([_candidate()])
    persistence = FakePersistence()
    service = CommitMemoryCaptureService(
        extraction=extraction,
        admission=FakeAdmission(),
        persistence=persistence,
        state=JsonlCaptureState(tmp_path / "state.jsonl"),
    )

    result = await service.capture(_context())

    source_text = extraction.calls[0][0][0]
    kwargs = extraction.calls[0][1]
    assert "separar a busca por arquivo" in source_text
    assert "pull/17" in source_text
    assert kwargs["allow_heuristic_fallback"] is False
    assert kwargs["source_event_id"].startswith("post-commit:")
    assert result["status"] == "captured"
    assert result["memory_ids"] == ["memory-1"]

    enriched = persistence.calls[0][0]
    assert "services/pr_memory_service.py" in enriched.related_files
    assert "services" in enriched.modules
    assert {item.type for item in enriched.evidence} >= {"commit", "conversation", "pull_request"}


@pytest.mark.asyncio
async def test_same_commit_and_pr_are_idempotent(tmp_path):
    extraction = FakeExtraction([_candidate()])
    persistence = FakePersistence()
    service = CommitMemoryCaptureService(
        extraction=extraction,
        admission=FakeAdmission(),
        persistence=persistence,
        state=JsonlCaptureState(tmp_path / "state.jsonl"),
    )

    first = await service.capture(_context())
    second = await service.capture(_context())

    assert first["status"] == "captured"
    assert second["status"] == "already_processed"
    assert len(persistence.calls) == 1
