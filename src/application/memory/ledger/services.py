from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from decisionssearch.application.memory.admission_gates import AdmissionResult
from decisionssearch.domain.memory.memory_candidate import MemoryCandidate
from decisionssearch.domain.memory.memory_item import MemoryItem
from decisionssearch.domain.memory_ledger import (
    ApprovalDecision,
    ChangeProposal,
    ConflictCase,
    ConflictDetectionCoverage,
    ConflictMember,
    ConflictResolution,
    Evidence,
    EvidenceLinkSpec,
    EvidenceVerification,
    FieldDiff,
    FieldOrigin,
    LedgerOperation,
    MemoryContent,
    MemoryScope,
    ProposalStatus,
    RevisionState,
    canonical_json,
    content_hash,
)
from decisionssearch.domain.shared.exceptions import ApprovalError, LedgerConflictError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def content_from_candidate(
    candidate: MemoryCandidate,
    *,
    memory_branch: str = "semantic",
    git_ref: str = "",
) -> MemoryContent:
    legacy_memory_id = MemoryItem.generate_id(candidate.project, candidate.type, candidate.title)
    return MemoryContent(
        project=candidate.project,
        category=candidate.type,
        title=candidate.title,
        summary=candidate.summary,
        details=candidate.details,
        objective=candidate.objective,
        trigger=candidate.trigger,
        domain=tuple(candidate.domain),
        modules=tuple(candidate.modules),
        stakeholders=tuple(candidate.stakeholders),
        action_triggers=tuple(candidate.action_triggers),
        related_files=tuple(candidate.related_files),
        business_rules=tuple(candidate.business_rules),
        architectural_rationale=candidate.architectural_rationale,
        examples=tuple(candidate.examples),
        alternatives_considered=tuple(candidate.alternatives_considered),
        weight_manual=float(candidate.proposed_weight),
        weight_confidence=float(candidate.confidence),
        significance={
            "FeatureDescription": 0.85,
            "ArchitecturalDecision": 0.9,
            "DesignRule": 0.8,
            "DesignPattern": 0.75,
            "BusinessRule": 0.6,
        }.get(candidate.type, 0.5),
        memory_scope=MemoryScope.SEMANTIC,
        memory_branch=memory_branch,
        git_ref=git_ref,
        valid_from=candidate.event_date,
        legacy_ids={"memory_id": legacy_memory_id},
    )


def evidence_from_candidate(candidate: MemoryCandidate) -> tuple[Evidence, ...]:
    evidence: list[Evidence] = []
    for item in candidate.evidence:
        evidence.append(
            Evidence(
                source_kind=item.type,
                source_locator=item.ref,
                verification=EvidenceVerification.UNVERIFIED,
                excerpt_or_hash=item.snippet,
                source_reliability=candidate.confidence,
            )
        )
    if not evidence and candidate.source_event_id:
        evidence.append(
            Evidence(
                source_kind="event",
                source_locator=candidate.source_event_id,
                verification=EvidenceVerification.UNVERIFIED,
                source_reliability=candidate.confidence,
            )
        )
    return tuple(evidence)


def _diff(before: MemoryContent | None, after: MemoryContent | None) -> tuple[FieldDiff, ...]:
    before_data = before.model_dump(mode="json") if before else {}
    after_data = after.model_dump(mode="json") if after else {}
    fields = sorted(set(before_data) | set(after_data))
    return tuple(
        FieldDiff(field=field, before=before_data.get(field), after=after_data.get(field))
        for field in fields
        if before_data.get(field) != after_data.get(field)
    )


def _preview_hash(data: dict) -> str:
    encoded = canonical_json(data).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _normal_value(value) -> str:  # noqa: ANN001
    return canonical_json(value)


def _claim_value(content: MemoryContent, claim_path: str):
    """Resolve um claim no snapshot final para validar a resolução escolhida."""

    current = content
    for part in claim_path.split("."):
        if isinstance(current, MemoryContent) and part == "structured_payload":
            current = current.structured_payload
            continue
        if isinstance(current, dict):
            if part not in current:
                raise LedgerConflictError(
                    "A resolução aponta para um claim ausente no snapshot final",
                    context={"claim_path": claim_path},
                )
            current = current[part]
            continue
        if not isinstance(current, MemoryContent) or not hasattr(current, part):
            raise LedgerConflictError(
                "A resolução aponta para um claim ausente no snapshot final",
                context={"claim_path": claim_path},
            )
        current = getattr(current, part)
    return current


def _normalize_existing_family_content(
    family,
    content: MemoryContent,
    *,
    current_content: MemoryContent | None = None,
) -> MemoryContent:  # noqa: ANN001
    """Preserva a identidade lógica ao criar uma nova revisão da família."""

    if family.project != content.project or family.category != content.category:
        raise LedgerConflictError(
            "Uma revisão não pode trocar projeto ou categoria da família",
            context={"family_id": str(family.family_id)},
        )
    if family.memory_scope is not content.memory_scope:
        raise LedgerConflictError(
            "Uma revisão não pode trocar o escopo da família",
            context={"family_id": str(family.family_id)},
        )
    if current_content is not None and current_content.memory_branch != content.memory_branch:
        raise LedgerConflictError(
            "Uma revisão não pode trocar o branch da família",
            context={"family_id": str(family.family_id)},
        )
    legacy_key = {
        MemoryScope.EPISODIC: "episode_id",
        MemoryScope.PROCEDURAL: "procedure_id",
    }.get(content.memory_scope, "memory_id")
    supplied = dict(content.legacy_ids).get(legacy_key)
    if supplied and family.legacy_memory_id and supplied != family.legacy_memory_id:
        raise LedgerConflictError(
            "A revisão tenta trocar o identificador legado da família",
            context={"family_id": str(family.family_id), "legacy_key": legacy_key},
        )
    return content.model_copy(
        update={"legacy_ids": {legacy_key: family.legacy_memory_id}}
    )


def _validate_field_origins(
    field_origins: tuple[FieldOrigin, ...],
    source_revisions: tuple,
    content: MemoryContent,
) -> None:
    """Garante que uma origem declarada não falsifique o snapshot final."""

    if not field_origins:
        return
    allowed_fields = set(LINEAGE_FIELDS)
    revisions_by_id = {revision.revision_id: revision for revision in source_revisions}
    for origin in field_origins:
        if origin.field not in allowed_fields:
            raise LedgerConflictError(
                "FieldOrigin aponta para um campo que não possui contrato de lineage",
                context={"field": origin.field},
            )
        source = revisions_by_id.get(origin.source_revision_id)
        if source is None:
            raise LedgerConflictError(
                "FieldOrigin aponta para uma revisão que não está no conjunto de fontes",
                context={"field": origin.field, "source_revision_id": str(origin.source_revision_id)},
            )
        source_value = _claim_value(source.content, origin.field)
        final_value = _claim_value(content, origin.field)
        if canonical_json(source_value) != canonical_json(final_value):
            raise LedgerConflictError(
                "FieldOrigin não corresponde ao valor do snapshot final",
                context={"field": origin.field, "source_revision_id": str(origin.source_revision_id)},
            )


def _claim_value_hash(value) -> str:  # noqa: ANN001
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


LINEAGE_FIELDS = (
    "title",
    "summary",
    "details",
    "objective",
    "trigger",
    "business_rules",
    "architectural_rationale",
    "domain",
    "modules",
    "stakeholders",
    "action_triggers",
    "related_files",
    "examples",
    "alternatives_considered",
    "structured_payload",
)


def _detect_merge_conflicts(
    revisions,
    *,
    field_origins: tuple[FieldOrigin, ...],
    content: MemoryContent,
) -> tuple[ConflictCase, ...]:
    """Detecta divergências somente nos claims não resolvidos pelo autor.

    O detector é deliberadamente conservador: um merge que fornece uma origem
    explícita para um campo já está declarando como aquele campo foi resolvido.
    Divergências sem origem, porém, bloqueiam a aprovação e ficam auditáveis.
    """

    origin_fields = {item.field for item in field_origins}
    fields = LINEAGE_FIELDS[:-1]
    conflicts: list[ConflictCase] = []
    for field in fields:
        if field in origin_fields:
            continue
        values: dict[str, list] = {}
        for revision in revisions:
            value = getattr(revision.content, field)
            normalized = _normal_value(value)
            if normalized:
                values.setdefault(normalized, []).append(revision)
        if len(values) < 2:
            continue
        # Um refinamento que apenas adiciona contexto não é contradição. Isso
        # evita bloquear consolidações como "Use cache" + "Use local cache",
        # mantendo divergências factuais distintas sob bloqueio. Negação é uma
        # exceção importante: "cache habilitado" e "cache não habilitado" não
        # podem ser tratados como simples subconjunto de tokens.
        if all(isinstance(getattr(row.content, field), str) for row in revisions):
            token_sets = [
                set(re.findall(r"[\wÀ-ÿ]+", str(getattr(row.content, field)).casefold()))
                for row in revisions
                if str(getattr(row.content, field)).strip()
            ]
            negations = {
                "não",
                "nao",
                "not",
                "never",
                "no",
                "without",
                "sem",
                "nunca",
                "don't",
                "doesn't",
            }
            if token_sets and all(
                (left <= right or right <= left)
                and not (negations & (left ^ right))
                for left in token_sets
                for right in token_sets
                if left != right
            ):
                continue
        members = tuple(
            ConflictMember(
                revision_id=revision.revision_id,
                family_id=revision.family_id,
                claim_path=field,
                normalized_value_hash="sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                evidence_ids=revision.evidence_ids,
            )
            for normalized, rows in values.items()
            for revision in rows
        )
        snapshot = canonical_json(
            {
                "field": field,
                "members": [member.model_dump(mode="json") for member in members],
            }
        )
        snapshot_hash = "sha256:" + hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        conflict_id = f"conflict:{content.memory_scope.value}:{content.memory_branch}:{field}:{snapshot_hash[7:23]}"
        conflicts.append(
            ConflictCase(
                conflict_id=conflict_id,
                claim_key=f"{content.project}:{content.category}:{field}",
                claim_path=field,
                memory_scope=content.memory_scope,
                memory_branch=content.memory_branch,
                coverage=ConflictDetectionCoverage.CONFLICT_FOUND,
                members=members,
                snapshot_hash=snapshot_hash,
            )
        )
    # Payloads estruturados são parte da afirmação, mas não podem ser
    # comparados por token. Divergência entre dois snapshots estruturados abre
    # um conflito explícito; um merge só pode prosseguir se o autor declarar a
    # origem/resolução desse payload.
    if "structured_payload" not in origin_fields:
        structured_values = [
            (revision, revision.content.structured_payload)
            for revision in revisions
            if revision.content.structured_payload is not None
        ]
        normalized_structured = {_normal_value(value) for _revision, value in structured_values}
        if len(normalized_structured) > 1:
            members = tuple(
                ConflictMember(
                    revision_id=revision.revision_id,
                    family_id=revision.family_id,
                    claim_path="structured_payload",
                    normalized_value_hash=_claim_value_hash(value),
                    evidence_ids=revision.evidence_ids,
                )
                for revision, value in structured_values
            )
            snapshot = canonical_json(
                {
                    "field": "structured_payload",
                    "members": [member.model_dump(mode="json") for member in members],
                }
            )
            snapshot_hash = "sha256:" + hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
            conflicts.append(
                ConflictCase(
                    conflict_id=f"conflict:{content.memory_scope.value}:{content.memory_branch}:structured_payload:{snapshot_hash[7:23]}",
                    claim_key=f"{content.project}:{content.category}:structured_payload",
                    claim_path="structured_payload",
                    memory_scope=content.memory_scope,
                    memory_branch=content.memory_branch,
                    coverage=ConflictDetectionCoverage.CONFLICT_FOUND,
                    detector_version="merge-detector.v2",
                    members=members,
                    snapshot_hash=snapshot_hash,
                )
            )
    return tuple(conflicts)


class ProposalService:
    """Gera previews server-side; nunca aplica uma alteração."""

    def __init__(self, ledger) -> None:  # noqa: ANN001
        self.ledger = ledger

    async def propose_create(
        self,
        content: MemoryContent,
        *,
        requested_by: str = "agent",
        evidence: Iterable[Evidence] = (),
        evidence_links: Iterable[EvidenceLinkSpec] = (),
        reason: str = "Nova memória semântica",
        idempotency_key: str = "",
    ) -> ChangeProposal:
        known_idempotency = False
        if idempotency_key:
            lookup = getattr(self.ledger, "get_proposal_by_idempotency", None)
            if lookup is not None:
                known_idempotency = await lookup(idempotency_key) is not None
        if not known_idempotency:
            for _alias_kind, legacy_id in content.legacy_ids:
                existing_alias = await self.ledger.resolve_alias(legacy_id)
                if existing_alias is not None and existing_alias.family_id is not None:
                    raise LedgerConflictError(
                        "O identificador legado já pertence a uma família; use update com CAS",
                        context={"legacy_id": legacy_id},
                    )
        return await self._build(
            operation=LedgerOperation.CREATE,
            content=content,
            before=(),
            target_family_id=None,
            base_revision_ids=(),
            expected_heads=(),
            source_revision_ids=(),
            requested_by=requested_by,
            evidence=tuple(evidence),
            evidence_links=tuple(evidence_links),
            reason=reason,
            idempotency_key=idempotency_key,
        )

    async def propose_candidate(
        self,
        candidate: MemoryCandidate,
        admission: AdmissionResult | dict,
        *,
        requested_by: str = "agent",
        reason: str = "Memória extraída pelo pipeline",
        idempotency_key: str = "",
    ) -> ChangeProposal:
        data = admission if isinstance(admission, dict) else vars(admission)
        action = str(data.get("action", "create"))
        content = content_from_candidate(candidate)
        if not idempotency_key:
            # Repetições exatas viram replay; uma alteração do mesmo título
            # colide no alias e precisa seguir como update explícito com CAS.
            idempotency_key = (
                f"candidate:{dict(content.legacy_ids)['memory_id']}:{content_hash(content)}"
            )
        evidence = evidence_from_candidate(candidate)
        if action == "refine":
            related_id = str(data.get("related_id") or "").strip()
            if not related_id:
                raise LedgerConflictError(
                    "Um refinamento precisa informar a memória existente relacionada"
                )
            alias = await self.ledger.resolve_alias(related_id)
            if alias is None or alias.family_id is None or alias.status.value != "resolved":
                raise LedgerConflictError(
                    "A memória relacionada não pode ser resolvida com segurança",
                    context={"related_id": related_id},
                )
            return await self.propose_create_and_link(
                content,
                target_family_id=alias.family_id,
                relation_type="REFINES",
                requested_by=requested_by,
                evidence=evidence,
                reason=reason,
                idempotency_key=idempotency_key,
            )
        if action == "update" and data.get("memory_id"):
            alias = await self.ledger.resolve_alias(str(data["memory_id"]))
            if alias and alias.family_id and alias.status.value == "resolved":
                return await self.propose_update(
                    alias.family_id,
                    content,
                    requested_by=requested_by,
                    evidence=evidence,
                    reason=reason,
                    idempotency_key=idempotency_key,
                )
        return await self.propose_create(
            content,
            requested_by=requested_by,
            evidence=evidence,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    async def propose_create_and_link(
        self,
        content: MemoryContent,
        *,
        target_family_id: uuid.UUID,
        relation_type: str = "REFINES",
        requested_by: str = "agent",
        evidence: Iterable[Evidence] = (),
        evidence_links: Iterable[EvidenceLinkSpec] = (),
        reason: str = "Memória nova relacionada a uma memória existente",
        idempotency_key: str = "",
    ) -> ChangeProposal:
        """Propõe a criação de uma família e sua relação no mesmo commit.

        O alvo é congelado pelo head atual no preview. Assim, um refinamento não
        pode virar um ``CREATE`` silencioso nem apontar para uma revisão que
        mudou enquanto aguardava aprovação.
        """

        relation_type = relation_type.strip().upper()
        if relation_type != "REFINES":
            raise LedgerConflictError(
                "CREATE_AND_LINK só é permitido para refinamentos de admissão"
            )
        target_family = await self.ledger.get_family(target_family_id)
        if target_family is None:
            raise LedgerConflictError("Família alvo do refinamento não existe")
        if target_family.project != content.project or target_family.category != content.category:
            raise LedgerConflictError(
                "O refinamento precisa permanecer no mesmo projeto e categoria"
            )
        if target_family.memory_scope != content.memory_scope:
            raise LedgerConflictError("O refinamento precisa permanecer no mesmo escopo")
        target_head = await self.ledger.get_head(
            target_family_id,
            target_family.memory_scope,
            content.memory_branch,
        )
        if target_head is None:
            raise LedgerConflictError("A família alvo do refinamento não possui head")
        target_revision = await self.ledger.get_revision(target_head.revision_id)
        if target_revision is None:
            raise LedgerConflictError("O head alvo aponta para uma revisão inexistente")
        target_view = await self.ledger.get_view(target_revision.revision_id)
        if target_view.state is not RevisionState.ACTIVE:
            raise LedgerConflictError("A memória alvo do refinamento não está ativa")
        if not idempotency_key:
            idempotency_key = (
                f"create-and-link:{relation_type}:{target_family_id}:{content_hash(content)}"
            )
        return await self._build(
            operation=LedgerOperation.CREATE_AND_LINK,
            content=content,
            before=(),
            target_family_id=None,
            base_revision_ids=(),
            expected_heads=(
                (
                    target_family_id,
                    str(target_head.memory_scope),
                    target_head.memory_branch,
                    target_head.revision_id,
                ),
            ),
            source_revision_ids=(),
            requested_by=requested_by,
            evidence=tuple(evidence),
            evidence_links=tuple(evidence_links),
            reason=reason,
            relation_type=relation_type,
            relation_target_family_id=target_family_id,
            idempotency_key=idempotency_key,
            target_branch=content.memory_branch,
        )

    async def propose_update(
        self,
        family_id: uuid.UUID,
        content: MemoryContent,
        *,
        requested_by: str = "agent",
        evidence: Iterable[Evidence] = (),
        evidence_links: Iterable[EvidenceLinkSpec] = (),
        reason: str = "Atualização de memória",
        idempotency_key: str = "",
    ) -> ChangeProposal:
        family = await self.ledger.get_family(family_id)
        if family is None:
            raise LedgerConflictError("Família não encontrada")
        head = await self.ledger.get_head(family_id, content.memory_scope, content.memory_branch)
        if head is None:
            raise LedgerConflictError("A família não possui head no escopo informado")
        revision = await self.ledger.get_revision(head.revision_id)
        if revision is None:
            raise LedgerConflictError("Head aponta para revisão inexistente")
        view = await self.ledger.get_view(revision.revision_id)
        if view.state is not RevisionState.ACTIVE:
            raise LedgerConflictError("A família não possui uma revisão ativa para atualizar")
        content = _normalize_existing_family_content(
            family,
            content,
            current_content=revision.content,
        )
        expected = ((family_id, str(content.memory_scope), content.memory_branch, revision.revision_id),)
        return await self._build(
            operation=LedgerOperation.UPDATE,
            content=content,
            before=(revision.content,),
            target_family_id=family_id,
            base_revision_ids=(revision.revision_id,),
            expected_heads=expected,
            source_revision_ids=(revision.revision_id,),
            requested_by=requested_by,
            evidence=tuple(evidence),
            evidence_links=tuple(evidence_links),
            reason=reason,
            idempotency_key=idempotency_key,
        )

    async def propose_merge(
        self,
        target_family_id: uuid.UUID,
        content: MemoryContent,
        expected_heads: tuple[tuple[uuid.UUID, str, str, uuid.UUID], ...],
        source_revision_ids: tuple[uuid.UUID, ...],
        *,
        requested_by: str = "agent",
        evidence: Iterable[Evidence] = (),
        evidence_links: Iterable[EvidenceLinkSpec] = (),
        field_origins: Iterable[FieldOrigin] = (),
        reason: str = "Consolidação de memórias relacionadas",
        idempotency_key: str = "",
    ) -> ChangeProposal:
        if len(source_revision_ids) < 2:
            raise LedgerConflictError("Uma fusão precisa de pelo menos duas revisões de origem")
        target_family = await self.ledger.get_family(target_family_id)
        if target_family is None:
            raise LedgerConflictError("A família alvo da fusão não existe")
        if (
            target_family.project != content.project
            or target_family.category != content.category
            or target_family.memory_scope != content.memory_scope
        ):
            raise LedgerConflictError(
                "Uma fusão não pode atravessar projeto, categoria ou escopo",
                context={"target_family_id": str(target_family_id)},
            )
        if len({item[0] for item in expected_heads}) < 2:
            raise LedgerConflictError("Uma fusão precisa comparar os heads de duas famílias")

        before = []
        source_families: set[uuid.UUID] = set()
        for revision_id in source_revision_ids:
            revision = await self.ledger.get_revision(revision_id)
            if revision is None:
                raise LedgerConflictError(
                    "A fusão aponta para uma revisão inexistente",
                    context={"revision_id": str(revision_id)},
                )
            before.append(revision.content)
            source_families.add(revision.family_id)
        if target_family_id not in source_families:
            raise LedgerConflictError("A família alvo precisa participar da fusão")
        expected_by_family = {item[0]: item for item in expected_heads}
        if set(expected_by_family) != source_families:
            raise LedgerConflictError("Os heads esperados precisam cobrir exatamente as famílias de origem")
        for revision in [await self.ledger.get_revision(item) for item in source_revision_ids]:
            if revision is None:
                raise LedgerConflictError("Uma revisão de origem da fusão não existe")
            expected = expected_by_family.get(revision.family_id)
            if (
                expected is None
                or expected[3] != revision.revision_id
                or str(expected[1]) != str(revision.content.memory_scope)
                or expected[2] != revision.content.memory_branch
            ):
                raise LedgerConflictError("A fusão só pode usar o head atual exato de cada família")
            if revision.content.memory_scope != content.memory_scope or revision.content.memory_branch != content.memory_branch:
                raise LedgerConflictError("As revisões fundidas precisam compartilhar escopo e branch")
            if revision.content.project != content.project or revision.content.category != content.category:
                raise LedgerConflictError("As revisões fundidas precisam compartilhar projeto e categoria")
        content = _normalize_existing_family_content(
            target_family,
            content,
            current_content=before[0] if before else None,
        )
        evidence_tuple = tuple(evidence)
        link_tuple = tuple(evidence_links)
        conflict_revisions = [
            revision
            for revision_id in source_revision_ids
            if (revision := await self.ledger.get_revision(revision_id)) is not None
        ]
        field_origins_tuple = tuple(field_origins)
        _validate_field_origins(field_origins_tuple, tuple(conflict_revisions), content)
        conflicts = _detect_merge_conflicts(
            conflict_revisions,
            field_origins=field_origins_tuple,
            content=content,
        )
        return await self._build(
            operation=LedgerOperation.MERGE,
            content=content,
            before=tuple(before),
            target_family_id=target_family_id,
            base_revision_ids=source_revision_ids,
            expected_heads=expected_heads,
            source_revision_ids=source_revision_ids,
            requested_by=requested_by,
            evidence=evidence_tuple,
            evidence_links=link_tuple,
            field_origins=field_origins_tuple,
            conflicts=conflicts,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    async def propose_rollback(
        self,
        target_family_id: uuid.UUID,
        restore_revision_id: uuid.UUID,
        expected_head: tuple[uuid.UUID, str, str, uuid.UUID],
        *,
        requested_by: str = "agent",
        reason: str = "Rollback aprovado de uma revisão anterior",
    ) -> ChangeProposal:
        current = await self.ledger.get_revision(expected_head[3])
        restored = await self.ledger.get_revision(restore_revision_id)
        if current is None or restored is None:
            raise LedgerConflictError("Rollback aponta para revisão inexistente")
        if current.family_id != target_family_id or restored.family_id != target_family_id:
            raise LedgerConflictError("Rollback não pode atravessar famílias")
        family = await self.ledger.get_family(target_family_id)
        if family is None:
            raise LedgerConflictError("Família do rollback não existe")
        restored_content = _normalize_existing_family_content(
            family,
            restored.content,
            current_content=current.content,
        )
        return await self._build(
            operation=LedgerOperation.ROLLBACK,
            content=restored_content,
            before=(current.content,),
            target_family_id=target_family_id,
            base_revision_ids=(current.revision_id,),
            expected_heads=(expected_head,),
            source_revision_ids=(restore_revision_id,),
            requested_by=requested_by,
            evidence=(),
            reason=reason,
            restore_revision_id=restore_revision_id,
        )

    async def propose_state_change(
        self,
        family_id: uuid.UUID,
        operation: LedgerOperation,
        *,
        requested_by: str = "agent",
        reason: str,
        idempotency_key: str = "",
        memory_branch: str | None = None,
        replacement_family_id: uuid.UUID | None = None,
        replacement_alias: str = "",
    ) -> ChangeProposal:
        if operation not in {
            LedgerOperation.INVALIDATE,
            LedgerOperation.SUPERSEDE,
            LedgerOperation.ARCHIVE,
        }:
            raise ValueError("Operação não representa mudança de estado")
        family = await self.ledger.get_family(family_id)
        if family is None:
            raise LedgerConflictError("Família não encontrada")
        get_current_head = getattr(self.ledger, "get_current_head", None)
        head = (
            await get_current_head(family_id, family.memory_scope, memory_branch)
            if get_current_head is not None
            else await self.ledger.get_head(
                family_id, family.memory_scope, memory_branch or "semantic"
            )
        )
        if head is None:
            raise LedgerConflictError("Família sem head para mudança de estado")
        revision = await self.ledger.get_revision(head.revision_id)
        if revision is None:
            raise LedgerConflictError("Head aponta para revisão inexistente")
        expected = [(family_id, str(head.memory_scope), head.memory_branch, revision.revision_id)]
        replacement_head = None
        if replacement_family_id is not None:
            if replacement_family_id == family_id:
                raise LedgerConflictError("Uma memória não pode substituir a si própria")
            replacement_family = await self.ledger.get_family(replacement_family_id)
            if replacement_family is None or replacement_family.state.value != "active":
                raise LedgerConflictError("A memória substituta não está ativa")
            if (
                replacement_family.project != family.project
                or replacement_family.memory_scope != family.memory_scope
            ):
                raise LedgerConflictError(
                    "A memória substituta precisa compartilhar projeto e escopo"
                )
            replacement_branch = (
                "pull_request"
                if replacement_family.memory_scope is MemoryScope.PULL_REQUEST
                else "episodic"
                if replacement_family.memory_scope is MemoryScope.EPISODIC
                else "procedural"
                if replacement_family.memory_scope is MemoryScope.PROCEDURAL
                else "semantic"
            )
            replacement_head = await self.ledger.get_head(
                replacement_family_id,
                replacement_family.memory_scope,
                replacement_branch,
            )
            if replacement_head is None:
                raise LedgerConflictError("A memória substituta não possui head")
            replacement_revision = await self.ledger.get_revision(replacement_head.revision_id)
            if replacement_revision is None:
                raise LedgerConflictError("O head da memória substituta é inválido")
            if (await self.ledger.get_view(replacement_revision.revision_id)).state is not RevisionState.ACTIVE:
                raise LedgerConflictError("A memória substituta não está ativa")
            expected.append(
                (
                    replacement_family_id,
                    str(replacement_head.memory_scope),
                    replacement_head.memory_branch,
                    replacement_head.revision_id,
                )
            )
        content = revision.content.model_copy(
            update={
                "valid_to": (
                    utc_now()
                    if operation
                    in {
                        LedgerOperation.INVALIDATE,
                        LedgerOperation.SUPERSEDE,
                        LedgerOperation.ARCHIVE,
                    }
                    else revision.content.valid_to
                )
            }
        )
        if replacement_family_id is not None and not idempotency_key:
            idempotency_key = (
                f"deprecate:{operation.value}:{family_id}:{replacement_family_id}"
            )
        return await self._build(
            operation=operation,
            content=content,
            before=(revision.content,),
            target_family_id=family_id,
            base_revision_ids=(revision.revision_id,),
            expected_heads=tuple(expected),
            source_revision_ids=(revision.revision_id,),
            requested_by=requested_by,
            evidence=(),
            reason=reason,
            idempotency_key=idempotency_key,
            replacement_family_id=replacement_family_id,
            replacement_alias=replacement_alias,
        )

    async def propose_unmerge(
        self,
        manifest_id: uuid.UUID,
        *,
        requested_by: str = "agent",
        reason: str = "Reversão explícita de uma fusão",
        idempotency_key: str = "",
    ) -> ChangeProposal:
        manifest = await self.ledger.get_merge_manifest(manifest_id)
        if manifest is None:
            raise LedgerConflictError("Manifesto de fusão não encontrado")
        target_snapshot = next(
            (item for item in manifest.previous_heads if item.family_id == manifest.target_family_id),
            None,
        )
        if target_snapshot is None:
            raise LedgerConflictError("Manifesto sem head da família alvo")
        current = await self.ledger.get_head(
            manifest.target_family_id,
            target_snapshot.memory_scope,
            target_snapshot.memory_branch,
        )
        if current is None or current.revision_id != manifest.merge_revision_id:
            raise LedgerConflictError("O head atual não corresponde ao merge que será desfeito")
        return await self._build(
            operation=LedgerOperation.UNMERGE,
            content=None,
            before=(),
            target_family_id=manifest.target_family_id,
            base_revision_ids=(manifest.merge_revision_id,),
            expected_heads=((manifest.target_family_id, str(current.memory_scope), current.memory_branch, current.revision_id),),
            source_revision_ids=tuple(
                snapshot.revision_id for snapshot in manifest.previous_heads
                if snapshot.family_id != manifest.target_family_id
            ),
            requested_by=requested_by,
            evidence=(),
            reason=reason,
            idempotency_key=idempotency_key,
            merge_manifest_id=manifest.manifest_id,
            expected_manifest_hash=manifest.manifest_hash,
        )

    async def propose_resolve_conflict(
        self,
        family_id: uuid.UUID,
        content: MemoryContent,
        resolutions: Iterable[ConflictResolution],
        *,
        requested_by: str = "agent",
        reason: str = "Resolução explícita de conflito",
        idempotency_key: str = "",
    ) -> ChangeProposal:
        head = await self.ledger.get_head(family_id, content.memory_scope, content.memory_branch)
        if head is None:
            raise LedgerConflictError("A família não possui head no escopo informado")
        current = await self.ledger.get_revision(head.revision_id)
        if current is None:
            raise LedgerConflictError("Head aponta para revisão inexistente")
        resolutions_tuple = tuple(
            item if isinstance(item, ConflictResolution) else ConflictResolution.model_validate(item)
            for item in resolutions
        )
        for resolution in resolutions_tuple:
            conflict = await self.ledger.get_conflict_case(resolution.conflict_id)
            if conflict is None or conflict.version != resolution.expected_conflict_version:
                raise LedgerConflictError("A versão do conflito não corresponde ao preview")
            if resolution.claim_path != conflict.claim_path:
                raise LedgerConflictError("A resolução precisa apontar para o claim do conflito")
            if (
                resolution.chosen_value_hash is not None
                and resolution.chosen_value_hash
                not in {member.normalized_value_hash for member in conflict.members}
            ):
                raise LedgerConflictError("O valor escolhido não pertence aos membros do conflito")
            final_value = _claim_value(content, resolution.claim_path)
            if resolution.chosen_value_hash is not None and _claim_value_hash(final_value) != resolution.chosen_value_hash:
                raise LedgerConflictError(
                    "O snapshot final não contém o valor escolhido para o conflito",
                    context={"claim_path": resolution.claim_path},
                )
            if resolution.synthesized_value_json is not None:
                synthesized = json.loads(resolution.synthesized_value_json)
                if canonical_json(final_value) != canonical_json(synthesized):
                    raise LedgerConflictError(
                        "O snapshot final não contém o valor sintetizado para o conflito",
                        context={"claim_path": resolution.claim_path},
                    )
        family = await self.ledger.get_family(family_id)
        if family is None:
            raise LedgerConflictError("Família do conflito não existe")
        content = _normalize_existing_family_content(
            family,
            content,
            current_content=current.content,
        )
        source_revisions = [current]
        for resolution in resolutions_tuple:
            conflict = await self.ledger.get_conflict_case(resolution.conflict_id)
            if conflict is not None:
                for member in conflict.members:
                    revision = await self.ledger.get_revision(member.revision_id)
                    if revision is not None and revision.revision_id not in {item.revision_id for item in source_revisions}:
                        source_revisions.append(revision)
        resolution_origins = tuple(
            origin
            for resolution in resolutions_tuple
            for origin in resolution.field_origins
        )
        _validate_field_origins(resolution_origins, tuple(source_revisions), content)
        return await self._build(
            operation=LedgerOperation.RESOLVE_CONFLICT,
            content=content,
            before=(current.content,),
            target_family_id=family_id,
            base_revision_ids=(current.revision_id,),
            expected_heads=((family_id, str(content.memory_scope), content.memory_branch, current.revision_id),),
            source_revision_ids=tuple(item.revision_id for item in source_revisions),
            requested_by=requested_by,
            evidence=(),
            reason=reason,
            idempotency_key=idempotency_key,
            field_origins=resolution_origins,
            conflict_resolutions=resolutions_tuple,
        )

    async def propose_link(
        self,
        source_family_id: uuid.UUID,
        target_family_id: uuid.UUID,
        relation_type: str,
        *,
        requested_by: str = "agent",
        evidence: Iterable[Evidence] = (),
        reason: str = "Relação semântica proposta",
        idempotency_key: str = "",
    ) -> ChangeProposal:
        relation_type = relation_type.strip().upper()
        if source_family_id == target_family_id:
            raise LedgerConflictError("Uma relação não pode apontar para a própria família")
        if relation_type == "RELATED_TO" and str(source_family_id) > str(target_family_id):
            source_family_id, target_family_id = target_family_id, source_family_id
        source_family = await self.ledger.get_family(source_family_id)
        target_family = await self.ledger.get_family(target_family_id)
        if source_family is None or target_family is None:
            raise LedgerConflictError("As famílias da relação não existem")
        source_branch = "pull_request" if source_family.memory_scope is MemoryScope.PULL_REQUEST else (
            "episodic" if source_family.memory_scope is MemoryScope.EPISODIC else
            "procedural" if source_family.memory_scope is MemoryScope.PROCEDURAL else "semantic"
        )
        target_branch = "pull_request" if target_family.memory_scope is MemoryScope.PULL_REQUEST else (
            "episodic" if target_family.memory_scope is MemoryScope.EPISODIC else
            "procedural" if target_family.memory_scope is MemoryScope.PROCEDURAL else "semantic"
        )
        source_head = await self.ledger.get_head(source_family_id, source_family.memory_scope, source_branch)
        target_head = await self.ledger.get_head(target_family_id, target_family.memory_scope, target_branch)
        if source_head is None or target_head is None:
            raise LedgerConflictError("As duas famílias precisam possuir heads atuais")
        existing_relations = await self.ledger.list_relations()
        for relation in existing_relations:
            same_direction = (
                relation.source_family_id == source_family_id
                and relation.target_family_id == target_family_id
            )
            same_pair = same_direction or (
                relation.source_family_id == target_family_id
                and relation.target_family_id == source_family_id
            )
            if relation.relation_type == relation_type and same_pair:
                if relation.proposal_id is not None:
                    return await self.ledger.get_proposal(relation.proposal_id)
                raise LedgerConflictError("A relação ativa já existe")
        evidence_tuple = tuple(evidence)
        if not idempotency_key:
            idempotency_key = f"relation:{relation_type}:{source_family_id}:{target_family_id}"
        return await self._build(
            operation=LedgerOperation.LINK,
            content=None,
            before=(),
            target_family_id=source_family_id,
            base_revision_ids=(),
            expected_heads=(
                (
                    source_family_id,
                    str(source_head.memory_scope),
                    source_head.memory_branch,
                    source_head.revision_id,
                ),
                (
                    target_family_id,
                    str(target_head.memory_scope),
                    target_head.memory_branch,
                    target_head.revision_id,
                ),
            ),
            source_revision_ids=(),
            requested_by=requested_by,
            evidence=evidence_tuple,
            reason=reason,
            relation_type=relation_type,
            relation_target_family_id=target_family_id,
            idempotency_key=idempotency_key,
            target_branch=source_head.memory_branch,
        )

    async def _build(
        self,
        *,
        operation: LedgerOperation,
        content: MemoryContent | None,
        before: tuple[MemoryContent, ...],
        target_family_id: uuid.UUID | None,
        base_revision_ids: tuple[uuid.UUID, ...],
        expected_heads: tuple[tuple[uuid.UUID, str, str, uuid.UUID], ...],
        source_revision_ids: tuple[uuid.UUID, ...],
        requested_by: str,
        evidence: tuple[Evidence, ...],
        evidence_links: tuple[EvidenceLinkSpec, ...] = (),
        reason: str,
        field_origins: tuple[FieldOrigin, ...] = (),
        conflicts: tuple[ConflictCase, ...] = (),
        conflict_resolutions: tuple[ConflictResolution, ...] = (),
        idempotency_key: str = "",
        restore_revision_id: uuid.UUID | None = None,
        relation_type: str = "",
        relation_target_family_id: uuid.UUID | None = None,
        target_branch: str = "semantic",
        replacement_family_id: uuid.UUID | None = None,
        replacement_alias: str = "",
        merge_manifest_id: uuid.UUID | None = None,
        expected_manifest_hash: str = "",
    ) -> ChangeProposal:
        evidence = tuple(evidence)
        evidence_links = tuple(evidence_links)
        field_origins = tuple(field_origins)
        conflicts = tuple(conflicts)
        conflict_resolutions = tuple(conflict_resolutions)
        field_diff = _diff(before[0] if len(before) == 1 else None, content)
        if evidence and not evidence_links:
            evidence_links = tuple(
                EvidenceLinkSpec(
                    evidence_id=item.evidence_id,
                    stance="supports",
                    confidence=item.source_reliability,
                )
                for item in evidence
            )
        hash_input = {
            "operation": operation.value,
            "target_family_id": str(target_family_id) if target_family_id else None,
            "expected_heads": [[str(a), b, c, str(d)] for a, b, c, d in expected_heads],
            "base_revision_ids": [str(item) for item in base_revision_ids],
            "source_revision_ids": [str(item) for item in source_revision_ids],
            "before": [item.model_dump(mode="json") for item in before],
            "after": content.model_dump(mode="json") if content else None,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "field_origins": [item.model_dump(mode="json") for item in field_origins],
            "evidence_links": [item.model_dump(mode="json") for item in evidence_links],
            "conflicts": [item.model_dump(mode="json") for item in conflicts],
            "conflict_resolutions": [item.model_dump(mode="json") for item in conflict_resolutions],
            "conflict_ids": [item.conflict_id for item in conflicts]
            + [item.conflict_id for item in conflict_resolutions],
            "conflict_versions": [
                [item.conflict_id, item.version] for item in conflicts
            ]
            + [
                [item.conflict_id, item.expected_conflict_version]
                for item in conflict_resolutions
            ],
            "reason": reason,
            "target_branch": content.memory_branch if content else "semantic",
            "restore_revision_id": str(restore_revision_id) if restore_revision_id else None,
            "merge_manifest_id": str(merge_manifest_id) if merge_manifest_id else None,
            "expected_manifest_hash": expected_manifest_hash,
            "relation_type": relation_type,
            "relation_target_family_id": str(relation_target_family_id) if relation_target_family_id else None,
            "replacement_family_id": str(replacement_family_id) if replacement_family_id else None,
            "replacement_alias": replacement_alias,
        }
        proposal = ChangeProposal(
            operation=operation,
            target_family_id=target_family_id,
            target_branch=content.memory_branch if content else target_branch,
            base_revision_ids=base_revision_ids,
            expected_heads=expected_heads,
            source_revision_ids=source_revision_ids,
            before=before,
            after=content,
            field_diff=field_diff,
            field_origins=field_origins,
            evidence=evidence,
            evidence_ids=tuple(item.evidence_id for item in evidence),
            evidence_links=evidence_links,
            conflict_ids=tuple(
                dict.fromkeys(
                    [item.conflict_id for item in conflicts]
                    + [item.conflict_id for item in conflict_resolutions]
                )
            ),
            conflict_snapshot_hash=(
                "sha256:" + hashlib.sha256(canonical_json([item.model_dump(mode="json") for item in conflicts]).encode("utf-8")).hexdigest()
                if conflicts else ""
            ),
            conflict_versions=tuple(
                [(item.conflict_id, item.version) for item in conflicts]
                + [
                    (item.conflict_id, item.expected_conflict_version)
                    for item in conflict_resolutions
                ]
            ),
            detector_version="merge-detector.v2" if conflicts else None,
            detector_coverage=(
                ConflictDetectionCoverage.CONFLICT_FOUND if conflicts else ConflictDetectionCoverage.COMPLETE_NO_CONFLICT
            ),
            conflicts=conflicts,
            conflict_resolutions=conflict_resolutions,
            reason=reason,
            requested_by=requested_by,
            preview_hash=_preview_hash(hash_input),
            expires_at=utc_now() + timedelta(hours=24),
            idempotency_key=idempotency_key,
            restore_revision_id=restore_revision_id,
            relation_type=relation_type,
            relation_target_family_id=relation_target_family_id,
            replacement_family_id=replacement_family_id,
            replacement_alias=replacement_alias,
            merge_manifest_id=merge_manifest_id,
            expected_manifest_hash=expected_manifest_hash,
            status=ProposalStatus.CONFLICTED if conflicts else ProposalStatus.PENDING_APPROVAL,
        )
        return await self.ledger.save_proposal(proposal)


class LocalApprovalBoundary:
    """Fronteira local de aprovação; não é autenticação externa forte."""

    def __init__(self, ledger) -> None:  # noqa: ANN001
        self.ledger = ledger

    async def approve(
        self,
        proposal_id: uuid.UUID,
        *,
        principal_id: str,
        principal_type: str = "operator",
        preview_hash: str,
        comment: str = "",
    ) -> ApprovalDecision:
        if not principal_id or principal_type == "agent":
            raise ApprovalError("A aprovação exige um principal operador separado")
        proposal = await self.ledger.get_proposal(proposal_id)
        if principal_id.strip().casefold() == proposal.requested_by.strip().casefold():
            raise ApprovalError("Quem propôs a alteração não pode aprovar a própria proposta")
        if principal_id.strip().casefold().startswith(("agent", "system", "anonymous")):
            raise ApprovalError("A identidade de aprovação não pode ser de agente ou sistema")
        if principal_type.strip().casefold() in {"agent", "system", "anonymous"}:
            raise ApprovalError("A aprovação exige um principal operador separado")
        if proposal.status is not ProposalStatus.PENDING_APPROVAL:
            raise ApprovalError("Somente propostas pendentes podem ser aprovadas")
        if preview_hash != proposal.preview_hash:
            raise ApprovalError("Hash do preview inválido")
        approval = ApprovalDecision(
            proposal_id=proposal_id,
            principal_id=principal_id,
            principal_type=principal_type,
            preview_hash=preview_hash,
            expected_heads=proposal.expected_heads,
            comment=comment,
            expires_at=proposal.expires_at,
        )
        return await self.ledger.save_approval(approval)

    async def reject(
        self,
        proposal_id: uuid.UUID,
        reason: str,
        *,
        principal_id: str,
        principal_type: str = "operator",
    ) -> ChangeProposal:
        return await self.ledger.reject_proposal(
            proposal_id,
            reason,
            principal_id=principal_id,
            principal_type=principal_type,
        )


class LedgerApplyService:
    """Única porta de aplicação; recebe somente IDs, nunca conteúdo do cliente."""

    def __init__(self, ledger) -> None:  # noqa: ANN001
        self.ledger = ledger

    async def apply(self, proposal_id: uuid.UUID, approval_id: uuid.UUID):
        return await self.ledger.apply_approved(proposal_id, approval_id)
