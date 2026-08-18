from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import uuid

import pytest

from decisionssearch.application.memory.episodic_memory_service import EpisodicMemoryService
from decisionssearch.application.memory.ledger import (
    InMemoryMemoryLedger,
    LedgerApplyService,
    LocalApprovalBoundary,
    ProposalService,
)
from decisionssearch.application.memory.ledger.views import revision_to_legacy_view
from decisionssearch.application.memory.procedural_memory_service import ProceduralMemoryService
from decisionssearch.domain import (
    EpisodeStatus,
    EpisodicMemory,
    Evidence,
    EvidenceLinkSpec,
    EvidenceStance,
    FieldOrigin,
    LedgerConflictError,
    MemoryContent,
    MemoryScope,
    ProceduralMemory,
    canonical_json,
    content_hash,
    MemoryCandidate,
    usage_payload_hash,
)


def content(title: str = "Regra", summary: str = "Resumo", **updates) -> MemoryContent:
    return MemoryContent(
        project="DecisionsSearch",
        category="Rule",
        title=title,
        summary=summary,
        domain=("memory",),
        **updates,
    )


async def apply(ledger: InMemoryMemoryLedger, proposal, principal: str = "operator"):
    approval = await LocalApprovalBoundary(ledger).approve(
        proposal.proposal_id,
        principal_id=principal,
        preview_hash=proposal.preview_hash,
    )
    return await LedgerApplyService(ledger).apply(proposal.proposal_id, approval.approval_id)


@pytest.mark.asyncio
async def test_structured_payload_is_canonical_and_scope_specific() -> None:
    payload = {"b": [2, 1], "a": "value"}
    first = MemoryContent(
        project="p",
        category="Procedure",
        title="deploy",
        summary="deploy",
        memory_scope=MemoryScope.PROCEDURAL,
        payload_schema="procedural.v1",
        structured_payload=payload,
    )
    second = first.model_copy(update={"structured_payload_json": canonical_json(payload)})
    assert first.structured_payload_json == '{"a":"value","b":[2,1]}'
    assert first.structured_payload == second.structured_payload
    assert content_hash(first) == content_hash(second)
    with pytest.raises(ValueError):
        MemoryContent(
            project="p",
            category="Procedure",
            title="deploy",
            summary="deploy",
            memory_scope=MemoryScope.PROCEDURAL,
            payload_schema="procedural.v1",
            structured_payload={"bad": math.nan},
        )
    with pytest.raises(ValueError):
        MemoryContent(
            project="p",
            category="PR",
            title="pr",
            summary="pr",
            memory_scope=MemoryScope.PULL_REQUEST,
            payload_schema="procedural.v1",
            structured_payload={"memory_id": "m"},
        )
    with pytest.raises(ValueError):
        MemoryContent(
            project="p",
            category="Procedure",
            title="deploy",
            summary="deploy",
            memory_scope=MemoryScope.PROCEDURAL,
            payload_schema="custom.v999",
            structured_payload={"steps": []},
        )
    with pytest.raises(ValueError):
        MemoryContent(
            project="p",
            category="Procedure",
            title="deploy",
            summary="deploy",
            memory_scope=MemoryScope.PROCEDURAL,
            payload_schema="procedural.v1",
            structured_payload={"steps": ["new"]},
            structured_payload_json='{"steps":["old"]}',
        )


@pytest.mark.asyncio
async def test_evidence_stance_and_duplicate_fingerprint_are_preserved() -> None:
    ledger = InMemoryMemoryLedger()
    evidence = Evidence(source_kind="test", source_locator="source-1")
    proposal = await ProposalService(ledger).propose_create(
        content(),
        evidence=(evidence,),
        evidence_links=(
            EvidenceLinkSpec(
                evidence_id=evidence.evidence_id,
                stance=EvidenceStance.CONTRADICTS,
                confidence=0.9,
                claim_path="summary",
            ),
        ),
    )
    revision = await apply(ledger, proposal)
    link = ledger.revision_evidence[0]
    assert link.stance is EvidenceStance.CONTRADICTS
    assert link.claim_path == "summary"
    assert revision.evidence_link_ids == (link.link_id,)

    conflicting = evidence.model_copy(update={"source_locator": "other"})
    proposal2 = await ProposalService(ledger).propose_update(
        revision.family_id,
        content("new"),
        evidence=(conflicting,),
    )
    with pytest.raises(LedgerConflictError):
        await apply(ledger, proposal2)


@pytest.mark.asyncio
async def test_merge_conflict_is_blocked_and_manifest_can_unmerge() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    left = await apply(ledger, await service.propose_create(content("left", "same")))
    right = await apply(ledger, await service.propose_create(content("right", "same")))
    left_head = await ledger.get_head(left.family_id)
    right_head = await ledger.get_head(right.family_id)
    assert left_head and right_head
    merge = await service.propose_merge(
        left.family_id,
        content("left", "same"),
        expected_heads=(
            (left.family_id, "semantic", "semantic", left_head.revision_id),
            (right.family_id, "semantic", "semantic", right_head.revision_id),
        ),
        source_revision_ids=(left.revision_id, right.revision_id),
        field_origins=(FieldOrigin(field="title", source_revision_id=left.revision_id),),
    )
    merged = await apply(ledger, merge)
    manifest = await ledger.get_merge_manifest(merged.merge_manifest_id)
    assert manifest is not None
    assert await ledger.get_head(right.family_id) is None

    unmerge = await service.propose_unmerge(manifest.manifest_id)
    restored = await apply(ledger, unmerge, principal="operator-2")
    assert restored.revision_id == left.revision_id
    assert (await ledger.get_head(right.family_id)).revision_id == right.revision_id
    assert all(item.state is not item.state.ACTIVE for item in await ledger.list_relations())

    conflict_left = await apply(ledger, await service.propose_create(content("c1", "SQLite")))
    conflict_right = await apply(ledger, await service.propose_create(content("c2", "PostgreSQL")))
    conflict_left_head = await ledger.get_head(conflict_left.family_id)
    conflict_right_head = await ledger.get_head(conflict_right.family_id)
    blocked = await service.propose_merge(
        conflict_left.family_id,
        content("c", "ambiguous"),
        expected_heads=(
            (conflict_left.family_id, "semantic", "semantic", conflict_left_head.revision_id),
            (conflict_right.family_id, "semantic", "semantic", conflict_right_head.revision_id),
        ),
        source_revision_ids=(conflict_left.revision_id, conflict_right.revision_id),
    )
    assert blocked.status.value == "conflicted"
    with pytest.raises(Exception):
        await LocalApprovalBoundary(ledger).approve(
            blocked.proposal_id,
            principal_id="operator-3",
            preview_hash=blocked.preview_hash,
        )


@pytest.mark.asyncio
async def test_temporal_resolver_keeps_current_until_future_revision_is_effective() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    now = datetime.now(timezone.utc)
    first = await apply(
        ledger,
        await service.propose_create(
            content("v1", "old", valid_from=now - timedelta(days=1)),
        ),
    )
    future = now + timedelta(days=1)
    second = await apply(
        ledger,
        await service.propose_update(
            first.family_id,
            content("v2", "new", valid_from=future),
        ),
    )
    recorded_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    current = await ledger.list_effective_revisions(valid_at=now, recorded_at=recorded_at)
    later = await ledger.list_effective_revisions(
        valid_at=future + timedelta(seconds=1),
        recorded_at=recorded_at,
    )
    assert [item.content.title for item in current] == ["v1"]
    assert [item.content.title for item in later] == ["v2"]
    assert second.revision_id == (await ledger.get_head(first.family_id)).revision_id
    with pytest.raises(ValueError):
        await ledger.list_effective_revisions(valid_at=datetime.now(), recorded_at=recorded_at)


@pytest.mark.asyncio
async def test_legacy_facades_propose_and_usage_is_append_only_idempotent() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    episodes = EpisodicMemoryService(proposal_service=proposals, ledger=ledger)
    episode = EpisodicMemory(
        episode_id="episode-1",
        project="DecisionsSearch",
        task_description="rebuild index",
        outcome=EpisodeStatus.COMPLETED,
    )
    pending = await episodes.create_episode(episode)
    assert pending["status"] == "pending_approval"
    proposal = await ledger.get_proposal(uuid.UUID(pending["proposal_id"]))
    await apply(ledger, proposal)
    assert (await episodes.query_episodes("DecisionsSearch"))[0]["episode_id"] == "episode-1"

    procedures = ProceduralMemoryService(proposal_service=proposals, ledger=ledger)
    procedure = ProceduralMemory(
        procedure_id="procedure-1",
        project="DecisionsSearch",
        task_type="deploy",
        steps=["build", "rollout"],
    )
    pending_proc = await procedures.create_procedure(procedure)
    proc_proposal = await ledger.get_proposal(uuid.UUID(pending_proc["proposal_id"]))
    await apply(ledger, proc_proposal, principal="operator-2")
    first = await procedures.record_usage("procedure-1", True, idempotency_key="run-1", correlation_id="c1")
    second = await procedures.record_usage("procedure-1", True, idempotency_key="run-1", correlation_id="c1")
    assert first["observation_id"] == second["observation_id"]
    assert len(ledger.revisions) == 2
    rows = await procedures.query_procedures("DecisionsSearch")
    assert rows[0]["usage_count"] == 1
    assert rows[0]["success_rate"] == 1.0


@pytest.mark.asyncio
async def test_manual_weight_is_part_of_the_versioned_snapshot() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    first = await apply(
        ledger,
        await proposals.propose_create(content("weighted", weight_manual=0.25)),
    )
    update = await proposals.propose_update(
        first.family_id,
        first.content.model_copy(update={"weight_manual": 0.9}),
    )
    second = await apply(ledger, update, principal="operator-weight")
    assert first.content.weight_manual == 0.25
    assert second.content.weight_manual == 0.9
    assert (await ledger.get_head(first.family_id)).revision_id == second.revision_id


@pytest.mark.asyncio
async def test_ledger_rejects_legacy_id_collision_even_with_different_idempotency_keys() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    first_content = content(legacy_ids={"memory_id": "legacy-1"})
    first = await apply(ledger, await service.propose_create(first_content, idempotency_key="create-1"))
    with pytest.raises(LedgerConflictError):
        await service.propose_create(
            content("other", legacy_ids={"memory_id": "legacy-1"}),
            idempotency_key="create-2",
        )
    replay = await service.propose_create(first_content, idempotency_key="create-1")
    assert replay.status.value == "applied"
    assert replay.applied_revision_id == first.revision_id


@pytest.mark.asyncio
async def test_candidate_proposal_has_stable_legacy_id_and_idempotency() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    candidate = MemoryCandidate(
        project="DecisionsSearch",
        type="DesignRule",
        title="Stable candidate",
        summary="A candidate with a stable identity",
    )
    admission = {"action": "create", "status": "proposed"}
    first = await service.propose_candidate(candidate, admission)
    second = await service.propose_candidate(candidate, admission)
    assert first.idempotency_key == second.idempotency_key
    assert first.preview_hash == second.preview_hash
    assert dict(first.after.legacy_ids)["memory_id"]


@pytest.mark.asyncio
async def test_existing_family_keeps_legacy_identity_and_rejects_replacement() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    first = await apply(
        ledger,
        await service.propose_create(content("stable", legacy_ids={"memory_id": "legacy-stable"})),
    )
    update = await service.propose_update(first.family_id, content("renamed"))
    assert dict(update.after.legacy_ids)["memory_id"] == "legacy-stable"
    revised = await apply(ledger, update, principal="operator-update")
    projected = revision_to_legacy_view(revised)
    assert projected["memory_id"] == "legacy-stable"

    with pytest.raises(LedgerConflictError):
        await service.propose_update(
            first.family_id,
            content("renamed-again", legacy_ids={"memory_id": "another-family"}),
        )


@pytest.mark.asyncio
async def test_field_origin_must_match_the_final_snapshot() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    left = await apply(ledger, await service.propose_create(content("left", "same")))
    right = await apply(ledger, await service.propose_create(content("right", "same")))
    left_head = await ledger.get_head(left.family_id)
    right_head = await ledger.get_head(right.family_id)
    assert left_head and right_head

    with pytest.raises(LedgerConflictError):
        await service.propose_merge(
            left.family_id,
            content("synthesized", "same"),
            expected_heads=(
                (left.family_id, "semantic", "semantic", left_head.revision_id),
                (right.family_id, "semantic", "semantic", right_head.revision_id),
            ),
            source_revision_ids=(left.revision_id, right.revision_id),
            field_origins=(FieldOrigin(field="title", source_revision_id=left.revision_id),),
        )


@pytest.mark.asyncio
async def test_usage_hash_is_verified_and_only_procedural_revisions_accept_usage() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    semantic = await apply(ledger, await service.propose_create(content("semantic")))
    observation = {
        "procedure_family_id": semantic.family_id,
        "procedure_revision_id": semantic.revision_id,
        "success": True,
        "correlation_id": "c",
        "idempotency_key": "usage-bad",
        "payload_hash": usage_payload_hash(
            procedure_family_id=semantic.family_id,
            procedure_revision_id=semantic.revision_id,
            success=True,
            correlation_id="c",
            actor_id="operator",
            result="",
        ),
        "actor_id": "operator",
    }
    from decisionssearch.domain import UsageObservation

    with pytest.raises(LedgerConflictError):
        await ledger.record_usage_observation(UsageObservation(**observation))


@pytest.mark.asyncio
async def test_negation_is_not_treated_as_a_refinement() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    left = await apply(ledger, await service.propose_create(content("left", "use cache")))
    middle = await apply(ledger, await service.propose_create(content("middle", "use local cache")))
    right = await apply(ledger, await service.propose_create(content("right", "never cache")))
    heads = []
    for item in (left, middle, right):
        head = await ledger.get_head(item.family_id)
        heads.append((item.family_id, "semantic", "semantic", head.revision_id))
    merge = await service.propose_merge(
        left.family_id,
        content("merged", "use local cache"),
        expected_heads=(heads[0], heads[2]),
        source_revision_ids=(left.revision_id, right.revision_id),
    )
    assert merge.conflicts


@pytest.mark.asyncio
async def test_merge_conflict_detector_covers_title_and_examples() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    left = await apply(
        ledger,
        await service.propose_create(
            content("Cache local", "same", examples=("Redis",))
        ),
    )
    right = await apply(
        ledger,
        await service.propose_create(
            content("Cache distribuído", "same", examples=("Memcached",))
        ),
    )
    left_head = await ledger.get_head(left.family_id)
    right_head = await ledger.get_head(right.family_id)
    merge = await service.propose_merge(
        left.family_id,
        content("Cache unificado", "same", examples=("Redis",)),
        expected_heads=(
            (left.family_id, "semantic", "semantic", left_head.revision_id),
            (right.family_id, "semantic", "semantic", right_head.revision_id),
        ),
        source_revision_ids=(left.revision_id, right.revision_id),
    )
    assert merge.status.value == "conflicted"
    assert {item.claim_path for item in merge.conflicts} >= {"title", "examples"}


@pytest.mark.asyncio
async def test_episode_related_memory_becomes_canonical_relation() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    target = await apply(
        ledger,
        await service.propose_create(content("target", legacy_ids={"memory_id": "target-1"})),
    )
    episodes = EpisodicMemoryService(proposal_service=service, ledger=ledger)
    episode = EpisodicMemory(
        episode_id="episode-related",
        project="DecisionsSearch",
        task_description="learned target",
        related_memory_ids=["target-1"],
    )
    pending = await episodes.create_episode(episode)
    result = await apply(ledger, await ledger.get_proposal(uuid.UUID(pending["proposal_id"])))
    relations = await ledger.list_relations()
    assert any(
        relation.source_family_id == result.family_id
        and relation.target_family_id == target.family_id
        and relation.relation_type == "LEARNED_FROM"
        for relation in relations
    )


def test_ledger_model_copy_revalidates_immutable_invariants() -> None:
    item = MemoryContent(
        project="p",
        category="Rule",
        title="title",
        summary="summary",
        memory_scope=MemoryScope.PROCEDURAL,
        payload_schema="procedural.v1",
        structured_payload={"steps": ["one"]},
    )
    with pytest.raises(ValueError):
        item.model_copy(update={"structured_payload_json": "[]"})
    with pytest.raises(ValueError):
        item.model_copy(update={"valid_from": datetime.now()})


@pytest.mark.asyncio
async def test_conflict_resolution_must_match_claim_and_member_value() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    left = await apply(ledger, await service.propose_create(content("left", "SQLite")))
    right = await apply(ledger, await service.propose_create(content("right", "PostgreSQL")))
    left_head = await ledger.get_head(left.family_id)
    right_head = await ledger.get_head(right.family_id)
    blocked = await service.propose_merge(
        left.family_id,
        content("merged", "ambiguous"),
        expected_heads=(
            (left.family_id, "semantic", "semantic", left_head.revision_id),
            (right.family_id, "semantic", "semantic", right_head.revision_id),
        ),
        source_revision_ids=(left.revision_id, right.revision_id),
    )
    conflict = blocked.conflicts[0]
    with pytest.raises(LedgerConflictError):
        await service.propose_resolve_conflict(
            left.family_id,
            content("resolved", "SQLite"),
            resolutions=(
                {
                    "conflict_id": conflict.conflict_id,
                    "expected_conflict_version": conflict.version,
                    "claim_path": "wrong.path",
                    "decision": "choose",
                    "chosen_value_hash": conflict.members[0].normalized_value_hash,
                    "reason": "wrong claim",
                },
            ),
        )
    with pytest.raises(LedgerConflictError):
        await service.propose_resolve_conflict(
            left.family_id,
            content("resolved", "SQLite"),
            resolutions=(
                {
                    "conflict_id": conflict.conflict_id,
                    "expected_conflict_version": conflict.version,
                    "claim_path": conflict.claim_path,
                    "decision": "choose",
                    "chosen_value_hash": "sha256:not-a-member",
                    "reason": "wrong value",
                },
            ),
        )


@pytest.mark.asyncio
async def test_link_replay_returns_the_same_relation() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    left = await apply(ledger, await service.propose_create(content("left")))
    right = await apply(ledger, await service.propose_create(content("right")))
    proposal = await service.propose_link(left.family_id, right.family_id, "REFINES")
    approval = await LocalApprovalBoundary(ledger).approve(
        proposal.proposal_id,
        principal_id="operator-link",
        preview_hash=proposal.preview_hash,
    )
    first = await LedgerApplyService(ledger).apply(proposal.proposal_id, approval.approval_id)
    replay = await LedgerApplyService(ledger).apply(proposal.proposal_id, approval.approval_id)
    assert first.assertion_id == replay.assertion_id


@pytest.mark.asyncio
async def test_link_rejects_unregistered_relation_type() -> None:
    ledger = InMemoryMemoryLedger()
    service = ProposalService(ledger)
    left = await apply(ledger, await service.propose_create(content("left")))
    right = await apply(ledger, await service.propose_create(content("right")))
    with pytest.raises(ValueError):
        await service.propose_link(left.family_id, right.family_id, "invented_relation")
