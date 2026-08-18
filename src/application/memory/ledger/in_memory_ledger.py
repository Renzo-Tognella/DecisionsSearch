from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from decisionssearch.domain.memory_ledger import (
    ApprovalDecision,
    ApprovalStatus,
    ChangeProposal,
    ConflictCase,
    ConflictStatus,
    Evidence,
    EvidenceLinkSpec,
    EvidenceStance,
    FamilyState,
    LedgerOperation,
    MemoryAlias,
    MemoryAliasStatus,
    MemoryFamily,
    MemoryHead,
    MemoryRevision,
    MemoryRevisionView,
    MemoryScope,
    MergeHeadSnapshot,
    MergeManifest,
    OutboxEvent,
    OutboxStatus,
    ProposalStatus,
    RelationAssertion,
    RelationState,
    RevisionEvidence,
    RevisionState,
    RevisionTransition,
    UsageObservation,
    canonical_json,
    content_hash,
    legacy_memory_id_for_family,
    usage_payload_hash,
)
from decisionssearch.domain.shared.exceptions import (
    ApprovalError,
    LedgerConflictError,
    MemoryServiceError,
    ProposalNotFoundError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


HeadKey = tuple[uuid.UUID, str, str]


class InMemoryMemoryLedger:
    """Ledger de referência usado por testes, CLI local e contratos.

    Ele implementa as mesmas invariantes do adaptador Neo4j: revisão append-only,
    CAS por head, aprovação de uso único e outbox criado na aplicação. Não é uma
    promessa de durabilidade para o modo ``light``; esse modo continua não sendo
    fonte autoritativa até existir um ledger SQLite transacional.
    """

    def __init__(self) -> None:
        self.families: dict[uuid.UUID, MemoryFamily] = {}
        self.revisions: dict[uuid.UUID, MemoryRevision] = {}
        self.heads: dict[HeadKey, MemoryHead] = {}
        self.aliases: dict[str, list[MemoryAlias]] = defaultdict(list)
        self.evidences: dict[uuid.UUID, Evidence] = {}
        self.revision_evidence: list[RevisionEvidence] = []
        self.conflict_cases: dict[str, ConflictCase] = {}
        self.merge_manifests: dict[uuid.UUID, MergeManifest] = {}
        self.usage_observations: dict[uuid.UUID, UsageObservation] = {}
        self._usage_idempotency: dict[str, uuid.UUID] = {}
        self.proposals: dict[uuid.UUID, ChangeProposal] = {}
        self.approvals: dict[uuid.UUID, ApprovalDecision] = {}
        self.transitions: list[RevisionTransition] = []
        self.outbox: dict[uuid.UUID, OutboxEvent] = {}
        self.relations: dict[uuid.UUID, RelationAssertion] = {}
        self._idempotency: dict[str, uuid.UUID] = {}
        self._sequence = 0
        self._lock = asyncio.Lock()

    def export_state(self) -> dict:
        """Snapshot JSON para testes/reexecuções locais; não substitui Neo4j."""

        return {
            "families": [item.model_dump(mode="json") for item in self.families.values()],
            "revisions": [item.model_dump(mode="json") for item in self.revisions.values()],
            "heads": [item.model_dump(mode="json") for item in self.heads.values()],
            "aliases": [item.model_dump(mode="json") for rows in self.aliases.values() for item in rows],
            "evidences": [item.model_dump(mode="json") for item in self.evidences.values()],
            "revision_evidence": [item.model_dump(mode="json") for item in self.revision_evidence],
            "conflict_cases": [item.model_dump(mode="json") for item in self.conflict_cases.values()],
            "merge_manifests": [item.model_dump(mode="json") for item in self.merge_manifests.values()],
            "usage_observations": [item.model_dump(mode="json") for item in self.usage_observations.values()],
            "proposals": [item.model_dump(mode="json") for item in self.proposals.values()],
            "approvals": [item.model_dump(mode="json") for item in self.approvals.values()],
            "transitions": [item.model_dump(mode="json") for item in self.transitions],
            "outbox": [item.model_dump(mode="json") for item in self.outbox.values()],
            "relations": [item.model_dump(mode="json") for item in self.relations.values()],
            "sequence": self._sequence,
        }

    def restore_state(self, payload: dict) -> None:
        """Restaura um snapshot produzido por :meth:`export_state`."""

        self.families = {
            item.family_id: item
            for item in (MemoryFamily.model_validate(row) for row in payload.get("families", []))
        }
        self.revisions = {
            item.revision_id: item
            for item in (MemoryRevision.model_validate(row) for row in payload.get("revisions", []))
        }
        self.heads = {}
        for row in payload.get("heads", []):
            item = MemoryHead.model_validate(row)
            self.heads[self._head_key(item.family_id, item.memory_scope, item.memory_branch)] = item
        self.aliases = defaultdict(list)
        for row in payload.get("aliases", []):
            item = MemoryAlias.model_validate(row)
            self.aliases[item.alias].append(item)
        self.evidences = {
            item.evidence_id: item
            for item in (Evidence.model_validate(row) for row in payload.get("evidences", []))
        }
        self.revision_evidence = [
            RevisionEvidence.model_validate(row) for row in payload.get("revision_evidence", [])
        ]
        self.conflict_cases = {
            item.conflict_id: item
            for item in (ConflictCase.model_validate(row) for row in payload.get("conflict_cases", []))
        }
        self.merge_manifests = {
            item.manifest_id: item
            for item in (MergeManifest.model_validate(row) for row in payload.get("merge_manifests", []))
        }
        self.usage_observations = {
            item.observation_id: item
            for item in (UsageObservation.model_validate(row) for row in payload.get("usage_observations", []))
        }
        self._usage_idempotency = {
            item.idempotency_key: item.observation_id
            for item in self.usage_observations.values()
        }
        self.proposals = {
            item.proposal_id: item
            for item in (ChangeProposal.model_validate(row) for row in payload.get("proposals", []))
        }
        self.approvals = {
            item.approval_id: item
            for item in (ApprovalDecision.model_validate(row) for row in payload.get("approvals", []))
        }
        self.transitions = [RevisionTransition.model_validate(row) for row in payload.get("transitions", [])]
        self.outbox = {
            item.event_id: item
            for item in (OutboxEvent.model_validate(row) for row in payload.get("outbox", []))
        }
        self.relations = {
            item.assertion_id: item
            for item in (RelationAssertion.model_validate(row) for row in payload.get("relations", []))
        }
        self._sequence = int(payload.get("sequence", 0))
        self._idempotency = {
            item.idempotency_key: item.proposal_id
            for item in self.proposals.values()
            if item.idempotency_key
        }

    def save_snapshot(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.export_state(), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _head_key(family_id: uuid.UUID, scope: str | MemoryScope, branch: str) -> HeadKey:
        return family_id, str(scope), branch

    async def get_family(self, family_id: uuid.UUID) -> MemoryFamily | None:
        return self.families.get(family_id)

    async def get_head(
        self,
        family_id: uuid.UUID,
        scope: MemoryScope | str = MemoryScope.SEMANTIC,
        branch: str = "semantic",
    ) -> MemoryHead | None:
        return self.heads.get(self._head_key(family_id, scope, branch))

    async def get_current_head(
        self,
        family_id: uuid.UUID,
        scope: MemoryScope | str | None = None,
        branch: str | None = None,
    ) -> MemoryHead | None:
        candidates = [
            item
            for item in self.heads.values()
            if item.family_id == family_id
            and (scope is None or str(item.memory_scope) == str(scope))
            and (branch is None or item.memory_branch == branch)
        ]
        return max(candidates, key=lambda item: item.sequence, default=None)

    async def get_revision(self, revision_id: uuid.UUID) -> MemoryRevision | None:
        return self.revisions.get(revision_id)

    async def get_proposal(self, proposal_id: uuid.UUID) -> ChangeProposal:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(
                "Proposta não encontrada", context={"proposal_id": str(proposal_id)}
            )
        return proposal

    async def get_proposal_by_idempotency(self, idempotency_key: str) -> ChangeProposal | None:
        proposal_id = self._idempotency.get(idempotency_key)
        return self.proposals.get(proposal_id) if proposal_id else None

    async def get_approval(self, approval_id: uuid.UUID) -> ApprovalDecision | None:
        return self.approvals.get(approval_id)

    async def save_proposal(self, proposal: ChangeProposal) -> ChangeProposal:
        async with self._lock:
            if proposal.idempotency_key and proposal.idempotency_key in self._idempotency:
                existing = self.proposals[self._idempotency[proposal.idempotency_key]]
                if existing.preview_hash != proposal.preview_hash:
                    raise LedgerConflictError(
                        "A chave de idempotência já foi usada para outro preview",
                        context={"idempotency_key": proposal.idempotency_key},
                    )
                return existing
            existing = self.proposals.get(proposal.proposal_id)
            if existing is not None and existing.preview_hash != proposal.preview_hash:
                raise LedgerConflictError("proposal_id já existe com outro preview")
            self.proposals[proposal.proposal_id] = proposal
            for conflict in proposal.conflicts:
                existing_conflict = self.conflict_cases.get(conflict.conflict_id)
                if existing_conflict and existing_conflict.snapshot_hash != conflict.snapshot_hash:
                    raise LedgerConflictError(
                        "O conflito já existe com outro snapshot",
                        context={"conflict_id": conflict.conflict_id},
                    )
                self.conflict_cases[conflict.conflict_id] = conflict
            if proposal.idempotency_key:
                self._idempotency[proposal.idempotency_key] = proposal.proposal_id
            return proposal

    async def save_approval(self, approval: ApprovalDecision) -> ApprovalDecision:
        async with self._lock:
            proposal = await self.get_proposal(approval.proposal_id)
            if proposal.status is not ProposalStatus.PENDING_APPROVAL:
                raise ApprovalError(
                    "A proposta não está pendente de aprovação",
                    context={"proposal_id": str(proposal.proposal_id), "status": proposal.status.value},
                )
            if approval.preview_hash != proposal.preview_hash:
                raise ApprovalError(
                    "O hash aprovado não corresponde ao preview",
                    context={"proposal_id": str(proposal.proposal_id)},
                )
            if approval.expected_heads != proposal.expected_heads:
                raise ApprovalError("A aprovação não confirma os mesmos heads do preview")
            if approval.expires_at and approval.expires_at <= utc_now():
                raise ApprovalError("A aprovação expirou")
            existing = self.approvals.get(approval.approval_id)
            if existing is not None:
                if existing.model_dump(mode="json") != approval.model_dump(mode="json"):
                    raise ApprovalError("approval_id já existe com outro conteúdo")
                return existing
            self.approvals[approval.approval_id] = approval
            self.proposals[proposal.proposal_id] = proposal.model_copy(
                update={"status": ProposalStatus.APPROVED}
            )
            return approval

    async def reject_proposal(
        self,
        proposal_id: uuid.UUID,
        reason: str,
        *,
        principal_id: str,
        principal_type: str = "operator",
    ) -> ChangeProposal:
        async with self._lock:
            proposal = await self.get_proposal(proposal_id)
            if proposal.status is not ProposalStatus.PENDING_APPROVAL:
                raise ApprovalError(
                    "Somente propostas pendentes podem ser rejeitadas",
                    context={"proposal_id": str(proposal_id), "status": proposal.status.value},
                )
            clean_reason = reason.strip()
            if not clean_reason:
                raise ApprovalError("O motivo da rejeição é obrigatório")
            if (
                not principal_id.strip()
                or principal_id.strip().casefold().startswith(("agent", "system", "anonymous"))
                or principal_type.strip().casefold() in {"agent", "system", "anonymous"}
            ):
                raise ApprovalError("A rejeição exige um principal operador separado")
            updated = proposal.model_copy(
                update={
                    "status": ProposalStatus.REJECTED,
                    "reason": f"{proposal.reason} | {clean_reason}",
                    "rejected_by": principal_id,
                    "rejected_by_type": principal_type,
                    "rejected_at": utc_now(),
                }
            )
            self.proposals[proposal_id] = updated
            return updated

    async def current_head_matches(
        self, expected_heads: Iterable[tuple[uuid.UUID, str, str, uuid.UUID]]
    ) -> bool:
        for family_id, scope, branch, revision_id in expected_heads:
            head = self.heads.get(self._head_key(family_id, scope, branch))
            if head is None or head.revision_id != revision_id:
                return False
        return True

    async def apply_approved(
        self,
        proposal_id: uuid.UUID,
        approval_id: uuid.UUID,
    ) -> MemoryRevision | RelationAssertion:
        """Aplica uma aprovação em uma seção crítica única.

        A implementação em memória representa a transação canônica. O adaptador
        Neo4j usa o mesmo contrato com uma transação gerenciada no banco.
        """

        async with self._lock:
            proposal = await self.get_proposal(proposal_id)
            approval = self.approvals.get(approval_id)
            if approval is None or approval.proposal_id != proposal_id:
                raise ApprovalError("Aprovação inválida para a proposta")
            if approval.status is ApprovalStatus.CONSUMED:
                if proposal.applied_revision_id and proposal.applied_revision_id in self.revisions:
                    return self.revisions[proposal.applied_revision_id]
                if proposal.applied_relation_id and proposal.applied_relation_id in self.relations:
                    return self.relations[proposal.applied_relation_id]
                raise ApprovalError("Aprovação já consumida")
            if proposal.status is ProposalStatus.APPLIED and proposal.applied_revision_id:
                return self.revisions[proposal.applied_revision_id]
            if proposal.status is ProposalStatus.APPLIED and proposal.applied_relation_id:
                return self.relations[proposal.applied_relation_id]
            if proposal.status is not ProposalStatus.APPROVED:
                raise ApprovalError(
                    "A proposta não pode ser aplicada",
                    context={"proposal_id": str(proposal_id), "status": proposal.status.value},
                )
            if approval.preview_hash != proposal.preview_hash:
                raise ApprovalError("O preview mudou desde a aprovação")
            if proposal.expires_at and proposal.expires_at <= utc_now():
                self.proposals[proposal_id] = proposal.model_copy(update={"status": ProposalStatus.EXPIRED})
                raise ApprovalError("A proposta expirou")
            if not await self.current_head_matches(proposal.expected_heads):
                self.proposals[proposal_id] = proposal.model_copy(update={"status": ProposalStatus.STALE})
                raise LedgerConflictError(
                    "A revisão-base deixou de ser o head atual",
                    context={"proposal_id": str(proposal_id), "expected_heads": str(proposal.expected_heads)},
                )
            if approval.expected_heads != proposal.expected_heads:
                raise ApprovalError("A aprovação não confirma os mesmos heads do preview")
            if proposal.conflict_ids and proposal.operation is not LedgerOperation.RESOLVE_CONFLICT:
                self.proposals[proposal_id] = proposal.model_copy(update={"status": ProposalStatus.CONFLICTED})
                raise LedgerConflictError("A proposta contém conflitos não resolvidos")

            if proposal.operation is LedgerOperation.RESOLVE_CONFLICT:
                for resolution in proposal.conflict_resolutions:
                    conflict = self.conflict_cases.get(resolution.conflict_id)
                    if (
                        conflict is None
                        or conflict.status is not ConflictStatus.OPEN
                        or conflict.version != resolution.expected_conflict_version
                    ):
                        raise LedgerConflictError("O caso de conflito mudou antes da resolução")

            if proposal.operation is LedgerOperation.UNMERGE:
                return self._apply_unmerge(proposal, approval)

            if proposal.operation is LedgerOperation.LINK:
                relation = self._build_relation(proposal, approval)
                if any(
                    existing.relation_type == relation.relation_type
                    and (
                        (
                            existing.source_family_id == relation.source_family_id
                            and existing.target_family_id == relation.target_family_id
                        )
                        or (
                            relation.relation_type == "RELATED_TO"
                            and existing.source_family_id == relation.target_family_id
                            and existing.target_family_id == relation.source_family_id
                        )
                    )
                    and existing.state is RelationState.ACTIVE
                    for existing in self.relations.values()
                ):
                    raise LedgerConflictError("A relação ativa já existe")
                relation_event = self._new_outbox(
                    event_type="memory.relation.applied",
                    family_id=relation.source_family_id,
                    revision_id=None,
                    content_hash="sha256:" + hashlib.sha256(
                        canonical_json(relation).encode("utf-8")
                    ).hexdigest(),
                    payload=(
                        ("operation", proposal.operation.value),
                        ("assertion_id", str(relation.assertion_id)),
                    ),
                )
                self.relations[relation.assertion_id] = relation
                self.outbox[relation_event.event_id] = relation_event
                self._sequence = relation_event.sequence
                self._consume(proposal, approval, applied_relation_id=relation.assertion_id)
                return relation

            content = proposal.after
            if content is None:
                raise MemoryServiceError("Proposta de memória não possui snapshot depois")
            for evidence in proposal.evidence:
                existing_evidence = self.evidences.get(evidence.evidence_id)
                if existing_evidence is not None and existing_evidence.fingerprint != evidence.fingerprint:
                    raise LedgerConflictError(
                        "evidence_id já existe com outro conteúdo",
                        context={"evidence_id": str(evidence.evidence_id)},
                    )

            create_link_target_family = None
            create_link_target_head = None
            if proposal.operation is LedgerOperation.CREATE_AND_LINK:
                target_family_id = proposal.relation_target_family_id
                if target_family_id is None:
                    raise LedgerConflictError("Refinamento sem família alvo")
                create_link_target_family = self.families.get(target_family_id)
                if create_link_target_family is None or create_link_target_family.state is not FamilyState.ACTIVE:
                    raise LedgerConflictError("A família alvo do refinamento não está ativa")
                if (
                    create_link_target_family.project != content.project
                    or create_link_target_family.category != content.category
                    or create_link_target_family.memory_scope is not content.memory_scope
                ):
                    raise LedgerConflictError(
                        "A família alvo do refinamento não é compatível com o conteúdo"
                    )
                create_link_target_head = self.heads.get(
                    self._head_key(target_family_id, content.memory_scope, content.memory_branch)
                )
                if create_link_target_head is None:
                    raise LedgerConflictError("A família alvo do refinamento não possui head")
                if not any(
                    expected[0] == target_family_id
                    and expected[3] == create_link_target_head.revision_id
                    for expected in proposal.expected_heads
                ):
                    raise LedgerConflictError("O head alvo do refinamento não foi congelado no preview")

            if proposal.operation in {LedgerOperation.CREATE, LedgerOperation.CREATE_AND_LINK} and proposal.target_family_id is None:
                family = MemoryFamily(
                    project=content.project,
                    category=content.category,
                    memory_scope=content.memory_scope,
                    created_by=approval.principal_id,
                )
                legacy_id = dict(content.legacy_ids).get("memory_id") or dict(content.legacy_ids).get(
                    "episode_id"
                ) or dict(content.legacy_ids).get("procedure_id")
                family = family.model_copy(
                    update={
                        "legacy_memory_id": legacy_id
                        or legacy_memory_id_for_family(family.family_id)
                    }
                )
                self.families[family.family_id] = family
                family_id = family.family_id
            else:
                family_id = proposal.target_family_id
                if family_id is None or family_id not in self.families:
                    raise MemoryServiceError("Família alvo não encontrada")
                family = self.families[family_id]
                if family.state is not FamilyState.ACTIVE:
                    raise LedgerConflictError("A família alvo não está ativa")

            if not family.legacy_memory_id:
                family = family.model_copy(
                    update={"legacy_memory_id": legacy_memory_id_for_family(family.family_id)}
                )
            alias = MemoryAlias(
                alias=family.legacy_memory_id,
                family_id=family.family_id,
                project=family.project,
                category=family.category,
                memory_branch=content.memory_branch,
            )
            if alias not in self.aliases[alias.alias]:
                self.aliases[alias.alias].append(alias)

            parent_ids = proposal.base_revision_ids
            if any(parent not in self.revisions for parent in parent_ids):
                raise LedgerConflictError("Uma revisão pai não existe no ledger")
            parent_versions = [self.revisions[parent].version for parent in parent_ids]
            version = max(parent_versions, default=0) + 1
            proposal_links = proposal.evidence_links or tuple(
                EvidenceLinkSpec(
                    evidence_id=evidence.evidence_id,
                    stance=EvidenceStance.SUPPORTS,
                    confidence=evidence.source_reliability,
                )
                for evidence in proposal.evidence
            )
            revision = MemoryRevision(
                family_id=family_id,
                version=version,
                parent_revision_ids=parent_ids,
                source_revision_ids=proposal.source_revision_ids,
                content=content,
                content_hash=content_hash(content),
                actor_id=approval.principal_id,
                actor_type=approval.principal_type,
                reason=proposal.reason,
                evidence_ids=proposal.evidence_ids,
                rollback_of=proposal.restore_revision_id,
                field_origins=proposal.field_origins,
                evidence_link_ids=(),
                conflict_ids=proposal.conflict_ids,
                merge_manifest_id=(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"decisionssearch:merge-manifest:{proposal.proposal_id}")
                    if proposal.operation is LedgerOperation.MERGE
                    else None
                ),
            )
            evidence_link_ids = tuple(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"decisionssearch:evidence-link:{revision.revision_id}:{link.evidence_id}:{link.claim_path}:{link.stance.value}",
                )
                for link in proposal_links
            )
            revision = revision.model_copy(
                update={
                    "evidence_link_ids": evidence_link_ids,
                    "provenance_hash": self._provenance_hash(revision, proposal),
                }
            )
            evidence_links = [
                RevisionEvidence(
                    link_id=link_id,
                    revision_id=revision.revision_id,
                    evidence_id=link.evidence_id,
                    stance=link.stance,
                    confidence=link.confidence,
                    claim_path=link.claim_path,
                    excerpt_hash=link.excerpt_hash,
                )
                for link_id, link in zip(evidence_link_ids, proposal_links)
            ]
            target_state = (
                RevisionState.INVALIDATED
                if proposal.operation is LedgerOperation.INVALIDATE
                else RevisionState.ARCHIVED
                if proposal.operation is LedgerOperation.ARCHIVE
                else RevisionState.SUPERSEDED
                if proposal.operation is LedgerOperation.SUPERSEDE
                else RevisionState.ACTIVE
            )

            merge_sources: list[tuple[uuid.UUID, MemoryRevision]] = []
            if proposal.operation is LedgerOperation.MERGE:
                for source_revision_id in proposal.source_revision_ids:
                    source_revision = self.revisions.get(source_revision_id)
                    if source_revision is None:
                        raise LedgerConflictError("Uma revisão de origem da fusão não existe")
                    if source_revision.family_id != family_id:
                        merge_sources.append((source_revision.family_id, source_revision))
                expected_by_family = {item[0]: item for item in proposal.expected_heads}
                if {item[0] for item in proposal.expected_heads} != {
                    revision.family_id for revision in [self.revisions[item] for item in proposal.source_revision_ids]
                }:
                    raise LedgerConflictError("O merge não cobre exatamente as famílias esperadas")
                for source_revision in [self.revisions[item] for item in proposal.source_revision_ids]:
                    expected = expected_by_family.get(source_revision.family_id)
                    if expected is None or expected[3] != source_revision.revision_id:
                        raise LedgerConflictError("A revisão de origem deixou de ser o head exato")

            sequence = self._sequence + 1
            head_key = self._head_key(family_id, content.memory_scope, content.memory_branch)
            new_head = MemoryHead(
                family_id=family_id,
                memory_scope=content.memory_scope,
                memory_branch=content.memory_branch,
                revision_id=revision.revision_id,
                sequence=sequence,
            )
            transitions = [
                RevisionTransition(
                    family_id=self.revisions[parent_id].family_id,
                    from_revision_ids=(parent_id,),
                    to_revision_id=revision.revision_id,
                    state=RevisionState.SUPERSEDED,
                    reason=proposal.reason,
                    actor_id=approval.principal_id,
                    actor_type=approval.principal_type,
                    proposal_id=proposal.proposal_id,
                )
                for parent_id in parent_ids
            ]
            transitions.append(
                RevisionTransition(
                    family_id=family_id,
                    from_revision_ids=parent_ids,
                    to_revision_id=revision.revision_id,
                    state=target_state,
                    reason=proposal.reason,
                    actor_id=approval.principal_id,
                    actor_type=approval.principal_type,
                    proposal_id=proposal.proposal_id,
                )
            )
            merge_relations = [
                RelationAssertion(
                    source_family_id=source_family_id,
                    target_family_id=family_id,
                    source_revision_id=source_revision.revision_id,
                    target_revision_id=revision.revision_id,
                    relation_type="MERGED_INTO",
                    memory_scope=content.memory_scope,
                    memory_branch=content.memory_branch,
                    created_by=approval.principal_id,
                    evidence_ids=proposal.evidence_ids,
                    proposal_id=proposal.proposal_id,
                )
                for source_family_id, source_revision in merge_sources
            ]
            merge_manifest: MergeManifest | None = None
            if proposal.operation is LedgerOperation.MERGE:
                source_family_ids = tuple(dict.fromkeys(item[0] for item in merge_sources))
                affected_family_ids = tuple(dict.fromkeys((family_id, *source_family_ids)))
                head_snapshots = tuple(
                    MergeHeadSnapshot(
                        family_id=family_id_item,
                        memory_scope=head.memory_scope,
                        memory_branch=head.memory_branch,
                        revision_id=head.revision_id,
                        sequence=head.sequence,
                    )
                    for family_id_item, _scope, _branch, _revision_id in proposal.expected_heads
                    if (head := self.heads.get(self._head_key(family_id_item, _scope, _branch))) is not None
                )
                aliases_before = tuple(
                    alias
                    for rows in self.aliases.values()
                    for alias in rows
                    if alias.family_id in affected_family_ids
                )
                relation_snapshots = tuple(
                    relation
                    for relation in self.relations.values()
                    if relation.source_family_id in affected_family_ids
                    or relation.target_family_id in affected_family_ids
                )
                manifest_id = revision.merge_manifest_id or uuid.uuid4()
                manifest_core = {
                    "manifest_id": str(manifest_id),
                    "manifest_schema": "merge-manifest.v1",
                    "merge_revision_id": str(revision.revision_id),
                    "target_family_id": str(family_id),
                    "source_family_ids": [str(item) for item in source_family_ids],
                    "previous_heads": [item.model_dump(mode="json") for item in head_snapshots],
                    "previous_family_snapshots": [
                        self.families[item].model_dump(mode="json") for item in affected_family_ids
                    ],
                    "aliases_before": [item.model_dump(mode="json") for item in aliases_before],
                    "affected_relation_snapshots": [
                        item.model_dump(mode="json") for item in relation_snapshots
                    ],
                    "created_relation_ids": [str(item.assertion_id) for item in merge_relations],
                    "field_origins": [item.model_dump(mode="json") for item in proposal.field_origins],
                    "proposal_id": str(proposal.proposal_id),
                    "approval_id": str(approval.approval_id),
                }
                manifest_hash = "sha256:" + hashlib.sha256(canonical_json(manifest_core).encode("utf-8")).hexdigest()
                merge_manifest = MergeManifest.model_validate({**manifest_core, "manifest_hash": manifest_hash})
            outbox_events = [
                self._new_outbox(
                    event_type="memory.head.changed",
                    family_id=family_id,
                    revision_id=revision.revision_id,
                    content_hash=revision.content_hash,
                    sequence=sequence,
                    payload=(
                        ("operation", proposal.operation.value),
                        ("state", target_state.value),
                        ("branch", content.memory_branch),
                        ("scope", content.memory_scope.value),
                    ),
                    available_at=content.valid_from if content.valid_from and content.valid_from > utc_now() else None,
                )
            ]
            created_relation: RelationAssertion | None = None
            if proposal.operation is LedgerOperation.CREATE_AND_LINK:
                assert create_link_target_family is not None
                assert create_link_target_head is not None
                created_relation = RelationAssertion(
                    assertion_id=uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"decisionssearch:relation:{proposal.proposal_id}",
                    ),
                    source_family_id=family_id,
                    target_family_id=create_link_target_family.family_id,
                    source_revision_id=revision.revision_id,
                    target_revision_id=create_link_target_head.revision_id,
                    relation_type=proposal.relation_type,
                    memory_scope=content.memory_scope,
                    memory_branch=content.memory_branch,
                    created_by=approval.principal_id,
                    evidence_ids=proposal.evidence_ids,
                    rationale=proposal.reason,
                    proposal_id=proposal.proposal_id,
                )
                outbox_events.append(
                    self._new_outbox(
                        event_type="memory.relation.applied",
                        family_id=family_id,
                        revision_id=None,
                        content_hash="sha256:" + hashlib.sha256(
                            canonical_json(created_relation).encode("utf-8")
                        ).hexdigest(),
                        sequence=sequence,
                        payload=(
                            ("operation", proposal.operation.value),
                            ("assertion_id", str(created_relation.assertion_id)),
                        ),
                    )
                )
            for source_family_id, _source_revision in merge_sources:
                outbox_events.append(
                    self._new_outbox(
                        event_type="memory.head.changed",
                        family_id=source_family_id,
                        revision_id=None,
                        content_hash="sha256:head-removed:" + str(source_family_id),
                        sequence=sequence,
                        payload=(
                            ("operation", "merge_source_retired"),
                            ("scope", content.memory_scope.value),
                            ("branch", content.memory_branch),
                        ),
                    )
                )
            if content.valid_to and content.valid_to > utc_now():
                outbox_events.append(
                    self._new_outbox(
                        event_type="memory.validity.expired",
                        family_id=family_id,
                        revision_id=revision.revision_id,
                        content_hash=revision.content_hash,
                        sequence=sequence,
                        payload=(
                            ("operation", "validity_expired"),
                            ("scope", content.memory_scope.value),
                            ("branch", content.memory_branch),
                        ),
                        available_at=content.valid_to,
                    )
                )

            # Todas as validações acima terminam antes deste bloco: a seção a
            # seguir é o commit atômico do ledger em memória.
            for parent_id in parent_ids:
                parent = self.revisions[parent_id]
                closes_recorded_history = (
                    proposal.operation
                    in {
                        LedgerOperation.INVALIDATE,
                        LedgerOperation.SUPERSEDE,
                        LedgerOperation.ARCHIVE,
                    }
                    or content.valid_from is None
                    or content.valid_from <= revision.recorded_from
                )
                if closes_recorded_history and (parent.recorded_to is None or parent.recorded_to > revision.recorded_from):
                    self.revisions[parent_id] = MemoryRevision.model_validate(
                        {
                            **parent.model_dump(mode="python"),
                            "recorded_to": revision.recorded_from,
                        }
                    )
            self.families[family.family_id] = family
            self.revisions[revision.revision_id] = revision
            for evidence in proposal.evidence:
                self.evidences[evidence.evidence_id] = evidence
            self.revision_evidence.extend(evidence_links)
            self.transitions.extend(transitions)
            self.heads[head_key] = new_head
            for source_family_id, _source_revision in merge_sources:
                source_family = self.families[source_family_id]
                self.families[source_family_id] = source_family.model_copy(
                    update={
                        "state": FamilyState.MERGED,
                        "merged_into_family_id": family_id,
                        "retired_at": utc_now(),
                        "retirement_reason": proposal.reason,
                    }
                )
                for key in tuple(self.heads):
                    if key[0] == source_family_id and key[1] == str(content.memory_scope) and key[2] == content.memory_branch:
                        del self.heads[key]
                for alias_name, aliases in self.aliases.items():
                    source_aliases = [alias for alias in aliases if alias.family_id == source_family_id]
                    if source_aliases:
                        for index, current_alias in enumerate(aliases):
                            if current_alias.family_id == source_family_id and current_alias.status is not MemoryAliasStatus.RETIRED:
                                aliases[index] = current_alias.model_copy(update={"status": MemoryAliasStatus.RETIRED})
                        for old_alias in source_aliases:
                            redirected = old_alias.model_copy(
                                update={"family_id": family_id, "status": MemoryAliasStatus.RESOLVED}
                            )
                            if redirected not in aliases:
                                aliases.append(redirected)
            for relation in merge_relations:
                self.relations[relation.assertion_id] = relation
            if created_relation is not None:
                self.relations[created_relation.assertion_id] = created_relation
            related_memory_ids = tuple(
                str(item)
                for item in (content.structured_payload or {}).get("related_memory_ids", [])
            )
            for related_memory_id in related_memory_ids:
                target_aliases = [
                    item
                    for item in self.aliases.get(related_memory_id, [])
                    if item.status is MemoryAliasStatus.RESOLVED and item.family_id is not None
                ]
                target_families = {item.family_id for item in target_aliases}
                if len(target_families) != 1:
                    continue
                target_family_id = next(iter(target_families))
                if target_family_id == family_id:
                    continue
                target_head = next(
                    (
                        item
                        for item in self.heads.values()
                        if item.family_id == target_family_id
                    ),
                    None,
                )
                relation_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"decisionssearch:episode-related:{family_id}:{target_family_id}:{revision.revision_id}",
                )
                if target_head is not None:
                    self.relations[relation_id] = RelationAssertion(
                        assertion_id=relation_id,
                        source_family_id=family_id,
                        target_family_id=target_family_id,
                        source_revision_id=revision.revision_id,
                        target_revision_id=target_head.revision_id,
                        relation_type="LEARNED_FROM",
                        memory_scope=content.memory_scope,
                        memory_branch=content.memory_branch,
                        rationale="Relação declarada pelo episódio legado",
                        created_by=approval.principal_id,
                        proposal_id=proposal.proposal_id,
                    )
            if proposal.replacement_family_id is not None:
                replacement_expected = next(
                    (
                        item
                        for item in proposal.expected_heads
                        if item[0] == proposal.replacement_family_id
                    ),
                    None,
                )
                replacement_head = next(
                    (
                        item
                        for item in self.heads.values()
                        if replacement_expected is not None
                        and item.family_id == replacement_expected[0]
                        and str(item.memory_scope) == str(replacement_expected[1])
                        and item.memory_branch == replacement_expected[2]
                        and item.revision_id == replacement_expected[3]
                    ),
                    None,
                )
                if replacement_head is None:
                    raise LedgerConflictError("A memória substituta não possui head ativo")
                replacement_revision_id = proposal.base_revision_ids[0] if proposal.base_revision_ids else revision.revision_id
                replacement_relation_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"decisionssearch:replacement-relation:{proposal.proposal_id}",
                )
                self.relations[replacement_relation_id] = RelationAssertion(
                    assertion_id=replacement_relation_id,
                    source_family_id=proposal.replacement_family_id,
                    target_family_id=family_id,
                    source_revision_id=replacement_head.revision_id,
                    target_revision_id=replacement_revision_id,
                    relation_type="DEPRECATES",
                    memory_scope=content.memory_scope,
                    memory_branch=content.memory_branch,
                    rationale=proposal.reason,
                    created_by=approval.principal_id,
                    proposal_id=proposal.proposal_id,
                )
            self._sequence = sequence
            if merge_manifest is not None:
                self.merge_manifests[merge_manifest.manifest_id] = merge_manifest
            for event in outbox_events:
                self.outbox[event.event_id] = event
            self._consume(
                proposal,
                approval,
                applied_revision_id=revision.revision_id,
                applied_relation_id=(created_relation.assertion_id if created_relation else None),
            )
            if proposal.operation is LedgerOperation.RESOLVE_CONFLICT:
                for resolution in proposal.conflict_resolutions:
                    conflict = self.conflict_cases[resolution.conflict_id]
                    self.conflict_cases[resolution.conflict_id] = conflict.model_copy(
                        update={"status": ConflictStatus.RESOLVED, "version": conflict.version + 1}
                    )
            return revision

    def _build_relation(self, proposal: ChangeProposal, approval: ApprovalDecision) -> RelationAssertion:
        source_revision_id = None
        target_revision_id = None
        for family_id, _scope, _branch, revision_id in proposal.expected_heads:
            if family_id == proposal.target_family_id:
                source_revision_id = revision_id
            if family_id == proposal.relation_target_family_id:
                target_revision_id = revision_id
        return RelationAssertion(
            assertion_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"decisionssearch:relation:{proposal.proposal_id}",
            ),
            source_family_id=proposal.target_family_id or uuid.UUID(int=0),
            target_family_id=proposal.relation_target_family_id or uuid.UUID(int=0),
            source_revision_id=source_revision_id,
            target_revision_id=target_revision_id,
            relation_type=proposal.relation_type,
            memory_scope=self.families[proposal.target_family_id].memory_scope,
            memory_branch=proposal.target_branch,
            created_by=approval.principal_id,
            evidence_ids=proposal.evidence_ids,
            rationale=proposal.reason,
            proposal_id=proposal.proposal_id,
        )

    @staticmethod
    def _provenance_hash(revision: MemoryRevision, proposal: ChangeProposal) -> str:
        payload = {
            "schema": "provenance.v1",
            "content_hash": revision.content_hash,
            "parents": [str(item) for item in revision.parent_revision_ids],
            "sources": [str(item) for item in revision.source_revision_ids],
            "evidence_links": [item.model_dump(mode="json") for item in proposal.evidence_links],
            "field_origins": [item.model_dump(mode="json") for item in revision.field_origins],
            "conflicts": list(revision.conflict_ids),
            "manifest_id": str(revision.merge_manifest_id) if revision.merge_manifest_id else None,
        }
        return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    async def get_merge_manifest(self, manifest_id: uuid.UUID) -> MergeManifest | None:
        return self.merge_manifests.get(manifest_id)

    async def get_conflict_case(self, conflict_id: str) -> ConflictCase | None:
        return self.conflict_cases.get(conflict_id)

    def _apply_unmerge(self, proposal: ChangeProposal, approval: ApprovalDecision):
        manifest = self.merge_manifests.get(proposal.merge_manifest_id)
        if manifest is None:
            raise LedgerConflictError("Manifesto de fusão não encontrado")
        if manifest.manifest_hash != proposal.expected_manifest_hash:
            raise LedgerConflictError("O manifesto mudou desde a proposta de unmerge")
        self._assert_unmerge_cas(manifest)
        target_current = self.heads.get(
            self._head_key(
                manifest.target_family_id,
                next(item.memory_scope for item in manifest.previous_heads if item.family_id == manifest.target_family_id),
                next(item.memory_branch for item in manifest.previous_heads if item.family_id == manifest.target_family_id),
            )
        )
        if target_current is None or target_current.revision_id != manifest.merge_revision_id:
            raise LedgerConflictError("O merge já não é o head atual")
        affected_families = {manifest.target_family_id, *manifest.source_family_ids}
        for key in tuple(self.heads):
            if key[0] in affected_families and any(
                snapshot.family_id == key[0]
                and str(snapshot.memory_scope) == key[1]
                and snapshot.memory_branch == key[2]
                for snapshot in manifest.previous_heads
            ):
                del self.heads[key]
        unmerge_at = utc_now()
        merge_revision = self.revisions.get(manifest.merge_revision_id)
        if merge_revision is not None and (
            merge_revision.recorded_to is None or merge_revision.recorded_to > unmerge_at
        ):
            self.revisions[manifest.merge_revision_id] = merge_revision.model_copy(
                update={"recorded_to": unmerge_at}
            )
        for snapshot in manifest.previous_heads:
            self.heads[self._head_key(snapshot.family_id, snapshot.memory_scope, snapshot.memory_branch)] = MemoryHead(
                family_id=snapshot.family_id,
                memory_scope=snapshot.memory_scope,
                memory_branch=snapshot.memory_branch,
                revision_id=snapshot.revision_id,
                sequence=self._sequence + 1,
            )
        for family in manifest.previous_family_snapshots:
            self.families[family.family_id] = family
        for alias_name in {alias.alias for alias in manifest.aliases_before}:
            self.aliases[alias_name] = []
        for alias in manifest.aliases_before:
            self.aliases[alias.alias].append(alias)
        for relation_id in manifest.created_relation_ids:
            relation = self.relations.get(relation_id)
            if relation is not None:
                self.relations[relation_id] = relation.model_copy(update={"state": RelationState.RETIRED})
        for relation in manifest.affected_relation_snapshots:
            self.relations[relation.assertion_id] = relation
        self._sequence += 1
        restored_target = next(
            snapshot.revision_id
            for snapshot in manifest.previous_heads
            if snapshot.family_id == manifest.target_family_id
        )
        self.transitions.append(
            RevisionTransition(
                family_id=manifest.target_family_id,
                from_revision_ids=(manifest.merge_revision_id,),
                to_revision_id=manifest.merge_revision_id,
                state=RevisionState.INVALIDATED,
                reason="A revisão de merge foi invalidada pelo unmerge",
                actor_id=approval.principal_id,
                actor_type=approval.principal_type,
                proposal_id=proposal.proposal_id,
                created_at=unmerge_at,
            )
        )
        for snapshot in manifest.previous_heads:
            self.transitions.append(
                RevisionTransition(
                    family_id=snapshot.family_id,
                    from_revision_ids=(),
                    to_revision_id=snapshot.revision_id,
                    state=RevisionState.ACTIVE,
                    reason=proposal.reason,
                    actor_id=approval.principal_id,
                    actor_type=approval.principal_type,
                    proposal_id=proposal.proposal_id,
                    created_at=unmerge_at,
                )
            )
        for family_id in affected_families:
            event = self._new_outbox(
                event_type="memory.head.changed",
                family_id=family_id,
                revision_id=next(
                    (snapshot.revision_id for snapshot in manifest.previous_heads if snapshot.family_id == family_id),
                    None,
                ),
                content_hash=(
                    self.revisions[next(snapshot.revision_id for snapshot in manifest.previous_heads if snapshot.family_id == family_id)].content_hash
                    if any(snapshot.family_id == family_id for snapshot in manifest.previous_heads)
                    else "sha256:unmerge"
                ),
                sequence=self._sequence,
                payload=(("operation", "unmerge"), ("manifest_id", str(manifest.manifest_id))),
            )
            self.outbox[event.event_id] = event
        self._consume(proposal, approval, applied_revision_id=restored_target)
        return self.revisions[restored_target]

    def _assert_unmerge_cas(self, manifest: MergeManifest) -> None:
        """Verifica o estado inteiro alterado pelo merge antes de restaurar.

        O manifesto é um snapshot histórico, não uma autorização para sobrescrever
        mudanças posteriores. Qualquer alteração em heads, aliases, famílias ou
        relações afetadas transforma o unmerge em conflito explícito.
        """

        target_snapshot = next(
            (item for item in manifest.previous_heads if item.family_id == manifest.target_family_id),
            None,
        )
        if target_snapshot is None:
            raise LedgerConflictError("Manifesto sem head da família alvo")
        target_head = self.heads.get(
            self._head_key(
                target_snapshot.family_id,
                target_snapshot.memory_scope,
                target_snapshot.memory_branch,
            )
        )
        if target_head is None or target_head.revision_id != manifest.merge_revision_id:
            raise LedgerConflictError("O head do merge mudou desde o manifesto")
        for snapshot in manifest.previous_heads:
            if snapshot.family_id == manifest.target_family_id:
                continue
            current = self.heads.get(
                self._head_key(snapshot.family_id, snapshot.memory_scope, snapshot.memory_branch)
            )
            if current is not None:
                raise LedgerConflictError("Um head de origem foi recriado após o merge")

        for family_snapshot in manifest.previous_family_snapshots:
            current = self.families.get(family_snapshot.family_id)
            if current is None:
                raise LedgerConflictError("Uma família do manifesto não existe mais")
            if family_snapshot.family_id in manifest.source_family_ids:
                immutable_fields = (
                    "project",
                    "category",
                    "memory_scope",
                    "created_at",
                    "created_by",
                    "legacy_memory_id",
                    "migration_run_id",
                )
                if any(
                    getattr(current, field) != getattr(family_snapshot, field)
                    for field in immutable_fields
                ):
                    raise LedgerConflictError("Dados imutáveis da família de origem mudaram após o merge")
                if (
                    current.state is not FamilyState.MERGED
                    or current.merged_into_family_id != manifest.target_family_id
                ):
                    raise LedgerConflictError("O estado de uma família de origem mudou após o merge")
            elif current.model_dump(mode="json") != family_snapshot.model_dump(mode="json"):
                raise LedgerConflictError("A família alvo mudou após o merge")

        expected_aliases: dict[str, list[MemoryAlias]] = defaultdict(list)
        for alias in manifest.aliases_before:
            if alias.family_id in manifest.source_family_ids:
                expected_aliases[alias.alias].append(
                    alias.model_copy(update={"status": MemoryAliasStatus.RETIRED})
                )
                expected_aliases[alias.alias].append(
                    alias.model_copy(
                        update={
                            "family_id": manifest.target_family_id,
                            "status": MemoryAliasStatus.RESOLVED,
                        }
                    )
                )
            else:
                expected_aliases[alias.alias].append(alias)
        for alias_name, expected in expected_aliases.items():
            actual = self.aliases.get(alias_name, [])
            actual_payload = sorted(canonical_json(item.model_dump(mode="json")) for item in actual)
            expected_payload = sorted(canonical_json(item.model_dump(mode="json")) for item in expected)
            if actual_payload != expected_payload:
                raise LedgerConflictError("Um alias afetado mudou após o merge")

        affected_families = {manifest.target_family_id, *manifest.source_family_ids}
        current_relations = {
            relation.assertion_id: relation
            for relation in self.relations.values()
            if relation.source_family_id in affected_families
            or relation.target_family_id in affected_families
        }
        expected_relations = {relation.assertion_id: relation for relation in manifest.affected_relation_snapshots}
        for relation_id in manifest.created_relation_ids:
            relation = current_relations.get(relation_id)
            if relation is None or relation.state is not RelationState.ACTIVE:
                raise LedgerConflictError("Uma relação criada pelo merge mudou após o merge")
            expected_relations[relation_id] = relation
        if set(current_relations) != set(expected_relations):
            raise LedgerConflictError("Relações afetadas mudaram após o merge")
        for relation_id, expected in expected_relations.items():
            actual = current_relations[relation_id]
            if relation_id not in manifest.created_relation_ids and actual.model_dump(mode="json") != expected.model_dump(mode="json"):
                raise LedgerConflictError("Uma relação histórica afetada mudou após o merge")

    def _consume(
        self,
        proposal: ChangeProposal,
        approval: ApprovalDecision,
        *,
        applied_revision_id: uuid.UUID | None = None,
        applied_relation_id: uuid.UUID | None = None,
    ) -> None:
        self.approvals[approval.approval_id] = approval.model_copy(
            update={"status": ApprovalStatus.CONSUMED, "consumed_at": utc_now()}
        )
        self.proposals[proposal.proposal_id] = proposal.model_copy(
            update={
                "status": ProposalStatus.APPLIED,
                "applied_revision_id": applied_revision_id,
                "applied_relation_id": applied_relation_id,
            }
        )

    def _new_outbox(
        self,
        *,
        event_type: str,
        family_id: uuid.UUID,
        revision_id: uuid.UUID | None,
        content_hash: str,
        payload: tuple[tuple[str, str], ...],
        sequence: int | None = None,
        available_at: datetime | None = None,
    ) -> OutboxEvent:
        sequence = sequence or self._sequence + 1
        event_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"decisionssearch:outbox:{event_type}:{family_id}:{revision_id}:{sequence}:{payload}",
        )
        return OutboxEvent(
            event_id=event_id,
            event_type=event_type,
            family_id=family_id,
            revision_id=revision_id,
            content_hash=content_hash,
            sequence=sequence,
            payload=payload,
            available_at=available_at or utc_now(),
        )

    async def get_view(self, revision_id: uuid.UUID) -> MemoryRevisionView:
        revision = await self.get_revision(revision_id)
        if revision is None:
            raise MemoryServiceError("Revisão não encontrada", context={"revision_id": str(revision_id)})
        current = any(head.revision_id == revision_id for head in self.heads.values())
        transitions = [item for item in self.transitions if revision_id in item.from_revision_ids or item.to_revision_id == revision_id]
        state = RevisionState.ACTIVE if current else RevisionState.SUPERSEDED
        invalidation_reason = ""
        for transition in transitions:
            if revision_id in transition.from_revision_ids and transition.to_revision_id != revision_id:
                state = RevisionState.SUPERSEDED
                invalidation_reason = transition.reason
            if transition.to_revision_id == revision_id:
                state = transition.state
                invalidation_reason = transition.reason if state is not RevisionState.ACTIVE else ""
        if (
            state is RevisionState.ACTIVE
            and revision.content.valid_from is not None
            and revision.content.valid_from > utc_now()
        ):
            state = RevisionState.SCHEDULED
            invalidation_reason = "A revisão está agendada para uma janela futura"
        if state is RevisionState.ACTIVE and revision.content.valid_to and revision.content.valid_to <= utc_now():
            state = RevisionState.INVALIDATED
            invalidation_reason = "A janela de validade da revisão expirou"
        return MemoryRevisionView(
            revision=revision,
            state=state,
            is_current_head=current,
            invalidation_reason=invalidation_reason,
            transition_ids=tuple(item.transition_id for item in transitions),
        )

    async def add_alias(self, alias: MemoryAlias) -> MemoryAlias:
        async with self._lock:
            existing = self.aliases[alias.alias]
            if alias.status is MemoryAliasStatus.AMBIGUOUS:
                candidates = tuple(
                    dict.fromkeys(
                        item
                        for current in existing
                        for item in (current.candidates or ((current.family_id,) if current.family_id else ()))
                    )
                )
                alias = alias.model_copy(update={"candidates": tuple(dict.fromkeys((*candidates, *alias.candidates)))})
                existing[:] = [item for item in existing if item.status is not MemoryAliasStatus.AMBIGUOUS]
            if not any(
                item.family_id == alias.family_id
                and item.status is alias.status
                and item.candidates == alias.candidates
                for item in existing
            ):
                existing.append(alias)
            return alias

    async def import_legacy(self, record) -> None:  # noqa: ANN001
        """Importa uma unidade legada de forma idempotente para testes/migração."""
        async with self._lock:
            if record.revision.revision_id in self.revisions:
                existing = self.revisions[record.revision.revision_id]
                if existing.content_hash != record.revision.content_hash:
                    raise LedgerConflictError("revision_id legado já existe com outro conteúdo")
                existing_evidence = self.evidences.get(record.evidence.evidence_id)
                if existing_evidence is not None and existing_evidence.fingerprint != record.evidence.fingerprint:
                    raise LedgerConflictError("evidence_id legado já existe com outro conteúdo")
                return
            existing_evidence = self.evidences.get(record.evidence.evidence_id)
            if existing_evidence is not None and existing_evidence.fingerprint != record.evidence.fingerprint:
                raise LedgerConflictError("evidence_id legado já existe com outro conteúdo")
            self.families[record.family.family_id] = record.family
            self.revisions[record.revision.revision_id] = record.revision
            self.evidences[record.evidence.evidence_id] = record.evidence
            self.revision_evidence.append(
                RevisionEvidence(
                    revision_id=record.revision.revision_id,
                    evidence_id=record.evidence.evidence_id,
                    stance="context",
                    confidence=0.0,
                )
            )
            if record.alias.status is MemoryAliasStatus.RESOLVED:
                self.aliases[record.alias.alias].append(record.alias)
            else:
                self.aliases[record.alias.alias].append(record.alias)
            self._sequence += 1
            key = self._head_key(
                record.family.family_id,
                record.revision.content.memory_scope,
                record.revision.content.memory_branch,
            )
            self.heads[key] = MemoryHead(
                family_id=record.family.family_id,
                memory_scope=record.revision.content.memory_scope,
                memory_branch=record.revision.content.memory_branch,
                revision_id=record.revision.revision_id,
                sequence=self._sequence,
            )
            state = (
                RevisionState.ACTIVE
                if record.legacy_status == "active"
                else RevisionState.ARCHIVED
            )
            self.transitions.append(
                RevisionTransition(
                    family_id=record.family.family_id,
                    to_revision_id=record.revision.revision_id,
                    state=state,
                    reason="Estado importado sem inferir validade histórica",
                    actor_id="legacy_import",
                    actor_type="migration",
                )
            )
            event = self._new_outbox(
                event_type="memory.head.changed",
                family_id=record.family.family_id,
                revision_id=record.revision.revision_id,
                content_hash=record.revision.content_hash,
                sequence=self._sequence,
                payload=(
                    ("operation", "legacy_import"),
                    ("state", state.value),
                    ("scope", record.revision.content.memory_scope.value),
                    ("branch", record.revision.content.memory_branch),
                ),
            )
            self.outbox[event.event_id] = event

    async def resolve_alias(self, alias: str) -> MemoryAlias | None:
        rows = [row for row in self.aliases.get(alias, []) if row.status is not MemoryAliasStatus.RETIRED]
        if not rows:
            return None
        if any(row.status is MemoryAliasStatus.AMBIGUOUS for row in rows):
            candidates = tuple(
                dict.fromkeys(
                    item
                    for row in rows
                    for item in (row.candidates or ((row.family_id,) if row.family_id else ()))
                )
            )
            return MemoryAlias(alias=alias, status=MemoryAliasStatus.AMBIGUOUS, candidates=candidates)
        families = {row.family_id for row in rows if row.family_id}
        if len(families) == 1:
            return next(row for row in rows if row.family_id)
        return MemoryAlias(
            alias=alias,
            status=MemoryAliasStatus.AMBIGUOUS,
            candidates=tuple(families),
        )

    async def list_active_revisions(
        self,
        project: str | None = None,
        category: str | None = None,
        memory_scope: MemoryScope | str | None = None,
        memory_branch: str | None = None,
    ) -> list[MemoryRevision]:
        return await self.list_effective_revisions(
            project=project,
            category=category,
            memory_scope=memory_scope,
            memory_branch=memory_branch,
        )

    async def list_effective_revisions(
        self,
        *,
        valid_at: datetime | None = None,
        recorded_at: datetime | None = None,
        project: str | None = None,
        category: str | None = None,
        memory_scope: MemoryScope | str | None = None,
        memory_branch: str | None = None,
    ) -> list[MemoryRevision]:
        valid_at = valid_at or utc_now()
        recorded_at = recorded_at or utc_now()
        if valid_at.tzinfo is None or recorded_at.tzinfo is None:
            raise ValueError("consultas temporais precisam de timezone explícito")
        grouped: dict[tuple[uuid.UUID, str, str], list[MemoryRevision]] = defaultdict(list)
        reactivated_at: dict[uuid.UUID, datetime] = {}
        for transition in self.transitions:
            if transition.state is RevisionState.ACTIVE and transition.to_revision_id:
                previous = reactivated_at.get(transition.to_revision_id)
                if previous is None or transition.created_at > previous:
                    reactivated_at[transition.to_revision_id] = transition.created_at
        for revision in self.revisions.values():
            content = revision.content
            if project is not None and content.project != project:
                continue
            if category is not None and content.category != category:
                continue
            if memory_scope is not None and str(content.memory_scope) != str(memory_scope):
                continue
            if memory_branch is not None and content.memory_branch != memory_branch:
                continue
            if revision.recorded_from > recorded_at:
                continue
            if revision.recorded_to is not None and recorded_at >= revision.recorded_to:
                restored_at = reactivated_at.get(revision.revision_id)
                if (
                    restored_at is None
                    or restored_at < revision.recorded_to
                    or restored_at > recorded_at
                ):
                    continue
            if content.valid_from is not None and content.valid_from > valid_at:
                continue
            transitions = [
                transition
                for transition in self.transitions
                if transition.to_revision_id == revision.revision_id
                and transition.state in {RevisionState.INVALIDATED, RevisionState.ARCHIVED}
                and transition.created_at <= recorded_at
            ]
            if transitions:
                continue
            grouped[(revision.family_id, str(content.memory_scope), content.memory_branch)].append(revision)
        result = []
        for rows in grouped.values():
            chosen = max(
                rows,
                key=lambda item: (
                    item.content.valid_from or datetime.min.replace(tzinfo=timezone.utc),
                    item.recorded_from,
                    item.created_at,
                    str(item.revision_id),
                ),
            )
            if chosen.content.valid_to is None or valid_at < chosen.content.valid_to:
                result.append(chosen)
        return sorted(result, key=lambda item: (item.created_at, str(item.revision_id)))

    async def list_revisions(
        self,
        project: str | None = None,
        category: str | None = None,
    ) -> list[MemoryRevision]:
        revisions = [
            revision
            for revision in self.revisions.values()
            if (project is None or revision.content.project == project)
            and (category is None or revision.content.category == category)
        ]
        return sorted(revisions, key=lambda item: (item.created_at, str(item.revision_id)))

    async def list_outbox(
        self,
        status: OutboxStatus | None = OutboxStatus.PENDING,
        *,
        now: datetime | None = None,
    ) -> list[OutboxEvent]:
        events = list(self.outbox.values())
        now = now or utc_now()
        if status is not None:
            events = [event for event in events if event.status is status]
        events = [
            event
            for event in events
            if event.available_at <= now
            and (event.lease_until is None or event.lease_until <= now or event.status is not OutboxStatus.PROCESSING)
        ]
        return sorted(events, key=lambda item: (item.sequence, item.created_at, str(item.event_id)))

    async def mark_outbox(
        self,
        event_id: uuid.UUID,
        status: OutboxStatus,
        error: str = "",
        *,
        worker_id: str | None = None,
        claim_token: str | None = None,
    ) -> None:
        async with self._lock:
            event = self.outbox.get(event_id)
            if event is None:
                raise MemoryServiceError("Evento outbox não encontrado")
            now = utc_now()
            if status is OutboxStatus.PROCESSING:
                raise LedgerConflictError("PROCESSING só pode ser definido por claim_outbox")
            if event.status is OutboxStatus.PROCESSING:
                if (
                    not worker_id
                    or not claim_token
                    or event.claimed_by != worker_id
                    or event.claim_token != claim_token
                    or event.lease_until is None
                    or event.lease_until <= now
                ):
                    raise LedgerConflictError("Lease do outbox ausente, incorreto ou expirado")
            elif status is not OutboxStatus.PROCESSING:
                raise LedgerConflictError("O evento precisa ser reivindicado antes da confirmação")
            attempts = event.attempts + 1
            next_status = OutboxStatus.DEAD_LETTER if status is OutboxStatus.FAILED and attempts >= 5 else status
            self.outbox[event_id] = event.model_copy(
                update={
                    "status": next_status,
                    "attempts": attempts,
                    "last_error": error,
                    "lease_until": None,
                    "claimed_by": None,
                    "claim_token": None,
                }
            )

    async def claim_outbox(
        self,
        event_id: uuid.UUID,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> OutboxEvent | None:
        async with self._lock:
            event = self.outbox.get(event_id)
            now = utc_now()
            if event is None or event.available_at > now:
                return None
            if event.status is OutboxStatus.PROCESSING and event.lease_until and event.lease_until > now:
                return None
            if event.status not in {OutboxStatus.PENDING, OutboxStatus.FAILED, OutboxStatus.PROCESSING}:
                return None
            claimed = event.model_copy(
                update={
                    "status": OutboxStatus.PROCESSING,
                    "lease_until": now + timedelta(seconds=lease_seconds),
                    "claimed_by": worker_id,
                    "claim_token": uuid.uuid4().hex,
                    "last_error": "",
                }
            )
            self.outbox[event_id] = claimed
            return claimed

    async def list_relations(self, state: RelationState = RelationState.ACTIVE) -> list[RelationAssertion]:
        return [relation for relation in self.relations.values() if relation.state is state]

    async def record_usage_observation(self, observation: UsageObservation) -> UsageObservation:
        async with self._lock:
            revision = self.revisions.get(observation.procedure_revision_id)
            if revision is None:
                raise LedgerConflictError("A observação aponta para uma revisão procedural inexistente")
            if revision.family_id != observation.procedure_family_id:
                raise LedgerConflictError("A observação não pertence à família da revisão informada")
            if revision.content.memory_scope is not MemoryScope.PROCEDURAL:
                raise LedgerConflictError("Somente revisões procedurais aceitam observações de uso")
            expected_hash = usage_payload_hash(
                procedure_family_id=observation.procedure_family_id,
                procedure_revision_id=observation.procedure_revision_id,
                success=observation.success,
                correlation_id=observation.correlation_id,
                actor_id=observation.actor_id,
                result=observation.result,
            )
            if observation.payload_hash != expected_hash:
                raise LedgerConflictError("payload_hash da observação não corresponde ao conteúdo enviado")
            existing_id = self._usage_idempotency.get(observation.idempotency_key)
            if existing_id is not None:
                existing = self.usage_observations[existing_id]
                if existing.payload_hash != observation.payload_hash:
                    raise LedgerConflictError("idempotency_key já foi usada com outro uso procedural")
                return existing
            self.usage_observations[observation.observation_id] = observation
            self._usage_idempotency[observation.idempotency_key] = observation.observation_id
            return observation

    async def list_usage_observations(
        self, procedure_family_id: uuid.UUID | None = None
    ) -> list[UsageObservation]:
        rows = list(self.usage_observations.values())
        if procedure_family_id is not None:
            rows = [item for item in rows if item.procedure_family_id == procedure_family_id]
        return sorted(rows, key=lambda item: (item.observed_at, str(item.observation_id)))
