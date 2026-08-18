import asyncio

from decisionssearch.domain.memory.memory_candidate import EvidenceRef, MemoryCandidate
from decisionssearch.domain.memory.memory_item import MemoryItem
from decisionssearch.application.memory.admission_gates import (
    ContextValidationGate,
    DuplicateGate,
    EvidenceGate,
    ProjectGate,
    WeightGate,
)


class StubVectorStore:
    def __init__(self, score: float | None = None, memory_id: str = "m-existing"):
        self.score = score
        self.memory_id = memory_id

    async def find_similar(self, embedding, project, type, threshold=0.92):  # noqa: ANN001
        del embedding, project, type, threshold
        if self.score is None:
            return []
        return [{"memory_id": self.memory_id, "score": self.score}]


class StubEmbeddings:
    async def embed(self, text: str):  # noqa: ANN201
        return [float(len(text))]


def _candidate(**kwargs) -> MemoryCandidate:
    payload = {
        "project": "CORE",
        "type": "DesignRule",
        "title": "Rule",
        "summary": "Summary",
        "details": "Details",
        "proposed_weight": 0.7,
        "evidence": [EvidenceRef(type="commit", ref="abc", snippet="s")],
    }
    payload.update(kwargs)
    return MemoryCandidate(**payload)


def test_project_gate_rejects_missing_project() -> None:
    gate = ProjectGate()
    result = asyncio.run(gate.evaluate(_candidate(project="")))
    assert result is not None
    assert result.status == "rejected"


def test_evidence_gate_marks_evidence_only() -> None:
    gate = EvidenceGate()
    result = asyncio.run(gate.evaluate(_candidate(evidence=[])))
    assert result is not None
    assert result.status == "evidence_only"


def test_duplicate_gate_returns_update() -> None:
    candidate = _candidate()
    candidate_id = MemoryItem.generate_id(candidate.project, candidate.type, candidate.title)
    gate = DuplicateGate(StubVectorStore(score=0.95, memory_id=candidate_id), StubEmbeddings())
    result = asyncio.run(gate.evaluate(candidate))
    assert result is not None
    assert result.action == "update"
    assert result.memory_id == candidate_id


def test_duplicate_gate_does_not_rebind_distinct_identity() -> None:
    candidate = _candidate()
    candidate_id = MemoryItem.generate_id(candidate.project, candidate.type, candidate.title)
    gate = DuplicateGate(StubVectorStore(score=0.95), StubEmbeddings())

    result = asyncio.run(gate.evaluate(candidate))

    assert result is not None
    assert result.action == "refine"
    assert result.memory_id == candidate_id
    assert result.related_id == "m-existing"


def test_duplicate_gate_returns_refine() -> None:
    gate = DuplicateGate(StubVectorStore(score=0.85), StubEmbeddings())
    result = asyncio.run(gate.evaluate(_candidate()))
    assert result is not None
    assert result.action == "refine"
    assert result.related_id == "m-existing"


def test_weight_gate_rejects_low_weight_for_non_adr() -> None:
    gate = WeightGate()
    result = asyncio.run(gate.evaluate(_candidate(proposed_weight=0.1, type="DesignPattern")))
    assert result is not None
    assert result.status == "rejected"


def test_weight_gate_allows_low_weight_for_adr() -> None:
    gate = WeightGate()
    result = asyncio.run(
        gate.evaluate(_candidate(proposed_weight=0.1, type="ArchitecturalDecision"))
    )
    assert result is None


def test_context_gate_rejects_empty_domain_for_business_rule() -> None:
    gate = ContextValidationGate()
    result = asyncio.run(gate.evaluate(_candidate(type="BusinessRule", domain=[])))
    assert result is not None
    assert result.status == "rejected"


def test_context_gate_passes_business_rule_with_domain() -> None:
    gate = ContextValidationGate()
    result = asyncio.run(gate.evaluate(_candidate(type="BusinessRule", domain=["Billing"])))
    assert result is None


def test_context_gate_passes_non_business_rule_without_domain() -> None:
    gate = ContextValidationGate()
    result = asyncio.run(gate.evaluate(_candidate(type="DesignPattern", domain=[])))
    assert result is None
