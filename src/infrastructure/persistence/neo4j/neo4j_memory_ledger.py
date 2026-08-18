from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from decisionssearch.domain.memory.memory_item import MemoryItem
from decisionssearch.domain.memory_ledger import (
    ApprovalDecision,
    ApprovalStatus,
    ChangeProposal,
    ConflictCase,
    ConflictDetectionCoverage,
    ConflictStatus,
    Evidence,
    EvidenceLinkSpec,
    EvidenceStance,
    FamilyState,
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
    RevisionState,
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
from decisionssearch.application.memory.ledger.views import _effective_weight


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Neo4jMemoryLedger:
    """Ledger canônico de memória semântica no Neo4j.

    O Qdrant não é usado neste adapter. A transação de aplicação grava a revisão,
    evidências, transições, head, projeção legada e evento de outbox de uma vez.
    O materializador vetorial consome o outbox depois do commit.
    """

    def __init__(self, graph) -> None:  # noqa: ANN001
        self.graph = graph
        self._schema_lock = asyncio.Lock()
        self._schema_ready = False

    async def ensure_schema(self) -> None:
        constraints = (
            "CREATE CONSTRAINT memory_family_id IF NOT EXISTS FOR (n:MemoryFamily) REQUIRE n.family_id IS UNIQUE",
            "CREATE CONSTRAINT memory_revision_id IF NOT EXISTS FOR (n:MemoryRevision) REQUIRE n.revision_id IS UNIQUE",
            "CREATE CONSTRAINT memory_head_key IF NOT EXISTS FOR (n:MemoryHead) REQUIRE n.head_key IS UNIQUE",
            "CREATE CONSTRAINT memory_evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.evidence_id IS UNIQUE",
            "CREATE CONSTRAINT memory_proposal_id IF NOT EXISTS FOR (n:ChangeProposal) REQUIRE n.proposal_id IS UNIQUE",
            "CREATE CONSTRAINT memory_proposal_idempotency IF NOT EXISTS FOR (n:ChangeProposal) REQUIRE n.idempotency_key IS UNIQUE",
            "CREATE CONSTRAINT memory_approval_id IF NOT EXISTS FOR (n:ApprovalDecision) REQUIRE n.approval_id IS UNIQUE",
            "CREATE CONSTRAINT memory_outbox_id IF NOT EXISTS FOR (n:OutboxEvent) REQUIRE n.event_id IS UNIQUE",
            "CREATE CONSTRAINT memory_conflict_id IF NOT EXISTS FOR (n:ConflictCase) REQUIRE n.conflict_id IS UNIQUE",
            "CREATE CONSTRAINT memory_manifest_id IF NOT EXISTS FOR (n:MergeManifest) REQUIRE n.manifest_id IS UNIQUE",
            "CREATE CONSTRAINT memory_usage_observation_id IF NOT EXISTS FOR (n:UsageObservation) REQUIRE n.observation_id IS UNIQUE",
            "CREATE CONSTRAINT memory_usage_idempotency_key IF NOT EXISTS FOR (n:UsageObservation) REQUIRE n.idempotency_key IS UNIQUE",
            "CREATE CONSTRAINT memory_alias_key IF NOT EXISTS FOR (n:MemoryAlias) REQUIRE (n.alias, n.family_id) IS UNIQUE",
            "CREATE INDEX memory_alias_lookup IF NOT EXISTS FOR (n:MemoryAlias) ON (n.alias)",
        )
        async with self.graph.driver.session() as session:
            for query in constraints:
                result = await session.run(query)
                await result.consume()
        self._schema_ready = True

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if not self._schema_ready:
                await self.ensure_schema()

    @staticmethod
    def _head_key(family_id: uuid.UUID, scope: str | MemoryScope, branch: str) -> str:
        normalized_scope = scope.value if isinstance(scope, MemoryScope) else str(scope)
        return f"{family_id}:{normalized_scope}:{branch}"

    @staticmethod
    def _expected_rows(
        expected_heads: Iterable[tuple[uuid.UUID, str, str, uuid.UUID]],
    ) -> list[dict[str, str]]:
        return [
            {
                "family_id": str(family_id),
                "scope": scope.value if isinstance(scope, MemoryScope) else str(scope),
                "branch": branch,
                "revision_id": str(revision_id),
            }
            for family_id, scope, branch, revision_id in expected_heads
        ]

    async def get_family(self, family_id: uuid.UUID) -> MemoryFamily | None:
        rows = await self.graph.execute_read(
            "MATCH (f:MemoryFamily {family_id: $family_id}) RETURN f.payload_json AS payload",
            family_id=str(family_id),
        )
        return MemoryFamily.model_validate_json(rows[0]["payload"]) if rows else None

    async def get_head(
        self,
        family_id: uuid.UUID,
        scope: MemoryScope | str = MemoryScope.SEMANTIC,
        branch: str = "semantic",
    ) -> MemoryHead | None:
        rows = await self.graph.execute_read(
            """
            MATCH (h:MemoryHead {head_key: $head_key})
            RETURN h.payload_json AS payload
            """,
            head_key=self._head_key(family_id, scope, branch),
        )
        return MemoryHead.model_validate_json(rows[0]["payload"]) if rows else None

    async def get_current_head(
        self,
        family_id: uuid.UUID,
        scope: MemoryScope | str | None = None,
        branch: str | None = None,
    ) -> MemoryHead | None:
        if scope is None:
            rows = await self.graph.execute_read(
                "MATCH (h:MemoryHead {family_id: $family_id}) "
                "WHERE ($branch IS NULL OR h.memory_branch = $branch) "
                "RETURN h.payload_json AS payload ORDER BY h.sequence DESC LIMIT 1",
                family_id=str(family_id),
                branch=branch,
            )
        else:
            rows = await self.graph.execute_read(
                "MATCH (h:MemoryHead {family_id: $family_id, memory_scope: $scope}) "
                "WHERE ($branch IS NULL OR h.memory_branch = $branch) "
                "RETURN h.payload_json AS payload ORDER BY h.sequence DESC LIMIT 1",
                family_id=str(family_id),
                scope=str(scope),
                branch=branch,
            )
        return MemoryHead.model_validate_json(rows[0]["payload"]) if rows else None

    async def get_revision(self, revision_id: uuid.UUID) -> MemoryRevision | None:
        rows = await self.graph.execute_read(
            "MATCH (r:MemoryRevision {revision_id: $revision_id}) RETURN r.payload_json AS payload",
            revision_id=str(revision_id),
        )
        return MemoryRevision.model_validate_json(rows[0]["payload"]) if rows else None

    async def get_proposal(self, proposal_id: uuid.UUID) -> ChangeProposal:
        rows = await self.graph.execute_read(
            "MATCH (p:ChangeProposal {proposal_id: $proposal_id}) RETURN p.payload_json AS payload",
            proposal_id=str(proposal_id),
        )
        if not rows:
            raise ProposalNotFoundError(
                "Proposta não encontrada", context={"proposal_id": str(proposal_id)}
            )
        return ChangeProposal.model_validate_json(rows[0]["payload"])

    async def get_proposal_by_idempotency(self, idempotency_key: str) -> ChangeProposal | None:
        rows = await self.graph.execute_read(
            "MATCH (p:ChangeProposal {idempotency_key: $key}) RETURN p.payload_json AS payload",
            key=idempotency_key,
        )
        return ChangeProposal.model_validate_json(rows[0]["payload"]) if rows else None

    async def get_conflict_case(self, conflict_id: str) -> ConflictCase | None:
        rows = await self.graph.execute_read(
            "MATCH (c:ConflictCase {conflict_id: $conflict_id}) RETURN c.payload_json AS payload",
            conflict_id=conflict_id,
        )
        return ConflictCase.model_validate_json(rows[0]["payload"]) if rows else None

    async def get_merge_manifest(self, manifest_id: uuid.UUID) -> MergeManifest | None:
        rows = await self.graph.execute_read(
            "MATCH (m:MergeManifest {manifest_id: $manifest_id}) RETURN m.payload_json AS payload",
            manifest_id=str(manifest_id),
        )
        return MergeManifest.model_validate_json(rows[0]["payload"]) if rows else None

    async def get_approval(self, approval_id: uuid.UUID) -> ApprovalDecision | None:
        rows = await self.graph.execute_read(
            "MATCH (a:ApprovalDecision {approval_id: $approval_id}) RETURN a.payload_json AS payload",
            approval_id=str(approval_id),
        )
        return ApprovalDecision.model_validate_json(rows[0]["payload"]) if rows else None

    async def save_proposal(self, proposal: ChangeProposal) -> ChangeProposal:
        await self._ensure_schema()
        if proposal.idempotency_key:
            existing_rows = await self.graph.execute_read(
                "MATCH (p:ChangeProposal {idempotency_key: $key}) RETURN p.payload_json AS payload",
                key=proposal.idempotency_key,
            )
            if existing_rows:
                existing = ChangeProposal.model_validate_json(existing_rows[0]["payload"])
                if existing.preview_hash != proposal.preview_hash:
                    raise LedgerConflictError("A chave de idempotência já foi usada para outro preview")
                return existing
        payload = proposal.model_dump_json()
        async with self.graph.driver.session() as session:
            row = await session.execute_write(
                self._save_proposal_transaction,
                proposal,
                payload,
            )
        if row is None:
            raise MemoryServiceError("Falha ao persistir proposta")
        stored = ChangeProposal.model_validate_json(row["payload"])
        if stored.preview_hash != proposal.preview_hash:
            raise LedgerConflictError("proposal_id já existe com outro preview")
        return stored

    async def _save_proposal_transaction(self, tx, proposal, payload):  # noqa: ANN001
        """Grava proposta e conflitos no mesmo commit.

        A chave de idempotência participa do ``MERGE`` quando fornecida e é
        protegida por constraint Neo4j. Isso elimina a janela de corrida entre
        ``get_proposal_by_idempotency`` e a criação do nó.
        """

        if proposal.idempotency_key:
            result = await tx.run(
                """
                MERGE (p:ChangeProposal {idempotency_key: $idempotency_key})
                ON CREATE SET p.proposal_id = $proposal_id,
                              p.payload_json = $payload,
                              p.status = $status,
                              p.preview_hash = $preview_hash,
                              p.created_at = $created_at
                RETURN p.payload_json AS payload
                """,
                proposal_id=str(proposal.proposal_id),
                idempotency_key=proposal.idempotency_key,
                payload=payload,
                status=proposal.status.value,
                preview_hash=proposal.preview_hash,
                created_at=proposal.created_at.isoformat(),
            )
        else:
            result = await tx.run(
                """
                MERGE (p:ChangeProposal {proposal_id: $proposal_id})
                ON CREATE SET p.payload_json = $payload,
                              p.status = $status,
                              p.preview_hash = $preview_hash,
                              p.created_at = $created_at
                RETURN p.payload_json AS payload
                """,
                proposal_id=str(proposal.proposal_id),
                payload=payload,
                status=proposal.status.value,
                preview_hash=proposal.preview_hash,
                created_at=proposal.created_at.isoformat(),
            )
        row = await result.single()
        if row is None:
            return None
        for conflict in proposal.conflicts:
            conflict_result = await tx.run(
                "MATCH (c:ConflictCase {conflict_id: $conflict_id}) "
                "RETURN c.snapshot_hash AS snapshot_hash",
                conflict_id=conflict.conflict_id,
            )
            existing_conflict = await conflict_result.single()
            if (
                existing_conflict is not None
                and existing_conflict["snapshot_hash"] != conflict.snapshot_hash
            ):
                raise LedgerConflictError("O conflito já existe com outro snapshot")
            await tx.run(
                "MERGE (c:ConflictCase {conflict_id: $conflict_id}) "
                "ON CREATE SET c.snapshot_hash = $snapshot_hash, c.payload_json = $payload",
                conflict_id=conflict.conflict_id,
                snapshot_hash=conflict.snapshot_hash,
                payload=conflict.model_dump_json(),
            )
        return row

    async def save_approval(self, approval: ApprovalDecision) -> ApprovalDecision:
        await self._ensure_schema()
        proposal = await self.get_proposal(approval.proposal_id)
        if proposal.status is not ProposalStatus.PENDING_APPROVAL:
            raise ApprovalError("A proposta não está pendente de aprovação")
        if approval.preview_hash != proposal.preview_hash:
            raise ApprovalError("O hash aprovado não corresponde ao preview")
        if approval.expected_heads != proposal.expected_heads:
            raise ApprovalError("A aprovação não confirma os mesmos heads do preview")
        if approval.expires_at and approval.expires_at <= utc_now():
            raise ApprovalError("A aprovação expirou")
        existing = await self.get_approval(approval.approval_id)
        if existing is not None:
            if existing.model_dump(mode="json") != approval.model_dump(mode="json"):
                raise ApprovalError("approval_id já existe com outro conteúdo")
            return existing
        payload = approval.model_dump_json()
        updated_proposal = proposal.model_copy(update={"status": ProposalStatus.APPROVED})
        async with self.graph.driver.session() as session:
            result = await session.execute_write(
                self._save_approval_transaction,
                approval,
                payload,
                updated_proposal,
            )
        if result is None:
            raise ApprovalError("A proposta mudou antes da aprovação ser registrada")
        return approval

    async def _save_approval_transaction(self, tx, approval, payload, updated_proposal):  # noqa: ANN001
        result = await tx.run(
                """
                MERGE (a:ApprovalDecision {approval_id: $approval_id})
                ON CREATE SET a.payload_json = $payload,
                              a.proposal_id = $proposal_id
                WITH a
                MATCH (p:ChangeProposal {proposal_id: $proposal_id})
                WHERE p.status = 'pending_approval' AND p.preview_hash = $preview_hash
                SET p.payload_json = $proposal_payload, p.status = 'approved'
                RETURN a.payload_json AS payload
                """,
                approval_id=str(approval.approval_id),
                payload=payload,
                proposal_id=str(approval.proposal_id),
                preview_hash=approval.preview_hash,
                proposal_payload=updated_proposal.model_dump_json(),
            )
        row = await result.single()
        return row["payload"] if row else None

    async def reject_proposal(
        self,
        proposal_id: uuid.UUID,
        reason: str,
        *,
        principal_id: str,
        principal_type: str = "operator",
    ) -> ChangeProposal:
        await self._ensure_schema()
        proposal = await self.get_proposal(proposal_id)
        if proposal.status is not ProposalStatus.PENDING_APPROVAL:
            raise ApprovalError("Somente propostas pendentes podem ser rejeitadas")
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
        async with self.graph.driver.session() as session:
            result = await session.execute_write(
                self._reject_transaction,
                proposal_id,
                updated,
            )
        if result is None:
            raise ApprovalError("A proposta mudou antes da rejeição ser registrada")
        return updated

    async def _reject_transaction(self, tx, proposal_id, updated):  # noqa: ANN001
        result = await tx.run(
                """
                MATCH (p:ChangeProposal {proposal_id: $proposal_id, status: 'pending_approval'})
                SET p.payload_json = $payload, p.status = $status
                RETURN p.proposal_id AS proposal_id
                """,
                proposal_id=str(proposal_id),
                payload=updated.model_dump_json(),
                status=updated.status.value,
            )
        return await result.single()

    async def _parent_versions(self, tx, parent_ids: tuple[uuid.UUID, ...]) -> list[int]:  # noqa: ANN001
        result = await tx.run(
            """
            UNWIND $parent_ids AS parent_id
            MATCH (r:MemoryRevision {revision_id: parent_id})
            RETURN r.version AS version
            """,
            parent_ids=[str(item) for item in parent_ids],
        )
        rows = await result.data()
        if len(rows) != len(parent_ids):
            raise LedgerConflictError("Uma revisão pai não existe no ledger")
        return [int(row["version"]) for row in rows]

    async def _family_legacy_id(self, tx, family_id: uuid.UUID) -> str:  # noqa: ANN001
        result = await tx.run(
            "MATCH (f:MemoryFamily {family_id: $family_id}) RETURN f.legacy_memory_id AS legacy",
            family_id=str(family_id),
        )
        row = await result.single()
        return (
            str(row["legacy"])
            if row and row["legacy"]
            else legacy_memory_id_for_family(family_id)
        )

    async def _assert_expected_heads(self, tx, expected_heads) -> None:  # noqa: ANN001
        expected = self._expected_rows(expected_heads)
        if not expected:
            return
        result = await tx.run(
            """
            UNWIND $expected AS item
            OPTIONAL MATCH (h:MemoryHead {
                head_key: item.family_id + ':' + item.scope + ':' + item.branch
            })
            RETURN item.revision_id AS expected_revision, h.revision_id AS actual_revision
            """,
            expected=expected,
        )
        rows = await result.data()
        if len(rows) != len(expected) or any(
            row["expected_revision"] != row["actual_revision"] for row in rows
        ):
            raise LedgerConflictError("A revisão-base deixou de ser o head atual")

    async def _assert_approval_is_current(self, tx, proposal, approval) -> None:  # noqa: ANN001
        result = await tx.run(
            """
            MATCH (p:ChangeProposal {proposal_id: $proposal_id})
            MATCH (a:ApprovalDecision {approval_id: $approval_id})
            WHERE p.status = 'approved'
              AND a.status = 'issued'
              AND p.preview_hash = $preview_hash
              AND a.preview_hash = $preview_hash
            RETURN p.proposal_id AS proposal_id
            """,
            proposal_id=str(proposal.proposal_id),
            approval_id=str(approval.approval_id),
            preview_hash=proposal.preview_hash,
        )
        if await result.single() is None:
            raise ApprovalError("A proposta ou aprovação já foi consumida ou alterada")

    async def _source_family_ids(self, tx, revision_ids: tuple[uuid.UUID, ...]) -> list[uuid.UUID]:  # noqa: ANN001
        if not revision_ids:
            return []
        result = await tx.run(
            """
            UNWIND $revision_ids AS revision_id
            OPTIONAL MATCH (r:MemoryRevision {revision_id: revision_id})
            RETURN revision_id, r.family_id AS family_id
            """,
            revision_ids=[str(item) for item in revision_ids],
        )
        rows = await result.data()
        if len(rows) != len(revision_ids) or any(row["family_id"] is None for row in rows):
            raise LedgerConflictError("Uma revisão de origem não existe no ledger")
        return list({uuid.UUID(str(row["family_id"])) for row in rows})

    @staticmethod
    def _deterministic_id(kind: str, proposal_id: uuid.UUID, suffix: str = "") -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"decisionssearch:{kind}:{proposal_id}:{suffix}")

    async def _apply_transaction(self, tx, proposal, approval):  # noqa: ANN001
        await self._assert_approval_is_current(tx, proposal, approval)
        await self._assert_expected_heads(tx, proposal.expected_heads)
        if (
            (proposal.conflict_ids and proposal.operation.value != "resolve_conflict")
            or proposal.detector_coverage in {
            ConflictDetectionCoverage.INCOMPLETE,
            ConflictDetectionCoverage.UNKNOWN,
            }
        ):
            raise LedgerConflictError("A proposta possui conflitos ou cobertura incompleta")
        if proposal.operation.value == "resolve_conflict":
            for resolution in proposal.conflict_resolutions:
                conflict_result = await tx.run(
                    "MATCH (c:ConflictCase {conflict_id: $conflict_id}) RETURN c.payload_json AS payload",
                    conflict_id=resolution.conflict_id,
                )
                conflict_row = await conflict_result.single()
                if conflict_row is None:
                    raise LedgerConflictError("Caso de conflito não encontrado")
                conflict = ConflictCase.model_validate_json(conflict_row["payload"])
                if (
                    conflict.status is not ConflictStatus.OPEN
                    or conflict.version != resolution.expected_conflict_version
                    or conflict.claim_path != resolution.claim_path
                ):
                    raise LedgerConflictError("O caso de conflito mudou antes da resolução")
                resolved = conflict.model_copy(
                    update={"status": ConflictStatus.RESOLVED, "version": conflict.version + 1}
                )
                await tx.run(
                    "MATCH (c:ConflictCase {conflict_id: $conflict_id}) "
                    "SET c.payload_json = $payload, c.status = $status, c.version = $version",
                    conflict_id=resolution.conflict_id,
                    payload=resolved.model_dump_json(),
                    status=resolved.status.value,
                    version=resolved.version,
                )
        content = proposal.after
        if proposal.operation.value == "link":
            return await self._apply_relation(tx, proposal, approval)
        if content is None:
            raise MemoryServiceError("Proposta de memória não possui snapshot depois")

        composite_target_family = None
        composite_target_revision = None
        if proposal.operation.value == "create_and_link":
            target_family_id = proposal.relation_target_family_id
            if target_family_id is None:
                raise LedgerConflictError("Refinamento sem família alvo")
            target_family_result = await tx.run(
                "MATCH (f:MemoryFamily {family_id: $family_id}) RETURN f.payload_json AS payload",
                family_id=str(target_family_id),
            )
            target_family_row = await target_family_result.single()
            if target_family_row is None:
                raise LedgerConflictError("A família alvo do refinamento não existe")
            composite_target_family = MemoryFamily.model_validate_json(target_family_row["payload"])
            if composite_target_family.state is not FamilyState.ACTIVE:
                raise LedgerConflictError("A família alvo do refinamento não está ativa")
            if (
                composite_target_family.project != content.project
                or composite_target_family.category != content.category
                or composite_target_family.memory_scope is not content.memory_scope
            ):
                raise LedgerConflictError(
                    "A família alvo do refinamento não é compatível com o conteúdo"
                )
            expected_target = next(
                (
                    item
                    for item in proposal.expected_heads
                    if item[0] == target_family_id
                ),
                None,
            )
            if expected_target is None:
                raise LedgerConflictError("O head alvo do refinamento não foi congelado no preview")
            target_revision_result = await tx.run(
                "MATCH (r:MemoryRevision {revision_id: $revision_id}) RETURN r.payload_json AS payload",
                revision_id=str(expected_target[3]),
            )
            target_revision_row = await target_revision_result.single()
            if target_revision_row is None:
                raise LedgerConflictError("O head alvo do refinamento aponta para revisão inexistente")
            composite_target_revision = MemoryRevision.model_validate_json(target_revision_row["payload"])

        family_id = proposal.target_family_id
        legacy_id = ""
        if proposal.operation.value in {"create", "create_and_link"}:
            family_id = self._deterministic_id("family", proposal.proposal_id)
            legacy_values = dict(content.legacy_ids)
            legacy_id = (
                legacy_values.get("memory_id")
                or legacy_values.get("episode_id")
                or legacy_values.get("procedure_id")
                or legacy_memory_id_for_family(family_id)
            )
            family = MemoryFamily(
                family_id=family_id,
                project=content.project,
                category=content.category,
                memory_scope=content.memory_scope,
                created_by=approval.principal_id,
                legacy_memory_id=legacy_id,
            )
        else:
            if family_id is None:
                raise MemoryServiceError("Proposta sem família alvo")
            legacy_id = await self._family_legacy_id(tx, family_id)
            if not legacy_id:
                legacy_id = MemoryItem.generate_id(content.project, content.category, content.title)
            family = None

        if family_id is None:
            raise MemoryServiceError("Não foi possível resolver a família")
        versions = await self._parent_versions(tx, proposal.base_revision_ids)
        revision_id = self._deterministic_id("revision", proposal.proposal_id)
        proposal_links = proposal.evidence_links or tuple(
            EvidenceLinkSpec(
                evidence_id=evidence.evidence_id,
                stance=EvidenceStance.SUPPORTS,
                confidence=evidence.source_reliability,
            )
            for evidence in proposal.evidence
        )
        evidence_link_ids = tuple(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"decisionssearch:evidence-link:{revision_id}:{link.evidence_id}:{link.claim_path}:{link.stance.value}",
            )
            for link in proposal_links
        )
        revision = MemoryRevision(
            revision_id=revision_id,
            family_id=family_id,
            version=max(versions, default=0) + 1,
            parent_revision_ids=proposal.base_revision_ids,
            content=content,
            content_hash=content_hash(content),
            actor_id=approval.principal_id,
            actor_type=approval.principal_type,
            reason=proposal.reason,
            evidence_ids=proposal.evidence_ids,
            source_revision_ids=proposal.source_revision_ids,
            rollback_of=proposal.restore_revision_id,
            field_origins=proposal.field_origins,
            evidence_link_ids=evidence_link_ids,
            conflict_ids=proposal.conflict_ids,
            merge_manifest_id=(
                self._deterministic_id("merge-manifest", proposal.proposal_id)
                if proposal.operation.value == "merge"
                else None
            ),
        )
        provenance = {
            "schema": "provenance.v1",
            "content_hash": revision.content_hash,
            "parents": [str(item) for item in revision.parent_revision_ids],
            "sources": [str(item) for item in revision.source_revision_ids],
            "evidence_links": [item.model_dump(mode="json") for item in proposal.evidence_links],
            "field_origins": [item.model_dump(mode="json") for item in proposal.field_origins],
            "conflicts": list(proposal.conflict_ids),
            "manifest_id": str(revision.merge_manifest_id) if revision.merge_manifest_id else None,
        }
        revision = revision.model_copy(
            update={
                "provenance_hash": "sha256:" + hashlib.sha256(canonical_json(provenance).encode("utf-8")).hexdigest(),
            }
        )
        sequence_result = await tx.run(
            "MERGE (s:LedgerSequence {id: 'memory'}) SET s.value = coalesce(s.value, 0) + 1 RETURN s.value AS value"
        )
        sequence_row = await sequence_result.single()
        sequence = int(sequence_row["value"] if sequence_row else 1)
        state = (
            RevisionState.INVALIDATED
            if proposal.operation.value == "invalidate"
            else RevisionState.ARCHIVED
            if proposal.operation.value == "archive"
            else RevisionState.SUPERSEDED
            if proposal.operation.value == "supersede"
            else RevisionState.ACTIVE
        )
        merge_source_families = []
        if proposal.operation.value == "merge":
            merge_source_families = [
                item
                for item in await self._source_family_ids(tx, proposal.source_revision_ids)
                if item != family_id
            ]
        merge_manifest: MergeManifest | None = None
        if proposal.operation.value == "merge":
            affected_family_ids = tuple(dict.fromkeys((family_id, *merge_source_families)))
            head_snapshots: list[MergeHeadSnapshot] = []
            for expected_family_id, expected_scope, expected_branch, _expected_revision_id in proposal.expected_heads:
                head_result = await tx.run(
                    "MATCH (h:MemoryHead {head_key: $head_key}) RETURN h.payload_json AS payload",
                    head_key=self._head_key(expected_family_id, expected_scope, expected_branch),
                )
                head_row = await head_result.single()
                if head_row is None:
                    raise LedgerConflictError("Um head do manifesto de merge não existe")
                head = MemoryHead.model_validate_json(head_row["payload"])
                head_snapshots.append(
                    MergeHeadSnapshot(
                        family_id=head.family_id,
                        memory_scope=head.memory_scope,
                        memory_branch=head.memory_branch,
                        revision_id=head.revision_id,
                        sequence=head.sequence,
                    )
                )
            family_result = await tx.run(
                "MATCH (f:MemoryFamily) WHERE f.family_id IN $family_ids "
                "RETURN f.payload_json AS payload",
                family_ids=[str(item) for item in affected_family_ids],
            )
            family_snapshots = tuple(
                MemoryFamily.model_validate_json(row["payload"])
                for row in await family_result.data()
            )
            if len(family_snapshots) != len(affected_family_ids):
                raise LedgerConflictError("O manifesto não conseguiu capturar todas as famílias")
            alias_result = await tx.run(
                "MATCH (a:MemoryAlias) WHERE a.family_id IN $family_ids "
                "RETURN a.payload_json AS payload",
                family_ids=[str(item) for item in affected_family_ids],
            )
            aliases_before = tuple(
                MemoryAlias.model_validate_json(row["payload"])
                for row in await alias_result.data()
            )
            relation_result = await tx.run(
                "MATCH (a:RelationAssertion) RETURN a.payload_json AS payload"
            )
            affected_set = set(affected_family_ids)
            relation_snapshots = tuple(
                relation
                for row in await relation_result.data()
                if (relation := RelationAssertion.model_validate_json(row["payload"])).source_family_id in affected_set
                or relation.target_family_id in affected_set
            )
            created_relation_ids = tuple(
                self._deterministic_id("merge-relation", proposal.proposal_id, source_family_id)
                for source_family_id in merge_source_families
            )
            manifest_core = {
                "manifest_id": str(revision.merge_manifest_id),
                "manifest_schema": "merge-manifest.v1",
                "merge_revision_id": str(revision.revision_id),
                "target_family_id": str(family_id),
                "source_family_ids": [str(item) for item in merge_source_families],
                "previous_heads": [item.model_dump(mode="json") for item in head_snapshots],
                "previous_family_snapshots": [item.model_dump(mode="json") for item in family_snapshots],
                "aliases_before": [item.model_dump(mode="json") for item in aliases_before],
                "affected_relation_snapshots": [item.model_dump(mode="json") for item in relation_snapshots],
                "created_relation_ids": [str(item) for item in created_relation_ids],
                "field_origins": [item.model_dump(mode="json") for item in proposal.field_origins],
                "proposal_id": str(proposal.proposal_id),
                "approval_id": str(approval.approval_id),
            }
            manifest_hash = "sha256:" + hashlib.sha256(
                canonical_json(manifest_core).encode("utf-8")
            ).hexdigest()
            merge_manifest = MergeManifest.model_validate(
                {**manifest_core, "manifest_hash": manifest_hash}
            )
        if family is not None:
            await tx.run(
                """
                CREATE (f:MemoryFamily {
                    family_id: $family_id,
                    project: $project,
                    category: $category,
                    memory_scope: $scope,
                    legacy_memory_id: $legacy_id,
                    payload_json: $payload
                })
                """,
                family_id=str(family.family_id),
                project=family.project,
                category=family.category,
                scope=family.memory_scope.value,
                legacy_id=legacy_id,
                payload=family.model_dump_json(),
            )
            alias = MemoryAlias(
                alias=legacy_id,
                family_id=family.family_id,
                project=family.project,
                category=family.category,
                memory_branch=content.memory_branch,
            )
            await tx.run(
                """
                MERGE (a:MemoryAlias {alias: $alias, family_id: $family_id})
                SET a.payload_json = $payload, a.status = $status
                """,
                alias=alias.alias,
                family_id=str(alias.family_id),
                payload=alias.model_dump_json(),
                status=alias.status.value,
            )
        expected_target = next(
            (
                item[3]
                for item in proposal.expected_heads
                if item[0] == family_id
                and str(item[1]) == str(content.memory_scope)
                and item[2] == content.memory_branch
            ),
            None,
        )
        head_result = await tx.run(
            """
            MATCH (f:MemoryFamily {family_id: $family_id})
            CREATE (r:MemoryRevision {
                revision_id: $revision_id,
                family_id: $family_id,
                version: $version,
                content_hash: $content_hash,
                payload_json: $payload,
                state: $state
            })
            CREATE (r)-[:REVISION_OF]->(f)
            MERGE (h:MemoryHead {head_key: $head_key})
            WITH f, r, h
            WHERE $is_create OR h.revision_id = $expected_revision_id
            SET h.family_id = $family_id,
                h.memory_scope = $scope,
                h.memory_branch = $branch,
                h.revision_id = $revision_id,
                h.sequence = $sequence,
                h.payload_json = $head_payload
            RETURN h.revision_id AS revision_id
            """,
            family_id=str(family_id),
            revision_id=str(revision.revision_id),
            version=revision.version,
            content_hash=revision.content_hash,
            payload=revision.model_dump_json(),
            state=state.value,
            head_key=self._head_key(family_id, content.memory_scope, content.memory_branch),
            scope=content.memory_scope.value,
            branch=content.memory_branch,
            sequence=sequence,
            head_payload=MemoryHead(
                family_id=family_id,
                memory_scope=content.memory_scope,
                memory_branch=content.memory_branch,
                revision_id=revision.revision_id,
                sequence=sequence,
            ).model_dump_json(),
            is_create=proposal.operation.value in {"create", "create_and_link"},
            expected_revision_id=str(expected_target) if expected_target else "",
        )
        if await head_result.single() is None:
            raise LedgerConflictError("O head mudou durante a aplicação da proposta")
        if merge_manifest is not None:
            await tx.run(
                "MERGE (m:MergeManifest {manifest_id: $manifest_id}) "
                "SET m.payload_json = $payload, m.manifest_hash = $manifest_hash",
                manifest_id=str(merge_manifest.manifest_id),
                payload=merge_manifest.model_dump_json(),
                manifest_hash=merge_manifest.manifest_hash,
            )
        links = proposal_links
        evidence_by_id = {item.evidence_id: item for item in proposal.evidence}
        for link in links:
            evidence = evidence_by_id[link.evidence_id]
            evidence_result = await tx.run(
                """
                MERGE (e:Evidence {evidence_id: $evidence_id})
                ON CREATE SET e.payload_json = $payload
                ON MATCH SET e.payload_json = coalesce(e.payload_json, $payload)
                WITH e
                WHERE e.payload_json = $payload
                MATCH (r:MemoryRevision {revision_id: $revision_id})
                MERGE (r)-[:SUPPORTED_BY {
                    link_id: $link_id,
                    stance: $stance,
                    confidence: $confidence,
                    claim_path: $claim_path,
                    excerpt_hash: $excerpt_hash
                }]->(e)
                RETURN e.evidence_id AS evidence_id
                """,
                evidence_id=str(evidence.evidence_id),
                payload=evidence.model_dump_json(),
                revision_id=str(revision.revision_id),
                link_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"decisionssearch:evidence-link:{revision.revision_id}:{link.evidence_id}:{link.claim_path}:{link.stance.value}",
                    )
                ),
                stance=link.stance.value,
                confidence=link.confidence,
                claim_path=link.claim_path,
                excerpt_hash=link.excerpt_hash,
            )
            if await evidence_result.single() is None:
                raise LedgerConflictError(
                    "evidence_id já existe com outro conteúdo",
                    context={"evidence_id": str(evidence.evidence_id)},
                )
        for parent_id in proposal.base_revision_ids:
            await tx.run(
                """
                MATCH (parent:MemoryRevision {revision_id: $parent_id})
                MATCH (child:MemoryRevision {revision_id: $child_id})
                CREATE (t:RevisionTransition {
                    transition_id: $transition_id,
                    family_id: parent.family_id,
                    from_revision_id: $parent_id,
                    to_revision_id: $child_id,
                    state: 'superseded',
                    reason: $reason,
                    actor_id: $actor_id,
                    proposal_id: $proposal_id,
                    created_at: $created_at
                })
                CREATE (parent)-[:SUPERSEDED_BY]->(child)
                """,
                parent_id=str(parent_id),
                child_id=str(revision.revision_id),
                transition_id=str(self._deterministic_id("transition", proposal.proposal_id, parent_id)),
                family_id=str(family_id),
                reason=proposal.reason,
                actor_id=approval.principal_id,
                proposal_id=str(proposal.proposal_id),
                created_at=utc_now().isoformat(),
            )
        await tx.run(
            """
            MATCH (r:MemoryRevision {revision_id: $revision_id})
            CREATE (t:RevisionTransition {
                transition_id: $transition_id,
                family_id: $family_id,
                to_revision_id: $revision_id,
                state: $state,
                reason: $reason,
                actor_id: $actor_id,
                proposal_id: $proposal_id,
                created_at: $created_at
            })
            """,
            transition_id=str(self._deterministic_id("transition", proposal.proposal_id, "target")),
            family_id=str(family_id),
            revision_id=str(revision.revision_id),
            state=state.value,
            reason=proposal.reason,
            actor_id=approval.principal_id,
            proposal_id=str(proposal.proposal_id),
            created_at=utc_now().isoformat(),
        )
        # Fecha a validade registrada dos pais somente quando a nova revisão
        # passa a ser efetiva imediatamente. Uma revisão com valid_from futuro
        # precisa coexistir com o pai para consultas históricas/temporais.
        closes_recorded_history = (
            proposal.operation.value in {"invalidate", "supersede", "archive"}
            or content.valid_from is None
            or content.valid_from <= revision.recorded_from
        )
        if closes_recorded_history:
            for parent_id in proposal.base_revision_ids:
                parent_rows = await tx.run(
                    "MATCH (parent:MemoryRevision {revision_id: $revision_id}) "
                    "RETURN parent.payload_json AS payload",
                    revision_id=str(parent_id),
                )
                parent_row = await parent_rows.single()
                if parent_row and parent_row["payload"]:
                    parent = MemoryRevision.model_validate_json(parent_row["payload"])
                    if parent.recorded_to is None or parent.recorded_to > revision.recorded_from:
                        closed_parent = parent.model_copy(update={"recorded_to": revision.recorded_from})
                        await tx.run(
                            "MATCH (parent:MemoryRevision {revision_id: $revision_id}) "
                            "SET parent.payload_json = $payload",
                            revision_id=str(parent_id),
                            payload=closed_parent.model_dump_json(),
                        )
        revision_is_scheduled = revision.content.valid_from is not None and revision.content.valid_from > utc_now()
        # A projeção legada representa o estado consultável agora. A revisão
        # futura fica somente no ledger até o evento agendado ser liberado.
        if not revision_is_scheduled:
            await self._upsert_legacy_projection(tx, revision, legacy_id, state)
        alias = MemoryAlias(
            alias=legacy_id,
            family_id=family_id,
            project=content.project,
            category=content.category,
            memory_branch=content.memory_branch,
        )
        await tx.run(
            """
            MERGE (a:MemoryAlias {alias: $alias, family_id: $family_id})
            SET a.payload_json = $payload, a.status = $status
            """,
            alias=alias.alias,
            family_id=str(alias.family_id),
            payload=alias.model_dump_json(),
            status=alias.status.value,
        )
        related_memory_ids = tuple(
            str(item)
            for item in (content.structured_payload or {}).get("related_memory_ids", [])
        )
        for related_memory_id in related_memory_ids:
            target_result = await tx.run(
                """
                MATCH (target_alias:MemoryAlias {alias: $alias, status: 'resolved'})
                MATCH (target_head:MemoryHead)
                WHERE target_head.head_key = target_alias.family_id + ':semantic:semantic'
                  AND target_alias.family_id <> $source_family_id
                RETURN target_alias.family_id AS target_family_id,
                       target_head.revision_id AS target_revision_id
                ORDER BY target_head.sequence DESC
                LIMIT 1
                """,
                alias=related_memory_id,
                source_family_id=str(family_id),
            )
            target_row = await target_result.single()
            if target_row is None:
                continue
            target_family_id = uuid.UUID(str(target_row["target_family_id"]))
            relation_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"decisionssearch:episode-related:{family_id}:{target_family_id}:{revision.revision_id}",
            )
            relation = RelationAssertion(
                assertion_id=relation_id,
                source_family_id=family_id,
                target_family_id=target_family_id,
                source_revision_id=revision.revision_id,
                target_revision_id=uuid.UUID(str(target_row["target_revision_id"])),
                relation_type="LEARNED_FROM",
                memory_scope=content.memory_scope,
                memory_branch=content.memory_branch,
                rationale="Relação declarada pelo episódio legado",
                created_by=approval.principal_id,
                proposal_id=proposal.proposal_id,
            )
            await tx.run(
                """
                MERGE (a:RelationAssertion {assertion_id: $assertion_id})
                ON CREATE SET a.payload_json = $payload, a.state = 'active'
                WITH a
                MATCH (source:MemoryFamily {family_id: $source_family_id})
                MATCH (target:MemoryFamily {family_id: $target_family_id})
                MERGE (source)-[:ASSERTS_RELATION]->(a)-[:RELATES_TO]->(target)
                """,
                assertion_id=str(relation_id),
                payload=relation.model_dump_json(),
                source_family_id=str(family_id),
                target_family_id=str(target_family_id),
            )
        composite_relation = None
        if proposal.operation.value == "create_and_link":
            if composite_target_family is None or composite_target_revision is None:
                raise LedgerConflictError("O alvo do refinamento não foi carregado")
            composite_relation = RelationAssertion(
                assertion_id=self._deterministic_id("relation", proposal.proposal_id),
                source_family_id=family_id,
                target_family_id=composite_target_family.family_id,
                source_revision_id=revision.revision_id,
                target_revision_id=composite_target_revision.revision_id,
                relation_type=proposal.relation_type,
                memory_scope=content.memory_scope,
                memory_branch=content.memory_branch,
                created_by=approval.principal_id,
                evidence_ids=proposal.evidence_ids,
                rationale=proposal.reason,
                proposal_id=proposal.proposal_id,
            )
            await tx.run(
                """
                MATCH (source:MemoryFamily {family_id: $source_family_id})
                MATCH (target:MemoryFamily {family_id: $target_family_id})
                MERGE (a:RelationAssertion {assertion_id: $assertion_id})
                ON CREATE SET a.payload_json = $payload, a.state = 'active'
                WITH source, target, a
                MERGE (source)-[:ASSERTS_RELATION]->(a)-[:RELATES_TO]->(target)
                """,
                source_family_id=str(family_id),
                target_family_id=str(composite_target_family.family_id),
                assertion_id=str(composite_relation.assertion_id),
                payload=composite_relation.model_dump_json(),
            )
            relation_links = proposal.evidence_links or tuple(
                EvidenceLinkSpec(
                    evidence_id=evidence.evidence_id,
                    stance=EvidenceStance.SUPPORTS,
                    confidence=evidence.source_reliability,
                )
                for evidence in proposal.evidence
            )
            evidence_by_id = {item.evidence_id: item for item in proposal.evidence}
            for link in relation_links:
                evidence = evidence_by_id[link.evidence_id]
                evidence_result = await tx.run(
                    """
                    MERGE (e:Evidence {evidence_id: $evidence_id})
                    ON CREATE SET e.payload_json = $payload
                    ON MATCH SET e.payload_json = coalesce(e.payload_json, $payload)
                    WITH e
                    WHERE e.payload_json = $payload
                    MATCH (a:RelationAssertion {assertion_id: $assertion_id})
                    MERGE (a)-[:SUPPORTED_BY {
                        link_id: $link_id,
                        stance: $stance,
                        confidence: $confidence,
                        claim_path: $claim_path,
                        excerpt_hash: $excerpt_hash
                    }]->(e)
                    RETURN e.evidence_id AS evidence_id
                    """,
                    evidence_id=str(evidence.evidence_id),
                    payload=evidence.model_dump_json(),
                    assertion_id=str(composite_relation.assertion_id),
                    link_id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"decisionssearch:relation-evidence:{composite_relation.assertion_id}:{link.evidence_id}:{link.claim_path}:{link.stance.value}",
                        )
                    ),
                    stance=link.stance.value,
                    confidence=link.confidence,
                    claim_path=link.claim_path,
                    excerpt_hash=link.excerpt_hash,
                )
                if await evidence_result.single() is None:
                    raise LedgerConflictError(
                        "evidence_id já existe com outro conteúdo",
                        context={"evidence_id": str(evidence.evidence_id)},
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
            if replacement_expected is None:
                raise LedgerConflictError("A memória substituta não possui head ativo")
            replacement_revision_id = proposal.base_revision_ids[0] if proposal.base_revision_ids else revision.revision_id
            replacement_relation_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"decisionssearch:replacement-relation:{proposal.proposal_id}",
            )
            replacement_relation = RelationAssertion(
                assertion_id=replacement_relation_id,
                source_family_id=proposal.replacement_family_id,
                target_family_id=family_id,
                source_revision_id=replacement_expected[3],
                target_revision_id=replacement_revision_id,
                relation_type="DEPRECATES",
                memory_scope=content.memory_scope,
                memory_branch=content.memory_branch,
                rationale=proposal.reason,
                created_by=approval.principal_id,
                proposal_id=proposal.proposal_id,
            )
            await tx.run(
                """
                MERGE (a:RelationAssertion {assertion_id: $assertion_id})
                ON CREATE SET a.payload_json = $payload, a.state = 'active'
                WITH a
                MATCH (source:MemoryFamily {family_id: $source_family_id})
                MATCH (target:MemoryFamily {family_id: $target_family_id})
                MERGE (source)-[:ASSERTS_RELATION]->(a)-[:RELATES_TO]->(target)
                """,
                assertion_id=str(replacement_relation_id),
                payload=replacement_relation.model_dump_json(),
                source_family_id=str(proposal.replacement_family_id),
                target_family_id=str(family_id),
            )
        if merge_source_families:
            for source_family_id in merge_source_families:
                family_result = await tx.run(
                    "MATCH (f:MemoryFamily {family_id: $family_id}) RETURN f.payload_json AS payload",
                    family_id=str(source_family_id),
                )
                family_row = await family_result.single()
                if family_row is None:
                    raise LedgerConflictError("A família de origem da fusão não existe")
                source_family = MemoryFamily.model_validate_json(family_row["payload"])
                if source_family.state is not FamilyState.ACTIVE:
                    raise LedgerConflictError("A família de origem já não está ativa")
                merged_family = source_family.model_copy(
                    update={
                        "state": FamilyState.MERGED,
                        "merged_into_family_id": family_id,
                        "retired_at": utc_now(),
                        "retirement_reason": proposal.reason,
                    }
                )
                await tx.run(
                    """
                    MATCH (f:MemoryFamily {family_id: $family_id})
                    SET f.payload_json = $payload, f.state = $state,
                        f.merged_into_family_id = $merged_into_family_id
                    """,
                    family_id=str(source_family_id),
                    payload=merged_family.model_dump_json(),
                    state=merged_family.state.value,
                    merged_into_family_id=str(family_id),
                )
                expected_source = next(
                    (
                        item
                        for item in proposal.expected_heads
                        if item[0] == source_family_id
                    ),
                    None,
                )
                if expected_source is None:
                    raise LedgerConflictError("O merge não capturou o head da família de origem")
                head_result = await tx.run(
                    "MATCH (h:MemoryHead {head_key: $head_key, revision_id: $revision_id}) "
                    "WITH h DETACH DELETE h RETURN 1 AS deleted",
                    head_key=self._head_key(
                        source_family_id, expected_source[1], expected_source[2]
                    ),
                    revision_id=str(expected_source[3]),
                )
                head_row = await head_result.single()
                if head_row is None or int(head_row["deleted"] or 0) != 1:
                    raise LedgerConflictError("O head de origem mudou durante o merge")
                await tx.run(
                    "MATCH (m:MemoryItem {family_id: $family_id}) SET m.status = 'deprecated', m.invalid_at = $invalid_at",
                    family_id=str(source_family_id),
                    invalid_at=utc_now().isoformat(),
                )
                alias_result = await tx.run(
                    "MATCH (a:MemoryAlias {family_id: $family_id}) RETURN a.alias AS alias, a.payload_json AS payload",
                    family_id=str(source_family_id),
                )
                for alias_row in await alias_result.data():
                    old_alias = MemoryAlias.model_validate_json(alias_row["payload"])
                    retired_alias = old_alias.model_copy(update={"status": MemoryAliasStatus.RETIRED})
                    new_alias = old_alias.model_copy(
                        update={"family_id": family_id, "status": MemoryAliasStatus.RESOLVED}
                    )
                    await tx.run(
                        """
                        MERGE (a:MemoryAlias {alias: $alias, family_id: $family_id})
                        SET a.payload_json = $payload, a.status = 'resolved'
                        WITH a
                        MATCH (old:MemoryAlias {alias: $alias, family_id: $old_family_id})
                        SET old.payload_json = $retired_payload, old.status = 'retired'
                        """,
                        alias=old_alias.alias,
                        family_id=str(family_id),
                        old_family_id=str(source_family_id),
                        payload=new_alias.model_dump_json(),
                        retired_payload=retired_alias.model_dump_json(),
                    )
                source_revision_id = None
                for candidate_revision_id in proposal.source_revision_ids:
                    source_revision_row = await tx.run(
                        "MATCH (r:MemoryRevision {revision_id: $revision_id}) RETURN r.family_id AS family_id",
                        revision_id=str(candidate_revision_id),
                    )
                    source_revision_data = await source_revision_row.single()
                    if source_revision_data and source_revision_data["family_id"] == str(source_family_id):
                        source_revision_id = candidate_revision_id
                        break
                relation = RelationAssertion(
                    assertion_id=self._deterministic_id("merge-relation", proposal.proposal_id, source_family_id),
                    source_family_id=source_family_id,
                    target_family_id=family_id,
                    source_revision_id=source_revision_id,
                    target_revision_id=revision.revision_id,
                    relation_type="MERGED_INTO",
                    memory_scope=content.memory_scope,
                    memory_branch=content.memory_branch,
                    created_by=approval.principal_id,
                    evidence_ids=proposal.evidence_ids,
                    proposal_id=proposal.proposal_id,
                )
                await tx.run(
                    """
                    MATCH (source:MemoryFamily {family_id: $source_family_id})
                    MATCH (target:MemoryFamily {family_id: $target_family_id})
                    CREATE (a:RelationAssertion {
                        assertion_id: $assertion_id, payload_json: $payload, state: 'active'
                    })
                    CREATE (source)-[:ASSERTS_RELATION]->(a)-[:RELATES_TO]->(target)
                    """,
                    source_family_id=str(source_family_id),
                    target_family_id=str(family_id),
                    assertion_id=str(relation.assertion_id),
                    payload=relation.model_dump_json(),
                )
                source_event = OutboxEvent(
                    event_id=self._deterministic_id("outbox", proposal.proposal_id, f"source:{source_family_id}"),
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
                await self._create_outbox(tx, source_event)
        event = OutboxEvent(
            event_id=self._deterministic_id("outbox", proposal.proposal_id, "target"),
            event_type="memory.revision.applied",
            family_id=family_id,
            revision_id=revision.revision_id,
            content_hash=revision.content_hash,
            sequence=sequence,
            available_at=content.valid_from if revision_is_scheduled else utc_now(),
            payload=(
                ("operation", proposal.operation.value),
                ("state", state.value),
                ("scope", content.memory_scope.value),
                ("branch", content.memory_branch),
            ),
        )
        await self._create_outbox(tx, event)
        if composite_relation is not None:
            relation_event = OutboxEvent(
                event_id=self._deterministic_id("outbox", proposal.proposal_id, "relation"),
                event_type="memory.relation.applied",
                family_id=composite_relation.source_family_id,
                revision_id=None,
                content_hash="sha256:" + hashlib.sha256(
                    composite_relation.model_dump_json().encode("utf-8")
                ).hexdigest(),
                sequence=await self._next_sequence(tx),
                payload=(
                    ("operation", proposal.operation.value),
                    ("assertion_id", str(composite_relation.assertion_id)),
                ),
            )
            await self._create_outbox(tx, relation_event)
        if content.valid_to and content.valid_to > utc_now():
            await self._create_outbox(
                tx,
                OutboxEvent(
                    event_id=self._deterministic_id("outbox", proposal.proposal_id, "expiry"),
                    event_type="memory.validity.expired",
                    family_id=family_id,
                    revision_id=revision.revision_id,
                    content_hash=revision.content_hash,
                    sequence=sequence,
                    available_at=content.valid_to,
                    payload=(
                        ("operation", "validity_expired"),
                        ("scope", content.memory_scope.value),
                        ("branch", content.memory_branch),
                    ),
                ),
            )
        await tx.run(
            """
            MATCH (p:ChangeProposal {proposal_id: $proposal_id})
            SET p.payload_json = $proposal_payload, p.status = 'applied'
            MATCH (a:ApprovalDecision {approval_id: $approval_id})
            SET a.payload_json = $approval_payload, a.status = 'consumed'
            """,
            proposal_id=str(proposal.proposal_id),
            proposal_payload=proposal.model_copy(
                update={
                    "status": ProposalStatus.APPLIED,
                    "applied_revision_id": revision.revision_id,
                    "applied_relation_id": (
                        composite_relation.assertion_id if composite_relation is not None else None
                    ),
                }
            ).model_dump_json(),
            approval_id=str(approval.approval_id),
            approval_payload=approval.model_copy(
                update={"status": ApprovalStatus.CONSUMED, "consumed_at": utc_now()}
            ).model_dump_json(),
        )
        return revision.model_dump_json()

    async def _create_outbox(self, tx, event: OutboxEvent) -> None:  # noqa: ANN001
        await tx.run(
            """
            MERGE (o:OutboxEvent {event_id: $event_id})
            ON CREATE SET o.family_id = $family_id,
                          o.revision_id = $revision_id,
                          o.sequence = $sequence,
                          o.status = $status,
                          o.content_hash = $content_hash,
                          o.available_at = $available_at,
                          o.lease_until = $lease_until,
                          o.claimed_by = $claimed_by,
                          o.claim_token = $claim_token,
                          o.attempts = $attempts,
                          o.last_error = $last_error,
                          o.payload_json = $payload,
                          o.created_at = $created_at
            """,
            event_id=str(event.event_id),
            family_id=str(event.family_id),
            revision_id=str(event.revision_id) if event.revision_id else None,
            sequence=event.sequence,
            status=event.status.value,
            content_hash=event.content_hash,
            available_at=event.available_at.isoformat(),
            lease_until=event.lease_until.isoformat() if event.lease_until else None,
            claimed_by=event.claimed_by,
            claim_token=event.claim_token,
            attempts=event.attempts,
            last_error=event.last_error,
            payload=event.model_dump_json(),
            created_at=event.created_at.isoformat(),
        )

    async def _upsert_legacy_projection(self, tx, revision, legacy_id: str, state) -> None:  # noqa: ANN001
        content = revision.content
        legacy_status = "active" if state is RevisionState.ACTIVE else "deprecated"
        await tx.run(
            """
            MERGE (m:MemoryItem {memory_id: $memory_id})
            SET m.family_id = $family_id,
                m.revision_id = $revision_id,
                m.project = $project,
                m.category = $category,
                m.branch = $branch,
                m.domain = $domain,
                m.modules = $modules,
                m.title = $title,
                m.summary = $summary,
                m.details = $details,
                m.objective = $objective,
                m.trigger = $trigger,
                m.stakeholders = $stakeholders,
                m.action_triggers = $action_triggers,
                m.related_files = $related_files,
                m.business_rules = $business_rules,
                m.architectural_rationale = $architectural_rationale,
                m.examples = $examples,
                m.alternatives_considered = $alternatives,
                m.weight_manual = $weight_manual,
                m.weight_confidence = $weight_confidence,
                m.weight_usage = $weight_usage,
                m.weight_feedback = $weight_feedback,
                m.weight_contextual = $weight_contextual,
                m.significance = $significance,
                m.last_accessed_at = $last_accessed_at,
                m.effective_weight = $effective_weight,
                m.status = $status,
                m.valid_at = $valid_at,
                m.invalid_at = $valid_to,
                m.source_hash = $source_hash,
                m.evidence_count = $evidence_count,
                m.updated_at = $updated_at
            """,
            memory_id=legacy_id,
            family_id=str(revision.family_id),
            revision_id=str(revision.revision_id),
            project=content.project,
            category=content.category,
            branch=content.memory_branch,
            domain=list(content.domain),
            modules=list(content.modules),
            title=content.title,
            summary=content.summary,
            details=content.details,
            objective=content.objective,
            trigger=content.trigger,
            stakeholders=list(content.stakeholders),
            action_triggers=list(content.action_triggers),
            related_files=list(content.related_files),
            business_rules=list(content.business_rules),
            architectural_rationale=content.architectural_rationale,
            examples=list(content.examples),
            alternatives=list(content.alternatives_considered),
            weight_manual=content.weight_manual if content.weight_manual is not None else 0.5,
            weight_confidence=content.weight_confidence,
            weight_usage=content.weight_usage,
            weight_feedback=content.weight_feedback,
            weight_contextual=content.weight_contextual,
            significance=content.significance,
            last_accessed_at=content.last_accessed_at.isoformat() if content.last_accessed_at else None,
            effective_weight=_effective_weight(content),
            status=legacy_status,
            valid_at=content.valid_from.isoformat() if content.valid_from else revision.created_at.isoformat(),
            valid_to=content.valid_to.isoformat() if content.valid_to else None,
            source_hash=revision.content_hash,
            evidence_count=len(revision.evidence_ids),
            updated_at=revision.created_at.isoformat(),
        )
        await tx.run(
            """
            MERGE (a:MemoryAlias {alias: $alias, family_id: $family_id})
            SET a.payload_json = $alias_payload, a.status = 'resolved', a.project = $project, a.category = $category,
                a.memory_branch = $branch
            """,
            alias=legacy_id,
            family_id=str(revision.family_id),
            alias_payload=MemoryAlias(
                alias=legacy_id,
                family_id=revision.family_id,
                project=content.project,
                category=content.category,
                memory_branch=content.memory_branch,
            ).model_dump_json(),
            project=content.project,
            category=content.category,
            branch=content.memory_branch,
        )
        await tx.run(
            """
            MATCH (m:MemoryItem {memory_id: $memory_id})
            MERGE (p:Project {name: $project})
            MERGE (m)-[:IN_PROJECT]->(p)
            MERGE (c:Category {name: $category})
            MERGE (m)-[:IN_CATEGORY]->(c)
            """,
            memory_id=legacy_id,
            project=content.project,
            category=content.category,
        )

    async def _apply_relation(self, tx, proposal, approval):  # noqa: ANN001
        source_family_id = proposal.target_family_id
        target_family_id = proposal.relation_target_family_id
        if source_family_id is None or target_family_id is None:
            raise MemoryServiceError("Relação sem famílias de origem e destino")
        existing_result = await tx.run(
            "MATCH (a:RelationAssertion {state: 'active'}) RETURN a.payload_json AS payload"
        )
        for row in await existing_result.data():
            existing = RelationAssertion.model_validate_json(row["payload"])
            same_pair = (
                existing.source_family_id == source_family_id
                and existing.target_family_id == target_family_id
            ) or (
                proposal.relation_type == "RELATED_TO"
                and existing.source_family_id == target_family_id
                and existing.target_family_id == source_family_id
            )
            if existing.relation_type == proposal.relation_type and same_pair:
                raise LedgerConflictError("A relação ativa já existe")
        source_revision_id = None
        target_revision_id = None
        for family_id, _scope, _branch, revision_id in proposal.expected_heads:
            if family_id == source_family_id:
                source_revision_id = revision_id
            if family_id == target_family_id:
                target_revision_id = revision_id
        assertion = RelationAssertion(
            assertion_id=self._deterministic_id("relation", proposal.proposal_id),
            source_family_id=source_family_id,
            target_family_id=target_family_id,
            source_revision_id=source_revision_id,
            target_revision_id=target_revision_id,
            relation_type=proposal.relation_type,
            memory_scope=MemoryScope(str(proposal.expected_heads[0][1])) if proposal.expected_heads else MemoryScope.SEMANTIC,
            memory_branch=proposal.target_branch,
            created_by=approval.principal_id,
            evidence_ids=proposal.evidence_ids,
            rationale=proposal.reason,
            proposal_id=proposal.proposal_id,
        )
        sequence = await self._next_sequence(tx)
        event = OutboxEvent(
            event_id=self._deterministic_id("outbox", proposal.proposal_id, "relation"),
            event_type="memory.relation.applied",
            family_id=source_family_id,
            revision_id=None,
            content_hash="sha256:" + hashlib.sha256(assertion.model_dump_json().encode("utf-8")).hexdigest(),
            sequence=sequence,
            payload=(("operation", "link"), ("assertion_id", str(assertion.assertion_id))),
        )
        await tx.run(
            """
            MATCH (source:MemoryFamily {family_id: $source_family_id})
            MATCH (target:MemoryFamily {family_id: $target_family_id})
            MERGE (a:RelationAssertion {assertion_id: $assertion_id})
            ON CREATE SET a.payload_json = $payload, a.state = 'active'
            WITH source, target, a
            MERGE (source)-[:ASSERTS_RELATION]->(a)-[:RELATES_TO]->(target)
            WITH a
            MATCH (p:ChangeProposal {proposal_id: $proposal_id})
            SET p.payload_json = $proposal_payload, p.status = 'applied'
            WITH a
            MATCH (decision:ApprovalDecision {approval_id: $approval_id})
            SET decision.payload_json = $approval_payload, decision.status = 'consumed'
            RETURN a.assertion_id AS assertion_id
            """,
            source_family_id=str(source_family_id),
            target_family_id=str(target_family_id),
            assertion_id=str(assertion.assertion_id),
            payload=assertion.model_dump_json(),
            proposal_id=str(proposal.proposal_id),
            proposal_payload=proposal.model_copy(
                update={
                    "status": ProposalStatus.APPLIED,
                    "applied_relation_id": assertion.assertion_id,
                }
            ).model_dump_json(),
            approval_id=str(approval.approval_id),
            approval_payload=approval.model_copy(
                update={"status": ApprovalStatus.CONSUMED, "consumed_at": utc_now()}
            ).model_dump_json(),
        )
        relation_links = proposal.evidence_links or tuple(
            EvidenceLinkSpec(
                evidence_id=evidence.evidence_id,
                stance=EvidenceStance.SUPPORTS,
                confidence=evidence.source_reliability,
            )
            for evidence in proposal.evidence
        )
        evidence_by_id = {item.evidence_id: item for item in proposal.evidence}
        for link in relation_links:
            evidence = evidence_by_id[link.evidence_id]
            evidence_result = await tx.run(
                """
                MERGE (e:Evidence {evidence_id: $evidence_id})
                ON CREATE SET e.payload_json = $payload
                ON MATCH SET e.payload_json = coalesce(e.payload_json, $payload)
                WITH e
                WHERE e.payload_json = $payload
                MATCH (a:RelationAssertion {assertion_id: $assertion_id})
                MERGE (a)-[:SUPPORTED_BY {
                    link_id: $link_id,
                    stance: $stance,
                    confidence: $confidence,
                    claim_path: $claim_path,
                    excerpt_hash: $excerpt_hash
                }]->(e)
                RETURN e.evidence_id AS evidence_id
                """,
                evidence_id=str(evidence.evidence_id),
                payload=evidence.model_dump_json(),
                assertion_id=str(assertion.assertion_id),
                link_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"decisionssearch:relation-evidence:{assertion.assertion_id}:{link.evidence_id}:{link.claim_path}:{link.stance.value}",
                    )
                ),
                stance=link.stance.value,
                confidence=link.confidence,
                claim_path=link.claim_path,
                excerpt_hash=link.excerpt_hash,
            )
            if await evidence_result.single() is None:
                raise LedgerConflictError(
                    "evidence_id já existe com outro conteúdo",
                    context={"evidence_id": str(evidence.evidence_id)},
                )
        event = event.model_copy(update={"sequence": await self._next_sequence(tx)})
        await self._create_outbox(tx, event)
        return assertion.model_dump_json()

    async def _apply_unmerge_transaction(self, tx, proposal, approval):  # noqa: ANN001
        """Restaura um merge somente se o estado afetado ainda for o mesmo."""

        await self._assert_approval_is_current(tx, proposal, approval)
        await self._assert_expected_heads(tx, proposal.expected_heads)
        if proposal.merge_manifest_id is None:
            raise LedgerConflictError("Unmerge sem manifesto")
        manifest_result = await tx.run(
            "MATCH (m:MergeManifest {manifest_id: $manifest_id}) RETURN m.payload_json AS payload",
            manifest_id=str(proposal.merge_manifest_id),
        )
        manifest_row = await manifest_result.single()
        if manifest_row is None:
            raise LedgerConflictError("Manifesto de fusão não encontrado")
        manifest = MergeManifest.model_validate_json(manifest_row["payload"])
        if manifest.manifest_hash != proposal.expected_manifest_hash:
            raise LedgerConflictError("O manifesto mudou desde a proposta de unmerge")

        target_snapshot = next(
            (item for item in manifest.previous_heads if item.family_id == manifest.target_family_id),
            None,
        )
        if target_snapshot is None:
            raise LedgerConflictError("Manifesto sem head da família alvo")
        target_head_result = await tx.run(
            "MATCH (h:MemoryHead {head_key: $head_key}) RETURN h.revision_id AS revision_id",
            head_key=self._head_key(
                target_snapshot.family_id,
                target_snapshot.memory_scope,
                target_snapshot.memory_branch,
            ),
        )
        target_head = await target_head_result.single()
        if target_head is None or target_head["revision_id"] != str(manifest.merge_revision_id):
            raise LedgerConflictError("O head do merge mudou desde o manifesto")
        for snapshot in manifest.previous_heads:
            if snapshot.family_id == manifest.target_family_id:
                continue
            source_head = await tx.run(
                "MATCH (h:MemoryHead {head_key: $head_key}) RETURN h.revision_id AS revision_id",
                head_key=self._head_key(snapshot.family_id, snapshot.memory_scope, snapshot.memory_branch),
            )
            if await source_head.single() is not None:
                raise LedgerConflictError("Um head de origem foi recriado após o merge")

        affected_family_ids = {manifest.target_family_id, *manifest.source_family_ids}
        family_result = await tx.run(
            "MATCH (f:MemoryFamily) WHERE f.family_id IN $family_ids RETURN f.payload_json AS payload",
            family_ids=[str(item) for item in affected_family_ids],
        )
        current_families = {
            family.family_id: family
            for row in await family_result.data()
            if (family := MemoryFamily.model_validate_json(row["payload"]))
        }
        for snapshot in manifest.previous_family_snapshots:
            current = current_families.get(snapshot.family_id)
            if current is None:
                raise LedgerConflictError("Uma família do manifesto não existe mais")
            if snapshot.family_id in manifest.source_family_ids:
                if current.state is not FamilyState.MERGED or current.merged_into_family_id != manifest.target_family_id:
                    raise LedgerConflictError("O estado de uma família de origem mudou após o merge")
                immutable_fields = (
                    "project",
                    "category",
                    "memory_scope",
                    "created_at",
                    "created_by",
                    "legacy_memory_id",
                    "migration_run_id",
                )
                if any(getattr(current, field) != getattr(snapshot, field) for field in immutable_fields):
                    raise LedgerConflictError("A identidade de uma família de origem mudou após o merge")
            elif current.model_dump(mode="json") != snapshot.model_dump(mode="json"):
                raise LedgerConflictError("A família alvo mudou após o merge")

        alias_names = tuple(dict.fromkeys(alias.alias for alias in manifest.aliases_before))
        alias_result = await tx.run(
            "MATCH (a:MemoryAlias) WHERE a.alias IN $aliases RETURN a.payload_json AS payload",
            aliases=list(alias_names),
        )
        current_aliases = [MemoryAlias.model_validate_json(row["payload"]) for row in await alias_result.data()]
        expected_aliases: list[MemoryAlias] = []
        for alias in manifest.aliases_before:
            if alias.family_id in manifest.source_family_ids:
                expected_aliases.extend(
                    (
                        alias.model_copy(update={"status": MemoryAliasStatus.RETIRED}),
                        alias.model_copy(
                            update={
                                "family_id": manifest.target_family_id,
                                "status": MemoryAliasStatus.RESOLVED,
                            }
                        ),
                    )
                )
            else:
                expected_aliases.append(alias)
        if sorted(canonical_json(item.model_dump(mode="json")) for item in current_aliases) != sorted(
            canonical_json(item.model_dump(mode="json")) for item in expected_aliases
        ):
            raise LedgerConflictError("Um alias afetado mudou após o merge")

        relation_result = await tx.run("MATCH (a:RelationAssertion) RETURN a.payload_json AS payload")
        current_relations = {
            relation.assertion_id: relation
            for row in await relation_result.data()
            if (relation := RelationAssertion.model_validate_json(row["payload"])).source_family_id in affected_family_ids
            or relation.target_family_id in affected_family_ids
        }
        expected_relations = {item.assertion_id: item for item in manifest.affected_relation_snapshots}
        for relation_id in manifest.created_relation_ids:
            relation = current_relations.get(relation_id)
            if relation is None or relation.state is not RelationState.ACTIVE:
                raise LedgerConflictError("Uma relação criada pelo merge mudou após o merge")
            expected_relations[relation_id] = relation
        if set(current_relations) != set(expected_relations):
            raise LedgerConflictError("Relações afetadas mudaram após o merge")
        for relation_id, expected in expected_relations.items():
            if relation_id not in manifest.created_relation_ids and current_relations[relation_id].model_dump(mode="json") != expected.model_dump(mode="json"):
                raise LedgerConflictError("Uma relação histórica afetada mudou após o merge")

        sequence = await self._next_sequence(tx)
        for snapshot in manifest.previous_heads:
            await tx.run(
                "MERGE (h:MemoryHead {head_key: $head_key}) "
                "SET h.family_id = $family_id, h.memory_scope = $scope, h.memory_branch = $branch, "
                "h.revision_id = $revision_id, h.sequence = $sequence, h.payload_json = $payload",
                head_key=self._head_key(snapshot.family_id, snapshot.memory_scope, snapshot.memory_branch),
                family_id=str(snapshot.family_id),
                scope=snapshot.memory_scope.value,
                branch=snapshot.memory_branch,
                revision_id=str(snapshot.revision_id),
                sequence=sequence,
                payload=MemoryHead(
                    family_id=snapshot.family_id,
                    memory_scope=snapshot.memory_scope,
                    memory_branch=snapshot.memory_branch,
                    revision_id=snapshot.revision_id,
                    sequence=sequence,
                ).model_dump_json(),
            )
        for family in manifest.previous_family_snapshots:
            await tx.run(
                "MATCH (f:MemoryFamily {family_id: $family_id}) "
                "SET f.payload_json = $payload, f.state = $state, "
                "f.merged_into_family_id = $merged_into_family_id",
                family_id=str(family.family_id),
                payload=family.model_dump_json(),
                state=family.state.value,
                merged_into_family_id=(
                    str(family.merged_into_family_id) if family.merged_into_family_id else None
                ),
            )
        unmerge_at = utc_now()
        merge_revision_result = await tx.run(
            "MATCH (r:MemoryRevision {revision_id: $revision_id}) RETURN r.payload_json AS payload",
            revision_id=str(manifest.merge_revision_id),
        )
        merge_revision_row = await merge_revision_result.single()
        if merge_revision_row is None:
            raise LedgerConflictError("A revisão do merge não existe")
        merge_revision = MemoryRevision.model_validate_json(merge_revision_row["payload"])
        if merge_revision.recorded_to is None or merge_revision.recorded_to > unmerge_at:
            await tx.run(
                "MATCH (r:MemoryRevision {revision_id: $revision_id}) SET r.payload_json = $payload",
                revision_id=str(merge_revision.revision_id),
                payload=merge_revision.model_copy(update={"recorded_to": unmerge_at}).model_dump_json(),
            )
        await tx.run(
            """
            CREATE (t:RevisionTransition {
                transition_id: $transition_id, family_id: $family_id,
                from_revision_id: $revision_id, to_revision_id: $revision_id,
                state: 'invalidated', reason: $reason, actor_id: $actor_id,
                actor_type: $actor_type, proposal_id: $proposal_id, created_at: $created_at
            })
            """,
            transition_id=str(self._deterministic_id("transition", proposal.proposal_id, "unmerge-merge-invalidated")),
            family_id=str(manifest.target_family_id),
            revision_id=str(manifest.merge_revision_id),
            reason="A revisão de merge foi invalidada pelo unmerge",
            actor_id=approval.principal_id,
            actor_type=approval.principal_type,
            proposal_id=str(proposal.proposal_id),
            created_at=unmerge_at.isoformat(),
        )
        for snapshot in manifest.previous_heads:
            revision_result = await tx.run(
                "MATCH (r:MemoryRevision {revision_id: $revision_id}) RETURN r.payload_json AS payload",
                revision_id=str(snapshot.revision_id),
            )
            revision_row = await revision_result.single()
            if revision_row is None:
                raise LedgerConflictError("Uma revisão histórica do manifesto não existe")
            restored_revision = MemoryRevision.model_validate_json(revision_row["payload"])
            family = current_families.get(snapshot.family_id)
            if family is None:
                raise LedgerConflictError("Uma família do manifesto não existe")
            legacy_id = family.legacy_memory_id or legacy_memory_id_for_family(snapshot.family_id)
            restored_state = (
                RevisionState.INVALIDATED
                if restored_revision.content.valid_to and restored_revision.content.valid_to <= unmerge_at
                else RevisionState.ACTIVE
            )
            await self._upsert_legacy_projection(tx, restored_revision, legacy_id, restored_state)
            await tx.run(
                """
                CREATE (t:RevisionTransition {
                    transition_id: $transition_id, family_id: $family_id,
                    to_revision_id: $revision_id, state: $state,
                    reason: $reason, actor_id: $actor_id, actor_type: $actor_type,
                    proposal_id: $proposal_id, created_at: $created_at
                })
                """,
                transition_id=str(self._deterministic_id("transition", proposal.proposal_id, f"unmerge-active:{snapshot.family_id}")),
                family_id=str(snapshot.family_id),
                revision_id=str(snapshot.revision_id),
                state=restored_state.value,
                reason=proposal.reason,
                actor_id=approval.principal_id,
                actor_type=approval.principal_type,
                proposal_id=str(proposal.proposal_id),
                created_at=unmerge_at.isoformat(),
            )
        if alias_names:
            await tx.run("MATCH (a:MemoryAlias) WHERE a.alias IN $aliases DETACH DELETE a", aliases=list(alias_names))
            for alias in manifest.aliases_before:
                await tx.run(
                    "MERGE (a:MemoryAlias {alias: $alias, family_id: $family_id}) "
                    "SET a.payload_json = $payload, a.status = $status",
                    alias=alias.alias,
                    family_id=str(alias.family_id) if alias.family_id else "",
                    payload=alias.model_dump_json(),
                    status=alias.status.value,
                )
        for relation_id in manifest.created_relation_ids:
            relation = current_relations[relation_id].model_copy(update={"state": RelationState.RETIRED})
            await tx.run(
                "MATCH (a:RelationAssertion {assertion_id: $assertion_id}) "
                "SET a.payload_json = $payload, a.state = $state",
                assertion_id=str(relation_id),
                payload=relation.model_dump_json(),
                state=relation.state.value,
            )
        for relation in manifest.affected_relation_snapshots:
            await tx.run(
                "MERGE (a:RelationAssertion {assertion_id: $assertion_id}) "
                "SET a.payload_json = $payload, a.state = $state",
                assertion_id=str(relation.assertion_id),
                payload=relation.model_dump_json(),
                state=relation.state.value,
            )

        restored_revision = await tx.run(
            "MATCH (r:MemoryRevision {revision_id: $revision_id}) RETURN r.payload_json AS payload",
            revision_id=str(target_snapshot.revision_id),
        )
        restored_row = await restored_revision.single()
        if restored_row is None:
            raise LedgerConflictError("A revisão restaurada não existe")
        for family_id in affected_family_ids:
            event = OutboxEvent(
                event_id=self._deterministic_id("outbox", proposal.proposal_id, f"unmerge:{family_id}"),
                event_type="memory.head.changed",
                family_id=family_id,
                revision_id=next(
                    (item.revision_id for item in manifest.previous_heads if item.family_id == family_id),
                    None,
                ),
                content_hash="sha256:unmerge:" + str(family_id),
                sequence=sequence,
                payload=(("operation", "unmerge"), ("manifest_id", str(manifest.manifest_id))),
            )
            await self._create_outbox(tx, event)
        await tx.run(
            "MATCH (p:ChangeProposal {proposal_id: $proposal_id}) "
            "SET p.payload_json = $proposal_payload, p.status = 'applied' "
            "MATCH (a:ApprovalDecision {approval_id: $approval_id}) "
            "SET a.payload_json = $approval_payload, a.status = 'consumed'",
            proposal_id=str(proposal.proposal_id),
            proposal_payload=proposal.model_copy(
                update={"status": ProposalStatus.APPLIED, "applied_revision_id": target_snapshot.revision_id}
            ).model_dump_json(),
            approval_id=str(approval.approval_id),
            approval_payload=approval.model_copy(
                update={"status": ApprovalStatus.CONSUMED, "consumed_at": utc_now()}
            ).model_dump_json(),
        )
        return restored_row["payload"]

    async def _next_sequence(self, tx) -> int:  # noqa: ANN001
        result = await tx.run(
            "MERGE (s:LedgerSequence {id: 'memory'}) SET s.value = coalesce(s.value, 0) + 1 RETURN s.value AS value"
        )
        row = await result.single()
        return int(row["value"] if row else 1)

    async def apply_approved(self, proposal_id: uuid.UUID, approval_id: uuid.UUID):
        await self._ensure_schema()
        proposal = await self.get_proposal(proposal_id)
        approval = await self.get_approval(approval_id)
        if approval is None or approval.proposal_id != proposal_id:
            raise ApprovalError("Aprovação inválida para a proposta")
        if approval.status is ApprovalStatus.CONSUMED:
            if proposal.status is ProposalStatus.APPLIED:
                if proposal.applied_revision_id:
                    return await self.get_revision(proposal.applied_revision_id)
                relation = await self._get_relation_by_proposal(proposal_id)
                if relation is not None:
                    return relation
                raise ApprovalError("A aprovação consumida não possui resultado registrado")
            raise ApprovalError("Aprovação já consumida")
        if proposal.status is not ProposalStatus.APPROVED:
            raise ApprovalError("A proposta ainda não foi aprovada")
        if approval.preview_hash != proposal.preview_hash:
            raise ApprovalError("O preview mudou desde a aprovação")
        if proposal.expires_at and proposal.expires_at <= utc_now():
            raise ApprovalError("A proposta expirou")

        async with self.graph.driver.session() as session:
            try:
                payload = await session.execute_write(
                    self._apply_unmerge_transaction if proposal.operation.value == "unmerge" else self._apply_transaction,
                    proposal,
                    approval,
                )
            except LedgerConflictError:
                stale = proposal.model_copy(update={"status": ProposalStatus.STALE})
                await self._update_proposal(stale)
                raise
        if proposal.operation.value == "link":
            return RelationAssertion.model_validate_json(payload)
        return MemoryRevision.model_validate_json(payload)

    async def _get_relation_by_proposal(self, proposal_id: uuid.UUID) -> RelationAssertion | None:
        rows = await self.graph.execute_read(
            "MATCH (a:RelationAssertion) WHERE a.payload_json CONTAINS $proposal_id RETURN a.payload_json AS payload",
            proposal_id=str(proposal_id),
        )
        return RelationAssertion.model_validate_json(rows[0]["payload"]) if rows else None

    async def _update_proposal(self, proposal: ChangeProposal) -> None:
        async with self.graph.driver.session() as session:
            await session.run(
                "MATCH (p:ChangeProposal {proposal_id: $id}) SET p.payload_json = $payload, p.status = $status",
                id=str(proposal.proposal_id),
                payload=proposal.model_dump_json(),
                status=proposal.status.value,
            )

    async def get_view(self, revision_id: uuid.UUID) -> MemoryRevisionView:
        revision = await self.get_revision(revision_id)
        if revision is None:
            raise MemoryServiceError("Revisão não encontrada", context={"revision_id": str(revision_id)})
        heads = await self.graph.execute_read(
            "MATCH (h:MemoryHead {revision_id: $revision_id}) RETURN h.payload_json AS payload",
            revision_id=str(revision_id),
        )
        transitions = await self.graph.execute_read(
            """
            MATCH (t:RevisionTransition)
            WHERE t.from_revision_id = $revision_id OR t.to_revision_id = $revision_id
            RETURN t.transition_id AS transition_id, t.to_revision_id AS to_revision_id,
                   t.state AS state, t.reason AS reason
            ORDER BY t.created_at ASC
            """,
            revision_id=str(revision_id),
        )
        state = RevisionState.ACTIVE if heads else RevisionState.SUPERSEDED
        invalidation_reason = ""
        for transition in reversed(transitions):
            if transition.get("to_revision_id") == str(revision_id) and transition.get("state") in {
                RevisionState.INVALIDATED.value,
                RevisionState.ARCHIVED.value,
                RevisionState.CONFLICTED.value,
            }:
                state = RevisionState(transition["state"])
                invalidation_reason = str(transition.get("reason", ""))
                break
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
            is_current_head=bool(heads),
            invalidation_reason=invalidation_reason,
            transition_ids=tuple(uuid.UUID(str(row["transition_id"])) for row in transitions),
        )

    async def add_alias(self, alias: MemoryAlias) -> MemoryAlias:
        await self._ensure_schema()
        async with self.graph.driver.session() as session:
            await session.run(
                """
                MERGE (a:MemoryAlias {alias: $alias, family_id: $family_id})
                SET a.payload_json = $payload, a.status = $status
                """,
                alias=alias.alias,
                family_id=str(alias.family_id) if alias.family_id else "",
                payload=alias.model_dump_json(),
                status=alias.status.value,
            )
        return alias

    async def import_legacy(self, record) -> None:  # noqa: ANN001
        """Importa um registro legado em uma transação administrativa idempotente."""

        await self._ensure_schema()
        async with self.graph.driver.session() as session:
            await session.execute_write(self._import_legacy_transaction, record)

    async def _import_legacy_transaction(self, tx, record) -> None:  # noqa: ANN001
        family = record.family
        revision = record.revision
        evidence = record.evidence
        alias = record.alias
        state = RevisionState.ACTIVE if record.legacy_status == "active" else RevisionState.ARCHIVED
        existing_revision_result = await tx.run(
            "MATCH (r:MemoryRevision {revision_id: $revision_id}) "
            "RETURN r.content_hash AS content_hash, r.payload_json AS payload",
            revision_id=str(revision.revision_id),
        )
        existing_revision = await existing_revision_result.single()
        if existing_revision is not None and existing_revision["content_hash"] != revision.content_hash:
            raise LedgerConflictError("revision_id legado já existe com outro conteúdo")
        existing_evidence_result = await tx.run(
            "MATCH (e:Evidence {evidence_id: $evidence_id}) RETURN e.payload_json AS payload",
            evidence_id=str(evidence.evidence_id),
        )
        existing_evidence = await existing_evidence_result.single()
        if existing_evidence is not None:
            stored_evidence = Evidence.model_validate_json(existing_evidence["payload"])
            if stored_evidence.fingerprint != evidence.fingerprint:
                raise LedgerConflictError("evidence_id legado já existe com outro conteúdo")
        await tx.run(
            """
            MERGE (f:MemoryFamily {family_id: $family_id})
            ON CREATE SET f.project = $project, f.category = $category,
                          f.memory_scope = $scope, f.legacy_memory_id = $legacy_memory_id,
                          f.payload_json = $family_payload
            """,
            family_id=str(family.family_id),
            project=family.project,
            category=family.category,
            scope=family.memory_scope.value,
            legacy_memory_id=record.legacy_memory_id,
            family_payload=family.model_dump_json(),
        )
        await tx.run(
            """
            MERGE (e:Evidence {evidence_id: $evidence_id})
            ON CREATE SET e.payload_json = $payload
            MERGE (r:MemoryRevision {revision_id: $revision_id})
            ON CREATE SET r.family_id = $family_id, r.version = $version,
                          r.content_hash = $content_hash, r.payload_json = $revision_payload,
                          r.state = $state
            WITH e, r
            MATCH (f:MemoryFamily {family_id: $family_id})
            MERGE (r)-[:REVISION_OF]->(f)
            MERGE (r)-[:SUPPORTED_BY {stance: 'context', confidence: 0.0}]->(e)
            """,
            evidence_id=str(evidence.evidence_id),
            payload=evidence.model_dump_json(),
            revision_id=str(revision.revision_id),
            family_id=str(family.family_id),
            version=revision.version,
            content_hash=revision.content_hash,
            revision_payload=revision.model_dump_json(),
            state=state.value,
        )
        await tx.run(
            """
            MERGE (h:MemoryHead {head_key: $head_key})
            SET h.family_id = $family_id, h.memory_scope = $scope,
                h.memory_branch = $branch, h.revision_id = $revision_id,
                h.sequence = coalesce(h.sequence, 0), h.payload_json = $head_payload
            """,
            head_key=self._head_key(
                family.family_id, revision.content.memory_scope, revision.content.memory_branch
            ),
            family_id=str(family.family_id),
            scope=revision.content.memory_scope.value,
            branch=revision.content.memory_branch,
            revision_id=str(revision.revision_id),
            head_payload=MemoryHead(
                family_id=family.family_id,
                memory_scope=revision.content.memory_scope,
                memory_branch=revision.content.memory_branch,
                revision_id=revision.revision_id,
                sequence=1,
            ).model_dump_json(),
        )
        await tx.run(
            """
            MERGE (t:RevisionTransition {transition_id: $transition_id})
            SET t.family_id = $family_id, t.to_revision_id = $revision_id,
                t.state = $state, t.reason = $reason, t.actor_id = 'legacy_import',
                t.actor_type = 'migration', t.created_at = $created_at
            """,
            transition_id=str(uuid.uuid5(revision.revision_id, "legacy_import_transition")),
            family_id=str(family.family_id),
            revision_id=str(revision.revision_id),
            state=state.value,
            reason="Estado importado sem inferir validade histórica",
            created_at=utc_now().isoformat(),
        )
        await tx.run(
            """
            MERGE (a:MemoryAlias {alias: $alias, family_id: $family_id})
            SET a.payload_json = $payload, a.status = $status
            """,
            alias=alias.alias,
            family_id=str(alias.family_id) if alias.family_id else "",
            payload=alias.model_dump_json(),
            status=alias.status.value,
        )
        event = OutboxEvent(
            event_id=uuid.uuid5(revision.revision_id, "legacy_import_outbox"),
            event_type="memory.head.changed",
            family_id=family.family_id,
            revision_id=revision.revision_id,
            content_hash=revision.content_hash,
            sequence=1,
            payload=(
                ("operation", "legacy_import"),
                ("state", state.value),
                ("scope", revision.content.memory_scope.value),
                ("branch", revision.content.memory_branch),
            ),
        )
        await self._create_outbox(tx, event)
        await self._upsert_legacy_projection(tx, revision, record.legacy_memory_id, state)
        if alias.status is MemoryAliasStatus.AMBIGUOUS:
            await tx.run(
                """
                MERGE (a:MemoryAlias {alias: $alias, family_id: ''})
                SET a.payload_json = $payload, a.status = 'ambiguous'
                WITH a
                MATCH (old:MemoryAlias {alias: $alias, family_id: $family_id})
                DETACH DELETE old
                """,
                alias=alias.alias,
                family_id=str(family.family_id),
                payload=alias.model_dump_json(),
            )

    async def resolve_alias(self, alias: str) -> MemoryAlias | None:
        rows = await self.graph.execute_read(
            "MATCH (a:MemoryAlias {alias: $alias}) RETURN a.payload_json AS payload",
            alias=alias,
        )
        if not rows:
            return None
        aliases = [
            MemoryAlias.model_validate_json(row["payload"])
            for row in rows
            if MemoryAlias.model_validate_json(row["payload"]).status is not MemoryAliasStatus.RETIRED
        ]
        if not aliases:
            return None
        if any(item.status is MemoryAliasStatus.AMBIGUOUS for item in aliases):
            candidates = tuple(
                dict.fromkeys(
                    family_id
                    for item in aliases
                    for family_id in (item.candidates or ((item.family_id,) if item.family_id else ()))
                )
            )
            return MemoryAlias(
                alias=alias,
                status=MemoryAliasStatus.AMBIGUOUS,
                candidates=candidates,
            )
        families = {item.family_id for item in aliases if item.family_id}
        if len(families) == 1:
            return next(item for item in aliases if item.family_id)
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
        revisions = await self.list_revisions(project=project, category=category)
        transition_rows = await self.graph.execute_read(
            "MATCH (t:RevisionTransition) "
            "RETURN t.to_revision_id AS to_revision_id, t.state AS state, "
            "t.created_at AS created_at"
        )
        invalidated_at_recorded = {
            str(row["to_revision_id"])
            for row in transition_rows
            if row.get("to_revision_id")
            and row.get("state") in {
                RevisionState.INVALIDATED.value,
                RevisionState.ARCHIVED.value,
                RevisionState.CONFLICTED.value,
            }
            and (
                not row.get("created_at")
                or datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00")) <= recorded_at
            )
        }
        reactivated_at: dict[str, datetime] = {}
        for row in transition_rows:
            if row.get("to_revision_id") and row.get("state") == RevisionState.ACTIVE.value:
                created_at = row.get("created_at")
                if created_at:
                    created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                    previous = reactivated_at.get(str(row["to_revision_id"]))
                    if previous is None or created > previous:
                        reactivated_at[str(row["to_revision_id"])] = created
        grouped: dict[tuple[uuid.UUID, str, str], list[MemoryRevision]] = {}
        for revision in revisions:
            content = revision.content
            if memory_scope is not None and str(content.memory_scope) != str(memory_scope):
                continue
            if memory_branch is not None and content.memory_branch != memory_branch:
                continue
            if revision.recorded_from > recorded_at:
                continue
            if revision.recorded_to is not None and recorded_at >= revision.recorded_to:
                restored_at = reactivated_at.get(str(revision.revision_id))
                if (
                    restored_at is None
                    or restored_at < revision.recorded_to
                    or restored_at > recorded_at
                ):
                    continue
            if content.valid_from is not None and content.valid_from > valid_at:
                continue
            if str(revision.revision_id) in invalidated_at_recorded:
                continue
            grouped.setdefault((revision.family_id, str(content.memory_scope), content.memory_branch), []).append(revision)
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
        rows = await self.graph.execute_read(
            "MATCH (r:MemoryRevision) RETURN r.payload_json AS payload"
        )
        revisions = [MemoryRevision.model_validate_json(row["payload"]) for row in rows]
        return sorted(
            [
                revision
                for revision in revisions
                if (project is None or revision.content.project == project)
                and (category is None or revision.content.category == category)
            ],
            key=lambda item: (item.created_at, str(item.revision_id)),
        )

    async def list_outbox(
        self,
        status: OutboxStatus | None = OutboxStatus.PENDING,
        *,
        now: datetime | None = None,
    ) -> list[OutboxEvent]:
        query = "MATCH (o:OutboxEvent) "
        params = {}
        if status is not None:
            query += "WHERE o.status = $status "
            params["status"] = status.value
        query += "RETURN o.payload_json AS payload, o.status AS node_status, " \
                 "o.available_at AS available_at, o.lease_until AS lease_until, " \
                 "o.claimed_by AS claimed_by, o.claim_token AS claim_token, " \
                 "o.attempts AS attempts, o.last_error AS last_error " \
                 "ORDER BY o.sequence ASC, o.created_at ASC"
        rows = await self.graph.execute_read(query, **params)
        now = now or utc_now()
        events = []
        for row in rows:
            event = OutboxEvent.model_validate_json(row["payload"])
            updates = {
                "status": row.get("node_status") or event.status,
                "available_at": row.get("available_at") or event.available_at,
                "lease_until": row.get("lease_until") or event.lease_until,
                "claimed_by": row.get("claimed_by") or event.claimed_by,
                "claim_token": row.get("claim_token") or event.claim_token,
                "attempts": row.get("attempts") if row.get("attempts") is not None else event.attempts,
                "last_error": row.get("last_error") if row.get("last_error") is not None else event.last_error,
            }
            events.append(event.model_copy(update=updates))
        return [
            event
            for event in events
            if event.available_at <= now
            and (event.lease_until is None or event.lease_until <= now or event.status is not OutboxStatus.PROCESSING)
        ]

    async def mark_outbox(
        self,
        event_id: uuid.UUID,
        status: OutboxStatus,
        error: str = "",
        *,
        worker_id: str | None = None,
        claim_token: str | None = None,
    ) -> None:
        rows = await self.graph.execute_read(
            "MATCH (o:OutboxEvent {event_id: $event_id}) "
            "RETURN o.payload_json AS payload, o.status AS node_status, "
            "o.available_at AS available_at, o.lease_until AS lease_until, "
            "o.claimed_by AS claimed_by, o.claim_token AS claim_token, "
            "o.attempts AS attempts, o.last_error AS last_error",
            event_id=str(event_id),
        )
        if not rows:
            raise MemoryServiceError("Evento outbox não encontrado")
        if status is OutboxStatus.PROCESSING:
            raise LedgerConflictError("PROCESSING só pode ser definido por claim_outbox")
        row = rows[0]
        event = OutboxEvent.model_validate_json(row["payload"]).model_copy(
            update={
                "status": row.get("node_status") or OutboxStatus.PENDING,
                "available_at": row.get("available_at") or utc_now(),
                "lease_until": row.get("lease_until"),
                "claimed_by": row.get("claimed_by"),
                "claim_token": row.get("claim_token"),
                "attempts": row.get("attempts") if row.get("attempts") is not None else 0,
            }
        )
        if status is not OutboxStatus.PROCESSING:
            if (
                event.status is not OutboxStatus.PROCESSING
                or not worker_id
                or not claim_token
                or event.claimed_by != worker_id
                or event.claim_token != claim_token
                or event.lease_until is None
                or event.lease_until <= utc_now()
            ):
                raise LedgerConflictError("Lease do outbox ausente, incorreto ou expirado")
        attempts = event.attempts + 1
        next_status = OutboxStatus.DEAD_LETTER if status is OutboxStatus.FAILED and attempts >= 5 else status
        updated = event.model_copy(
            update={
                "status": next_status,
                "attempts": attempts,
                "last_error": error,
                "lease_until": None,
                "claimed_by": None,
                "claim_token": None,
            }
        )
        async with self.graph.driver.session() as session:
            result = await session.run(
                "MATCH (o:OutboxEvent {event_id: $event_id}) "
                "WHERE o.status = 'processing' AND o.claimed_by = $worker_id "
                "AND o.claim_token = $claim_token "
                "AND o.lease_until = $lease_until "
                "SET o.payload_json = $payload, o.status = $status, "
                "o.attempts = $attempts, o.last_error = $last_error, "
                "o.lease_until = NULL, o.claimed_by = NULL, o.claim_token = NULL "
                "RETURN o.event_id AS event_id",
                event_id=str(event_id),
                payload=updated.model_dump_json(),
                status=next_status.value,
                attempts=attempts,
                last_error=error,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_until=event.lease_until.isoformat() if event.lease_until else None,
            )
            if await result.single() is None:
                raise LedgerConflictError("O lease do outbox mudou antes da confirmação")

    async def claim_outbox(
        self,
        event_id: uuid.UUID,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> OutboxEvent | None:
        await self._ensure_schema()
        now = utc_now()
        lease_until = now + timedelta(seconds=lease_seconds)
        claim_token = uuid.uuid4().hex
        async with self.graph.driver.session() as session:
            result = await session.execute_write(
                self._claim_outbox_transaction,
                event_id,
                worker_id,
                lease_until,
                claim_token,
            )
        if not result:
            return None
        return OutboxEvent.model_validate_json(result["payload"]).model_copy(
            update={
                "status": OutboxStatus.PROCESSING,
                "lease_until": lease_until,
                "claimed_by": worker_id,
                "claim_token": claim_token,
            }
        )

    async def _claim_outbox_transaction(self, tx, event_id, worker_id, lease_until, claim_token):  # noqa: ANN001
        result = await tx.run(
            """
            MATCH (o:OutboxEvent {event_id: $event_id})
            WHERE o.status IN ['pending', 'failed', 'processing']
              AND (o.available_at IS NULL OR o.available_at <= $now)
              AND (o.lease_until IS NULL OR o.lease_until <= $now OR o.status <> 'processing')
            SET o.status = 'processing', o.lease_until = $lease_until,
                o.claimed_by = $worker_id, o.claim_token = $claim_token
            RETURN o.payload_json AS payload
            """,
            event_id=str(event_id),
            worker_id=worker_id,
            now=utc_now().isoformat(),
            lease_until=lease_until.isoformat(),
            claim_token=claim_token,
        )
        row = await result.single()
        return row if row else None

    async def list_relations(self, state: RelationState = RelationState.ACTIVE) -> list[RelationAssertion]:
        rows = await self.graph.execute_read(
            "MATCH (a:RelationAssertion {state: $state}) RETURN a.payload_json AS payload",
            state=state.value,
        )
        return [RelationAssertion.model_validate_json(row["payload"]) for row in rows]

    async def record_usage_observation(self, observation: UsageObservation) -> UsageObservation:
        await self._ensure_schema()
        revision = await self.get_revision(observation.procedure_revision_id)
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
        rows = await self.graph.execute_read(
            "MATCH (o:UsageObservation {idempotency_key: $key}) RETURN o.payload_json AS payload",
            key=observation.idempotency_key,
        )
        if rows:
            existing = UsageObservation.model_validate_json(rows[0]["payload"])
            if existing.payload_hash != observation.payload_hash:
                raise LedgerConflictError("idempotency_key já foi usada com outro uso procedural")
            return existing
        async with self.graph.driver.session() as session:
            result = await session.run(
                """
                MERGE (o:UsageObservation {idempotency_key: $idempotency_key})
                ON CREATE SET o.observation_id = $observation_id,
                              o.procedure_family_id = $procedure_family_id,
                              o.procedure_revision_id = $procedure_revision_id,
                              o.payload_json = $payload
                RETURN o.payload_json AS payload
                """,
                observation_id=str(observation.observation_id),
                idempotency_key=observation.idempotency_key,
                procedure_family_id=str(observation.procedure_family_id),
                procedure_revision_id=str(observation.procedure_revision_id),
                payload=observation.model_dump_json(),
            )
            row = await result.single()
        if row is None:
            raise MemoryServiceError("Falha ao persistir observação de uso")
        stored = UsageObservation.model_validate_json(row["payload"])
        if stored.payload_hash != observation.payload_hash:
            raise LedgerConflictError("idempotency_key já foi usada com outro uso procedural")
        return stored

    async def list_usage_observations(
        self, procedure_family_id: uuid.UUID | None = None
    ) -> list[UsageObservation]:
        if procedure_family_id is None:
            rows = await self.graph.execute_read(
                "MATCH (o:UsageObservation) RETURN o.payload_json AS payload"
            )
        else:
            rows = await self.graph.execute_read(
                "MATCH (o:UsageObservation {procedure_family_id: $family_id}) "
                "RETURN o.payload_json AS payload",
                family_id=str(procedure_family_id),
            )
        observations = [UsageObservation.model_validate_json(row["payload"]) for row in rows]
        return sorted(observations, key=lambda item: (item.observed_at, str(item.observation_id)))
