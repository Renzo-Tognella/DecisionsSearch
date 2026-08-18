from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterable

from decisionssearch.domain.memory.memory_item import MemoryItem
from decisionssearch.domain.memory_ledger import (
    Evidence,
    EvidenceVerification,
    MemoryAlias,
    MemoryAliasStatus,
    MemoryContent,
    MemoryFamily,
    MemoryRevision,
    MemoryScope,
    content_hash,
)
from decisionssearch.application.memory.ledger.adapters import episode_to_content, pr_to_content, procedure_to_content
from decisionssearch.domain.episodic.episodic_memory import EpisodicMemory
from decisionssearch.domain.pr_memory.pr_memory import PRMemory
from decisionssearch.domain.procedural.procedural_memory import ProceduralMemory


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LegacyMigrationRecord:
    source_record_key: str
    legacy_memory_id: str
    family: MemoryFamily
    revision: MemoryRevision
    evidence: Evidence
    alias: MemoryAlias
    legacy_status: str


@dataclass(frozen=True)
class MigrationPlan:
    manifest: dict
    records: tuple[LegacyMigrationRecord, ...]


class LegacyMemoryMigrator:
    """Planeja um backfill sem inventar o histórico sobrescrito."""

    NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "decisionssearch:legacy-memory-migration:v2")

    def plan(
        self,
        items: Iterable[MemoryItem],
        *,
        migration_run_id: str,
        dry_run: bool = True,
    ) -> MigrationPlan:
        records: list[LegacyMigrationRecord] = []
        source_rows: list[dict] = []
        for index, item in enumerate(items):
            content = MemoryContent(
                project=item.project,
                category=item.category,
                title=item.title,
                summary=item.summary,
                details=item.details,
                objective=item.objective,
                trigger=item.trigger,
                domain=tuple(item.domain),
                modules=tuple(item.modules),
                stakeholders=tuple(item.stakeholders),
                action_triggers=tuple(item.action_triggers),
                related_files=tuple(item.related_files),
                business_rules=tuple(item.business_rules),
                architectural_rationale=item.architectural_rationale,
                examples=tuple(item.examples),
                alternatives_considered=tuple(item.alternatives_considered),
                memory_branch=item.branch,
                valid_from=item.valid_at,
                valid_to=item.invalid_at,
            )
            snapshot_hash = content_hash(content)
            source_record_key = f"{item.memory_id}|{item.project}|{item.category}|{item.branch}|{snapshot_hash}"
            family_id = uuid.uuid5(self.NAMESPACE, source_record_key)
            revision_id = uuid.uuid5(family_id, "legacy_import:v1")
            evidence_id = uuid.uuid5(family_id, "legacy_evidence:v1")
            family = MemoryFamily(
                family_id=family_id,
                project=item.project,
                category=item.category,
                memory_scope=MemoryScope.SEMANTIC,
                created_at=item.created_at,
                created_by="legacy_import",
                legacy_memory_id=item.memory_id,
                migration_run_id=migration_run_id,
            )
            evidence = Evidence(
                evidence_id=evidence_id,
                source_kind="legacy_import",
                source_locator=item.memory_id,
                source_hash=item.source_hash or snapshot_hash,
                captured_at=item.created_at,
                observed_at=item.event_date,
                extractor="legacy_backfill",
                verification=EvidenceVerification.UNAVAILABLE,
                excerpt_or_hash=f"legacy_evidence_count={item.evidence_count}",
            )
            revision = MemoryRevision(
                revision_id=revision_id,
                family_id=family_id,
                version=1,
                content=content,
                content_hash=snapshot_hash,
                actor_id="legacy_import",
                actor_type="migration",
                reason="Migração do MemoryItem legado; histórico anterior não estava disponível",
                created_at=item.created_at,
                recorded_from=item.created_at,
                evidence_ids=(evidence_id,),
            )
            alias = MemoryAlias(
                alias=item.memory_id,
                family_id=family_id,
                project=item.project,
                category=item.category,
                memory_branch=item.branch,
            )
            records.append(
                LegacyMigrationRecord(
                    source_record_key=source_record_key,
                    legacy_memory_id=item.memory_id,
                    family=family,
                    revision=revision,
                    evidence=evidence,
                    alias=alias,
                    legacy_status=item.status.value,
                )
            )
            source_rows.append({"key": source_record_key, "content_hash": snapshot_hash})

        aliases: dict[str, list[uuid.UUID]] = {}
        for record in records:
            aliases.setdefault(record.legacy_memory_id, []).append(record.family.family_id)
        ambiguous = sorted(alias for alias, candidates in aliases.items() if len(set(candidates)) > 1)
        if ambiguous:
            normalized_records = []
            for record in records:
                if record.legacy_memory_id in ambiguous:
                    candidates = tuple(aliases[record.legacy_memory_id])
                    normalized_records.append(
                        replace(
                            record,
                            alias=record.alias.model_copy(
                                update={
                                    "family_id": None,
                                    "status": MemoryAliasStatus.AMBIGUOUS,
                                    "candidates": candidates,
                                }
                            ),
                        )
                    )
                else:
                    normalized_records.append(record)
            records = normalized_records
        manifest = {
            "schema_version": "memory-ledger-v2.2",
            "migration_run_id": migration_run_id,
            "dry_run": dry_run,
            "generated_at": utc_now().isoformat(),
            "source_record_count": len(records),
            "family_count": len({record.family.family_id for record in records}),
            "revision_count": len({record.revision.revision_id for record in records}),
            "ambiguous_alias_count": len(ambiguous),
            "ambiguous_aliases": ambiguous,
            "source_snapshot_hash": "sha256:" + hashlib.sha256(
                json.dumps(source_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        return MigrationPlan(manifest=manifest, records=tuple(records))

    def plan_all(
        self,
        *,
        items: Iterable[MemoryItem] = (),
        episodes: Iterable[EpisodicMemory] = (),
        procedures: Iterable[ProceduralMemory] = (),
        pr_memories: Iterable[PRMemory] = (),
        migration_run_id: str,
        dry_run: bool = True,
    ) -> MigrationPlan:
        """Planeja a migração das quatro superfícies legadas.

        O método não tenta inventar versões anteriores: cada registro disponível
        entra como uma revisão ``legacy_import`` e o manifesto marca a lacuna de
        histórico. IDs antigos são aliases explícitos e colisões ficam em
        quarentena como nos MemoryItems semânticos.
        """

        base = list(self.plan(items, migration_run_id=migration_run_id, dry_run=dry_run).records)
        structured = [
            (episode_to_content(item), item.episode_id, item.created_at, "episodic", item.outcome.value)
            for item in episodes
        ]
        structured.extend(
            (procedure_to_content(item), item.procedure_id, item.created_at, "procedural", "active")
            for item in procedures
        )
        structured.extend(
            (pr_to_content(item), item.memory_id, utc_now(), "pull_request", item.status)
            for item in pr_memories
        )
        for content, legacy_id, created_at, source_kind, legacy_status in structured:
            source_key = f"{source_kind}|{legacy_id}|{content.project}|{content_hash(content)}"
            family_id = uuid.uuid5(self.NAMESPACE, source_key)
            revision_id = uuid.uuid5(family_id, "legacy_import:v1")
            evidence_id = uuid.uuid5(family_id, "legacy_evidence:v1")
            family = MemoryFamily(
                family_id=family_id,
                project=content.project,
                category=content.category,
                memory_scope=content.memory_scope,
                created_at=created_at,
                created_by="legacy_import",
                legacy_memory_id=legacy_id,
                migration_run_id=migration_run_id,
            )
            evidence = Evidence(
                evidence_id=evidence_id,
                source_kind=source_kind,
                source_locator=legacy_id,
                captured_at=created_at,
                extractor="legacy_backfill",
                verification=EvidenceVerification.UNAVAILABLE,
                excerpt_or_hash="history_gap=previous revisions unavailable",
            )
            revision = MemoryRevision(
                revision_id=revision_id,
                family_id=family_id,
                version=1,
                content=content,
                content_hash=content_hash(content),
                actor_id="legacy_import",
                actor_type="migration",
                reason=f"Migração de {source_kind}; histórico anterior não estava disponível",
                created_at=created_at,
                recorded_from=created_at,
                evidence_ids=(evidence_id,),
            )
            base.append(
                LegacyMigrationRecord(
                    source_record_key=source_key,
                    legacy_memory_id=legacy_id,
                    family=family,
                    revision=revision,
                    evidence=evidence,
                    alias=MemoryAlias(
                        alias=legacy_id,
                        family_id=family_id,
                        project=content.project,
                        category=content.category,
                        memory_branch=content.memory_branch,
                    ),
                    legacy_status=legacy_status,
                )
            )
        aliases: dict[str, list[uuid.UUID]] = {}
        for record in base:
            aliases.setdefault(record.legacy_memory_id, []).append(record.family.family_id)
        ambiguous = sorted(alias for alias, candidates in aliases.items() if len(set(candidates)) > 1)
        normalized = []
        for record in base:
            if record.legacy_memory_id in ambiguous:
                record = replace(
                    record,
                    alias=record.alias.model_copy(
                        update={
                            "family_id": None,
                            "status": MemoryAliasStatus.AMBIGUOUS,
                            "candidates": tuple(aliases[record.legacy_memory_id]),
                        }
                    ),
                )
            normalized.append(record)
        records = tuple(normalized)
        source_rows = [{"key": item.source_record_key, "content_hash": item.revision.content_hash} for item in records]
        manifest = {
            "schema_version": "memory-ledger-v2.3",
            "migration_run_id": migration_run_id,
            "dry_run": dry_run,
            "generated_at": utc_now().isoformat(),
            "source_record_count": len(records),
            "family_count": len({item.family.family_id for item in records}),
            "revision_count": len({item.revision.revision_id for item in records}),
            "ambiguous_alias_count": len(ambiguous),
            "ambiguous_aliases": ambiguous,
            "history_gap": True,
            "source_scopes": sorted({item.revision.content.memory_scope.value for item in records}),
            "source_snapshot_hash": "sha256:" + hashlib.sha256(
                json.dumps(source_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        return MigrationPlan(manifest=manifest, records=records)

    async def apply(self, plan: MigrationPlan, ledger) -> dict[str, int]:  # noqa: ANN001
        """Aplica o plano apenas em um adapter que expõe import_legacy.

        A operação é administrativa e deve rodar com lock, backup e dry-run
        prévio. Não é exposta ao agente.
        """
        if plan.manifest.get("dry_run", True):
            raise RuntimeError(
                "O plano está marcado como dry_run; gere outro plano com dry_run=False "
                "após revisar o manifesto"
            )
        if not hasattr(ledger, "import_legacy"):
            raise RuntimeError("O adapter não suporta importação administrativa legada")
        imported = 0
        for record in plan.records:
            await ledger.import_legacy(record)
            imported += 1
        return {"records": imported, "families": len({item.family.family_id for item in plan.records})}
