from datetime import UTC

import pytest
from pydantic import ValidationError

from decisionssearch.domain import EvidenceRef, MemoryCandidate, MemoryItem, MemoryStatus, RawEvent, SourceKind


@pytest.mark.parametrize("source_kind", list(SourceKind))
def test_raw_event_accepts_all_source_kinds(source_kind: SourceKind) -> None:
    event = RawEvent(
        event_id="evt-123",
        source_kind=source_kind,
        payload="payload",
        project_hint=" CORE ",
        domain_hint=" Billing ",
    )

    assert event.source_kind == source_kind
    assert event.project_hint == "CORE"
    assert event.domain_hint == "Billing"
    assert event.created_at.tzinfo == UTC


def test_memory_candidate_validates_weight_range() -> None:
    with pytest.raises(ValidationError):
        MemoryCandidate(
            project="CORE",
            type="DesignPattern",
            title="Forms",
            summary="Use forms",
            proposed_weight=1.5,
        )


def test_memory_candidate_normalizes_lists_and_evidence() -> None:
    candidate = MemoryCandidate(
        project=" CORE ",
        type=" DesignRule ",
        title=" Write path ",
        summary=" Use forms ",
        domain=[" Billing ", "", " Treasury "],
        examples=[" one ", " ", " two "],
        tags=[" api ", "", "forms "],
        evidence=[EvidenceRef(type=" commit ", ref=" abc123 ", snippet=" diff ")],
    )

    assert candidate.project == "CORE"
    assert candidate.type == "DesignRule"
    assert candidate.title == "Write path"
    assert candidate.summary == "Use forms"
    assert candidate.domain == ["Billing", "Treasury"]
    assert candidate.examples == ["one", "two"]
    assert candidate.tags == ["api", "forms"]
    assert candidate.evidence[0].type == "commit"
    assert candidate.evidence[0].ref == "abc123"
    assert candidate.evidence[0].snippet == "diff"


def test_memory_item_generate_id_returns_stable_16_char_hash() -> None:
    generated = MemoryItem.generate_id("CORE", "DesignPattern", " Forms Pattern ")

    assert generated == MemoryItem.generate_id("CORE", "DesignPattern", "forms pattern")
    assert len(generated) == 16


def test_memory_item_defaults_and_normalization() -> None:
    item = MemoryItem(
        memory_id=" mem-123 ",
        project=" CORE ",
        category=" DesignPattern ",
        domain=[" Billing ", "", " Treasury "],
        title=" Forms Pattern ",
        summary=" Use forms for writes ",
    )

    assert item.memory_id == "mem-123"
    assert item.project == "CORE"
    assert item.category == "DesignPattern"
    assert item.domain == ["Billing", "Treasury"]
    assert item.status == MemoryStatus.PROPOSED
    assert item.created_at.tzinfo == UTC
    assert item.updated_at.tzinfo == UTC
    assert item.valid_at.tzinfo == UTC


def test_memory_item_accepts_new_type_specific_fields() -> None:
    from datetime import datetime, timezone

    item = MemoryItem(
        memory_id="mem-456",
        project="CORE",
        category="ArchitecturalDecision",
        domain=["infrastructure"],
        modules=[" faturamento ", "", " TUSD "],
        title="Use PostgreSQL",
        summary="Chose PostgreSQL",
        examples=[" example1 ", " example2 "],
        alternatives_considered=[" MongoDB "],
        event_date=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )

    assert item.modules == ["faturamento", "TUSD"]
    assert item.examples == ["example1", "example2"]
    assert item.alternatives_considered == ["MongoDB"]
    assert item.event_date is not None
    assert item.event_date.year == 2026


def test_memory_item_new_fields_default_to_empty() -> None:
    item = MemoryItem(
        memory_id="mem-789",
        project="CORE",
        category="BusinessRule",
        title="Some rule",
        summary="A rule",
    )

    assert item.modules == []
    assert item.examples == []
    assert item.alternatives_considered == []
    assert item.event_date is None


def test_memory_candidate_accepts_modules_and_alternatives() -> None:
    from datetime import datetime, timezone

    candidate = MemoryCandidate(
        project="CORE",
        type="ArchitecturalDecision",
        title="Use Redis",
        summary="Cache layer",
        modules=[" cache ", " api "],
        alternatives_considered=[" Memcached "],
        event_date=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )

    assert candidate.modules == ["cache", "api"]
    assert candidate.alternatives_considered == ["Memcached"]
    assert candidate.event_date is not None
