from __future__ import annotations

import pytest

from decisionssearch.application.memory.ledger import (
    InMemoryMemoryLedger,
    LedgerApplyService,
    LocalApprovalBoundary,
    ProposalService,
)
from decisionssearch.application.memory.consolidation_service import ConsolidationService
from decisionssearch.application.memory.ledger.migration import LegacyMemoryMigrator
from decisionssearch.application.memory.ledger.materializer import QdrantHeadMaterializer
from decisionssearch.domain import (
    Evidence,
    EvidenceVerification,
    FieldOrigin,
    LedgerConflictError,
    LedgerOperation,
    MemoryContent,
    MemoryScope,
    ProposalStatus,
    RelationAssertion,
    MemoryAlias,
    RevisionState,
)
from decisionssearch.domain.memory.memory_item import MemoryItem, MemoryStatus
from decisionssearch.domain.memory.memory_candidate import EvidenceRef, MemoryCandidate


def _content(title: str = "Regra original", summary: str = "Resumo") -> MemoryContent:
    return MemoryContent(
        project="DecisionsSearch",
        category="BusinessRule",
        title=title,
        summary=summary,
        domain=("memory",),
        memory_scope=MemoryScope.SEMANTIC,
        memory_branch="semantic",
    )


async def _apply(ledger: InMemoryMemoryLedger, proposal):
    approval = await LocalApprovalBoundary(ledger).approve(
        proposal.proposal_id,
        principal_id="operator-1",
        preview_hash=proposal.preview_hash,
        comment="A alteração faz sentido.",
    )
    return await LedgerApplyService(ledger).apply(proposal.proposal_id, approval.approval_id)


@pytest.mark.asyncio
async def test_create_update_preserves_previous_revision_and_shows_diff() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    evidence = Evidence(
        source_kind="commit",
        source_locator="abc123",
        source_hash="sha256:abc123",
        verification=EvidenceVerification.VERIFIED,
    )

    create = await proposals.propose_create(
        _content(), requested_by="agent-1", evidence=(evidence,), reason="Importação inicial"
    )
    assert create.status is ProposalStatus.PENDING_APPROVAL
    assert create.before == ()
    assert create.after == _content()
    assert any(item.field == "title" for item in create.field_diff)

    first = await _apply(ledger, create)
    family_id = first.family_id
    first_snapshot = first.content.model_dump(mode="json")
    family = await ledger.get_family(family_id)
    assert family is not None and family.legacy_memory_id
    stable_alias = await ledger.resolve_alias(family.legacy_memory_id)
    assert stable_alias is not None and stable_alias.family_id == family_id

    update = await proposals.propose_update(
        family_id,
        _content(title="Regra revisada", summary="Resumo atualizado"),
        evidence=(evidence,),
        reason="Commit alterou a regra",
    )
    assert update.before[0] == first.content
    assert any(item.field == "title" for item in update.field_diff)

    second = await _apply(ledger, update)
    assert second.parent_revision_ids == (first.revision_id,)
    assert first.content.model_dump(mode="json") == first_snapshot
    assert (await ledger.get_view(first.revision_id)).state is RevisionState.SUPERSEDED
    assert (await ledger.get_view(second.revision_id)).state is RevisionState.ACTIVE
    assert len(await ledger.list_outbox()) == 2
    assert len(ledger.evidences) == 1
    updated_alias = await ledger.resolve_alias(family.legacy_memory_id)
    assert updated_alias is not None and updated_alias.family_id == family_id


@pytest.mark.asyncio
async def test_agent_cannot_approve_and_approval_is_one_time() -> None:
    ledger = InMemoryMemoryLedger()
    proposal = await ProposalService(ledger).propose_create(_content())
    boundary = LocalApprovalBoundary(ledger)

    with pytest.raises(Exception):
        await boundary.approve(
            proposal.proposal_id,
            principal_id="agent-1",
            principal_type="agent",
            preview_hash=proposal.preview_hash,
        )

    approval = await boundary.approve(
        proposal.proposal_id,
        principal_id="human-1",
        preview_hash=proposal.preview_hash,
    )
    revision = await LedgerApplyService(ledger).apply(proposal.proposal_id, approval.approval_id)
    repeated = await LedgerApplyService(ledger).apply(proposal.proposal_id, approval.approval_id)
    assert repeated == revision


@pytest.mark.asyncio
async def test_stale_proposal_cannot_overwrite_new_head() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    first = await _apply(ledger, await proposals.propose_create(_content()))
    stale = await proposals.propose_update(first.family_id, _content(title="Alteração A"))
    current = await _apply(
        ledger,
        await proposals.propose_update(first.family_id, _content(title="Alteração B")),
    )
    assert current.parent_revision_ids == (first.revision_id,)

    approval = await LocalApprovalBoundary(ledger).approve(
        stale.proposal_id,
        principal_id="human-1",
        preview_hash=stale.preview_hash,
    )
    with pytest.raises(LedgerConflictError):
        await LedgerApplyService(ledger).apply(stale.proposal_id, approval.approval_id)
    head = await ledger.get_head(first.family_id)
    assert head is not None and head.revision_id == current.revision_id


@pytest.mark.asyncio
async def test_merge_has_multiple_parents_and_field_lineage() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    left = await _apply(ledger, await proposals.propose_create(_content("A", "lado A")))
    right = await _apply(ledger, await proposals.propose_create(_content("B", "lado B")))
    left_head = await ledger.get_head(left.family_id)
    right_head = await ledger.get_head(right.family_id)
    assert left_head and right_head
    merged = await proposals.propose_merge(
        left.family_id,
        _content("A", "lado B"),
        expected_heads=(
            (left.family_id, "semantic", "semantic", left_head.revision_id),
            (right.family_id, "semantic", "semantic", right_head.revision_id),
        ),
        source_revision_ids=(left.revision_id, right.revision_id),
        field_origins=(
            FieldOrigin(field="summary", source_revision_id=right.revision_id),
            FieldOrigin(field="title", source_revision_id=left.revision_id),
        ),
        reason="Fusão aprovada com duas fontes",
    )
    revision = await _apply(ledger, merged)
    assert revision.parent_revision_ids == (left.revision_id, right.revision_id)
    assert merged.field_origins[0].source_revision_id == right.revision_id
    assert (await ledger.get_view(left.revision_id)).state is RevisionState.SUPERSEDED
    assert (await ledger.get_view(right.revision_id)).state is RevisionState.SUPERSEDED


@pytest.mark.asyncio
async def test_rollback_creates_new_revision_and_keeps_bad_revision() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    first = await _apply(ledger, await proposals.propose_create(_content("v1")))
    second = await _apply(
        ledger,
        await proposals.propose_update(first.family_id, _content("v2")),
    )
    head = await ledger.get_head(first.family_id)
    assert head
    rollback = await proposals.propose_rollback(
        first.family_id,
        first.revision_id,
        (first.family_id, "semantic", "semantic", head.revision_id),
    )
    restored = await _apply(ledger, rollback)
    assert restored.revision_id != first.revision_id
    assert restored.rollback_of == first.revision_id
    assert restored.parent_revision_ids == (second.revision_id,)
    assert (await ledger.get_revision(second.revision_id)).content.title == "v2"


@pytest.mark.asyncio
async def test_relation_is_a_proposal_not_a_direct_graph_write() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    left = await _apply(ledger, await proposals.propose_create(_content("A")))
    right = await _apply(ledger, await proposals.propose_create(_content("B")))
    proposal = await proposals.propose_link(left.family_id, right.family_id, "REFINES")
    assert proposal.operation is LedgerOperation.LINK
    relation = await _apply(ledger, proposal)
    assert isinstance(relation, RelationAssertion)
    assert relation.source_family_id == left.family_id
    assert relation.target_family_id == right.family_id


@pytest.mark.asyncio
async def test_admission_refine_creates_new_memory_and_refines_target_atomically() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    target_id = MemoryItem.generate_id("DecisionsSearch", "BusinessRule", "Regra original")
    target = await _apply(
        ledger,
        await proposals.propose_create(
            _content("Regra original").model_copy(update={"legacy_ids": {"memory_id": target_id}})
        ),
    )
    candidate = MemoryCandidate(
        project="DecisionsSearch",
        type="BusinessRule",
        title="Regra original refinada",
        summary="Resumo com a nova exceção",
        evidence=[EvidenceRef(type="commit", ref="abc123", snippet="regra observada")],
    )

    proposal = await proposals.propose_candidate(
        candidate,
        {
            "status": "active",
            "action": "refine",
            "memory_id": MemoryItem.generate_id(
                candidate.project, candidate.type, candidate.title
            ),
            "related_id": target_id,
        },
    )

    assert proposal.operation is LedgerOperation.CREATE_AND_LINK
    assert proposal.target_family_id is None
    assert proposal.relation_target_family_id == target.family_id
    refined = await _apply(ledger, proposal)
    relations = await ledger.list_relations()

    assert refined.family_id != target.family_id
    assert len(relations) == 1
    assert relations[0].relation_type == "REFINES"
    assert relations[0].source_family_id == refined.family_id
    assert relations[0].target_family_id == target.family_id
    applied = await ledger.get_proposal(proposal.proposal_id)
    assert applied.applied_revision_id == refined.revision_id
    assert applied.applied_relation_id == relations[0].assertion_id


@pytest.mark.asyncio
async def test_refinement_rejects_a_changed_target_without_creating_partial_family() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    target_id = MemoryItem.generate_id("DecisionsSearch", "BusinessRule", "Regra original")
    target = await _apply(
        ledger,
        await proposals.propose_create(
            _content("Regra original").model_copy(update={"legacy_ids": {"memory_id": target_id}})
        ),
    )
    candidate = MemoryCandidate(
        project="DecisionsSearch",
        type="BusinessRule",
        title="Regra nova",
        summary="Nova formula",
        evidence=[EvidenceRef(type="commit", ref="abc123")],
    )
    proposal = await proposals.propose_candidate(
        candidate,
        {"status": "active", "action": "refine", "related_id": target_id},
    )
    await _apply(ledger, await proposals.propose_update(target.family_id, _content("Regra atualizada")))

    with pytest.raises(LedgerConflictError):
        await _apply(ledger, proposal)

    assert len(ledger.families) == 1
    assert await ledger.list_relations() == []


@pytest.mark.asyncio
async def test_related_to_is_canonical_and_replayed_in_reverse_without_duplicate() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    left = await _apply(ledger, await proposals.propose_create(_content("A")))
    right = await _apply(ledger, await proposals.propose_create(_content("B")))

    first_proposal = await proposals.propose_link(left.family_id, right.family_id, "RELATED_TO")
    first_relation = await _apply(ledger, first_proposal)
    reverse_proposal = await proposals.propose_link(right.family_id, left.family_id, "RELATED_TO")

    assert reverse_proposal.proposal_id == first_proposal.proposal_id
    assert await ledger.list_relations() == [first_relation]


@pytest.mark.asyncio
async def test_deprecates_points_from_replacement_to_invalidated_memory() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    old = await _apply(ledger, await proposals.propose_create(_content("old")))
    replacement = await _apply(ledger, await proposals.propose_create(_content("replacement")))

    invalidation = await proposals.propose_state_change(
        old.family_id,
        LedgerOperation.INVALIDATE,
        replacement_family_id=replacement.family_id,
        reason="Fonte oficial substituiu a regra",
    )
    await _apply(ledger, invalidation)
    relation = next(item for item in await ledger.list_relations() if item.relation_type == "DEPRECATES")

    assert relation.source_family_id == replacement.family_id
    assert relation.target_family_id == old.family_id
    assert relation.source_revision_id == (await ledger.get_head(replacement.family_id)).revision_id
    assert relation.target_revision_id == old.revision_id


@pytest.mark.asyncio
async def test_consolidation_proposes_related_to_for_shared_context() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    await _apply(
        ledger,
        await proposals.propose_create(
            _content("Billing rule", "Validate billing")
            .model_copy(update={"related_files": ("src/billing.py",), "modules": ("billing",)})
        ),
    )
    await _apply(
        ledger,
        await proposals.propose_create(
            _content("Packing rule", "Validate packing")
            .model_copy(update={"related_files": ("src/billing.py",), "modules": ("warehouse",)})
        ),
    )

    previews = await ConsolidationService(object(), object(), proposal_service=proposals).propose_now()

    related = [item for item in previews if item["relation_type"] == "RELATED_TO"]
    assert len(related) == 1
    assert related[0]["operation"] == "link"
    assert len(await ledger.list_relations()) == 0


@pytest.mark.asyncio
async def test_qdrant_is_only_materialized_from_outbox_and_can_retry() -> None:
    class Embeddings:
        async def embed(self, text: str) -> list[float]:
            return [float(len(text))]

    class Qdrant:
        def __init__(self) -> None:
            self.calls = []
            self.fail = True

        async def upsert_revision_head(self, revision, embedding, *, ledger_sequence: int) -> None:
            if self.fail:
                self.fail = False
                raise RuntimeError("qdrant offline")
            self.calls.append((revision.revision_id, embedding, ledger_sequence))

    ledger = InMemoryMemoryLedger()
    revision = await _apply(ledger, await ProposalService(ledger).propose_create(_content()))
    qdrant = Qdrant()
    materializer = QdrantHeadMaterializer(ledger, qdrant, Embeddings())

    first = await materializer.run_once()
    assert first == {"seen": 1, "applied": 0, "failed": 1}
    assert len(await ledger.list_active_revisions()) == 1
    second = await materializer.run_once()
    assert second == {"seen": 1, "applied": 1, "failed": 0}
    assert qdrant.calls[0][0] == revision.revision_id


@pytest.mark.asyncio
async def test_invalidation_is_a_new_revision_and_removes_it_from_active_heads() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    first = await _apply(ledger, await proposals.propose_create(_content()))
    invalidation = await proposals.propose_state_change(
        first.family_id,
        LedgerOperation.INVALIDATE,
        reason="Fonte oficial revogou a regra",
    )
    invalidated = await _apply(ledger, invalidation)

    assert invalidated.revision_id != first.revision_id
    assert invalidated.content.valid_to is not None
    assert (await ledger.get_view(invalidated.revision_id)).state is RevisionState.INVALIDATED
    assert await ledger.list_active_revisions() == []
    assert (await ledger.get_view(first.revision_id)).state is RevisionState.SUPERSEDED


@pytest.mark.asyncio
async def test_merge_retires_source_family_and_redirects_its_alias() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    left = await _apply(ledger, await proposals.propose_create(_content("Regra comum")))
    right = await _apply(ledger, await proposals.propose_create(_content("Regra comum v2")))
    right_alias = await ledger.resolve_alias("missing")
    assert right_alias is None
    await ledger.add_alias(
        MemoryAlias(
            alias="legacy-right",
            family_id=right.family_id,
        )
    )
    left_head = await ledger.get_head(left.family_id)
    right_head = await ledger.get_head(right.family_id)
    assert left_head and right_head
    proposal = await proposals.propose_merge(
        left.family_id,
        _content("Regra comum", "texto consolidado"),
        expected_heads=(
            (left.family_id, "semantic", "semantic", left_head.revision_id),
            (right.family_id, "semantic", "semantic", right_head.revision_id),
        ),
        source_revision_ids=(left.revision_id, right.revision_id),
        field_origins=(FieldOrigin(field="title", source_revision_id=left.revision_id),),
        reason="Unificação aprovada",
    )
    merged = await _apply(ledger, proposal)

    assert await ledger.get_head(right.family_id) is None
    source_family = await ledger.get_family(right.family_id)
    assert source_family and source_family.merged_into_family_id == left.family_id
    assert (await ledger.resolve_alias("legacy-right")).family_id == left.family_id
    assert any(item.relation_type == "MERGED_INTO" for item in await ledger.list_relations())
    assert merged.family_id == left.family_id


@pytest.mark.asyncio
async def test_consolidation_only_proposes_duplicate_merge() -> None:
    ledger = InMemoryMemoryLedger()
    proposals = ProposalService(ledger)
    await _apply(ledger, await proposals.propose_create(_content("Cache policy", "Use cache")))
    await _apply(ledger, await proposals.propose_create(_content("Cache policy", "Use local cache")))
    service = ConsolidationService(object(), object(), proposal_service=proposals)

    previews = await service.propose_now()

    assert len(previews) == 1
    assert previews[0]["operation"] == "merge"
    assert previews[0]["status"] == "pending_approval"
    assert len(await ledger.list_active_revisions()) == 2


def test_legacy_migration_quarantines_ambiguous_aliases() -> None:
    item_a = MemoryItem(
        memory_id="legacy-1",
        project="DecisionsSearch",
        category="BusinessRule",
        title="Regra A",
        summary="A",
        status=MemoryStatus.ACTIVE,
    )
    item_b = item_a.model_copy(update={"title": "Regra B"})
    plan = LegacyMemoryMigrator().plan(
        [item_a, item_b], migration_run_id="migration-test", dry_run=True
    )

    assert plan.manifest["family_count"] == 2
    assert plan.manifest["ambiguous_alias_count"] == 1
    assert all(record.alias.family_id is None for record in plan.records)


@pytest.mark.asyncio
async def test_legacy_migration_is_deterministic_and_does_not_invent_history() -> None:
    from decisionssearch.domain import MemoryItem, MemoryStatus

    item = MemoryItem(
        memory_id="legacy-1",
        project="DecisionsSearch",
        category="BusinessRule",
        title="Regra legada",
        summary="Estado atual importado",
        status=MemoryStatus.DEPRECATED,
        evidence_count=3,
    )
    migrator = LegacyMemoryMigrator()
    first = migrator.plan([item], migration_run_id="run-1")
    second = migrator.plan([item], migration_run_id="run-1")
    assert first.manifest["source_snapshot_hash"] == second.manifest["source_snapshot_hash"]
    assert first.records[0].family.family_id == second.records[0].family.family_id
    assert first.records[0].evidence.verification is EvidenceVerification.UNAVAILABLE
    assert first.records[0].evidence.excerpt_or_hash == "legacy_evidence_count=3"

    ledger = InMemoryMemoryLedger()
    apply_plan = migrator.plan([item], migration_run_id="run-1", dry_run=False)
    await migrator.apply(apply_plan, ledger)
    await migrator.apply(apply_plan, ledger)
    assert len(ledger.families) == 1
    assert (await ledger.get_view(first.records[0].revision.revision_id)).state is RevisionState.ARCHIVED
