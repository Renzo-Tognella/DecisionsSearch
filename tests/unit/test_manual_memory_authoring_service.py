from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from decisionssearch.domain import CreateManualMemoryCommand, EvidenceRef, MemoryCandidate, MemoryItem, MemoryStatus
from decisionssearch.domain.shared.exceptions import AdmissionError
from decisionssearch.application.memory.admission_gates import AdmissionResult
from decisionssearch.application.memory.manual_memory_authoring_service import ManualMemoryAuthoringService


@dataclass
class FakeAdmissionService:
    seen_candidates: list[MemoryCandidate]
    result: AdmissionResult

    def __init__(self, result: AdmissionResult | None = None) -> None:
        self.seen_candidates = []
        self.result = result or AdmissionResult(status="active", action="create", reason="manual accepted")

    async def evaluate(self, candidate: MemoryCandidate) -> AdmissionResult:
        self.seen_candidates.append(candidate)
        return self.result


@dataclass
class FakePersistenceService:
    seen_calls: list[tuple[MemoryCandidate, AdmissionResult]]

    def __init__(self) -> None:
        self.seen_calls = []

    async def persist(self, candidate: MemoryCandidate, admission: AdmissionResult) -> MemoryItem:
        self.seen_calls.append((candidate, admission))
        return MemoryItem(
            memory_id="m-1",
            project=candidate.project,
            category=candidate.type,
            domain=candidate.domain,
            title=candidate.title,
            summary=candidate.summary,
            details=candidate.details,
            status=MemoryStatus.ACTIVE,
        )


def test_manual_memory_service_builds_candidate_and_passes_pipeline() -> None:
    admission = FakeAdmissionService()
    persistence = FakePersistenceService()
    service = ManualMemoryAuthoringService(admission=admission, persistence=persistence)

    result = asyncio.run(
        service.create_manual_memory(
            CreateManualMemoryCommand(
                project="CORE",
                category="DesignRule",
                domain=["Billing"],
                title="Forms Pattern",
                summary="Use forms for writes",
                details="Keep writes centralized",
            )
        )
    )

    assert result.memory_id == "m-1"
    assert len(admission.seen_candidates) == 1
    candidate = admission.seen_candidates[0]
    assert candidate.project == "CORE"
    assert candidate.type == "DesignRule"
    assert candidate.domain == ["Billing"]
    assert candidate.evidence == [
        EvidenceRef(
            type="manual",
            ref="CORE:DesignRule:Forms Pattern",
            snippet="Use forms for writes",
        )
    ]
    assert len(persistence.seen_calls) == 1
    persisted_candidate, admission_result = persistence.seen_calls[0]
    assert persisted_candidate == candidate
    assert admission_result.status == "active"


def test_manual_memory_service_passes_new_fields_to_candidate() -> None:
    admission = FakeAdmissionService()
    persistence = FakePersistenceService()
    service = ManualMemoryAuthoringService(admission=admission, persistence=persistence)

    result = asyncio.run(
        service.create_manual_memory(
            CreateManualMemoryCommand(
                project="CORE",
                category="BusinessRule",
                domain=["Billing"],
                modules=["faturamento", "TUSD"],
                title="TUSD billing rule",
                summary="TUSD must be billed monthly",
                details="All TUSD charges are billed on a monthly cycle.",
                examples=[],
                alternatives_considered=[],
                event_date="2026-04-22T10:00:00",
            )
        )
    )

    assert result.memory_id == "m-1"
    candidate = admission.seen_candidates[0]
    assert candidate.modules == ["faturamento", "TUSD"]
    assert candidate.event_date is not None
    assert candidate.event_date.year == 2026


def test_manual_memory_service_rejected_admission_does_not_persist() -> None:
    admission = FakeAdmissionService(
        result=AdmissionResult(status="rejected", action="reject", reason="Sem evidencia")
    )
    persistence = FakePersistenceService()
    service = ManualMemoryAuthoringService(admission=admission, persistence=persistence)

    with pytest.raises(AdmissionError) as error:
        asyncio.run(
            service.create_manual_memory(
                CreateManualMemoryCommand(
                    project="CORE",
                    category="DesignRule",
                    domain=["Billing"],
                    title="Forms Pattern",
                    summary="Use forms for writes",
                    details="Keep writes centralized",
                )
            )
        )

    assert persistence.seen_calls == []
    assert error.value.context["status"] == "rejected"
    assert error.value.context["action"] == "reject"
