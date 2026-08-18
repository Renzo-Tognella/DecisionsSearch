from __future__ import annotations

import logging
from datetime import datetime, timezone

from decisionssearch.application.shared.jaro_winkler import jaro_winkler
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.infrastructure.persistence.qdrant.qdrant_service import QdrantService
from decisionssearch.application.governance.weight_service import WeightService
from decisionssearch.domain.memory_ledger import FieldOrigin, LedgerOperation

logger = logging.getLogger(__name__)


class ConsolidationService:
    def __init__(self, neo4j: Neo4jService, qdrant: QdrantService, proposal_service=None):  # noqa: ANN001
        self.neo4j = neo4j
        self.qdrant = qdrant
        self.proposal_service = proposal_service
        self.weight_service = WeightService()
        self.last_proposals: list[dict] = []

    async def run_now(self, scope: str = "all") -> int:
        if self.proposal_service is not None:
            self.last_proposals = await self.propose_now(scope)
            return len(self.last_proposals)
        count = 0
        count += await self._merge_near_duplicates(scope)
        count += await self._recalculate_weights(scope)
        count += await self._promote_proposed(scope)
        count += await self._deprecate_stale(scope)
        return count

    async def propose_now(self, scope: str = "all") -> list[dict]:
        """Propõe merges de duplicatas; nunca aplica a decisão automaticamente."""
        if self.proposal_service is None:
            return []
        all_revisions = await self.proposal_service.ledger.list_revisions(
            project=None if scope == "all" else scope,
        )
        proposals: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for revision in all_revisions:
            if revision.content.valid_to and revision.content.valid_to <= datetime.now(timezone.utc):
                get_current_head = getattr(self.proposal_service.ledger, "get_current_head", None)
                head = (
                    await get_current_head(
                        revision.family_id,
                        revision.content.memory_scope,
                        revision.content.memory_branch,
                    )
                    if get_current_head is not None
                    else await self.proposal_service.ledger.get_head(
                        revision.family_id,
                        revision.content.memory_scope,
                        revision.content.memory_branch,
                    )
                )
                if head and head.revision_id == revision.revision_id:
                    proposal = await self.proposal_service.propose_state_change(
                        revision.family_id,
                        operation=LedgerOperation.INVALIDATE,
                        requested_by="consolidation_worker",
                        reason="A validade temporal da memória expirou",
                        idempotency_key=f"expiry:{revision.revision_id}",
                        memory_branch=revision.content.memory_branch,
                    )
                    proposals.append(proposal.model_dump(mode="json"))
        revisions = await self.proposal_service.ledger.list_active_revisions(
            project=None if scope == "all" else scope,
        )
        active_relations = await self.proposal_service.ledger.list_relations()
        for index, left in enumerate(revisions):
            for right in revisions[index + 1 :]:
                if left.family_id == right.family_id:
                    continue
                if left.content.project != right.content.project or left.content.category != right.content.category:
                    continue
                pair = tuple(sorted((str(left.revision_id), str(right.revision_id))))
                if pair in seen:
                    continue
                seen.add(pair)
                ratio = jaro_winkler(left.content.title.casefold(), right.content.title.casefold())

                # RELATED_TO é uma relação estrutural, não um sinônimo de
                # "mesmo domínio". Exigimos contexto compartilhado observável
                # (arquivo ou módulo + domínio) e não criamos uma segunda aresta
                # quando já existe qualquer relação ativa entre as famílias.
                relation_family_pair = tuple(
                    sorted((str(left.family_id), str(right.family_id)))
                )
                has_relation = any(
                    tuple(sorted((str(item.source_family_id), str(item.target_family_id))))
                    == relation_family_pair
                    for item in active_relations
                )
                shared_files = self._shared_values(left.content.related_files, right.content.related_files)
                shared_modules = self._shared_values(left.content.modules, right.content.modules)
                shared_domains = self._shared_values(left.content.domain, right.content.domain)
                if (
                    not has_relation
                    and ratio < 0.90
                    and (shared_files or (shared_modules and shared_domains))
                ):
                    related_proposal = await self.proposal_service.propose_link(
                        left.family_id,
                        right.family_id,
                        "RELATED_TO",
                        requested_by="consolidation_worker",
                        reason=(
                            "Contexto compartilhado detectado: "
                            f"{len(shared_files)} arquivo(s), {len(shared_modules)} módulo(s), "
                            f"{len(shared_domains)} domínio(s)"
                        ),
                        idempotency_key=f"related:{relation_family_pair[0]}:{relation_family_pair[1]}",
                    )
                    proposals.append(related_proposal.model_dump(mode="json"))
                if ratio < 0.90:
                    continue
                target, source = (
                    (left, right)
                    if (left.content.title, str(left.family_id)) <= (right.content.title, str(right.family_id))
                    else (right, left)
                )
                get_current_head = getattr(self.proposal_service.ledger, "get_current_head", None)
                if get_current_head is not None:
                    target_head = await get_current_head(
                        target.family_id,
                        target.content.memory_scope,
                        target.content.memory_branch,
                    )
                    source_head = await get_current_head(
                        source.family_id,
                        source.content.memory_scope,
                        source.content.memory_branch,
                    )
                else:
                    target_head = await self.proposal_service.ledger.get_head(
                        target.family_id,
                        target.content.memory_scope,
                        target.content.memory_branch,
                    )
                    source_head = await self.proposal_service.ledger.get_head(
                        source.family_id,
                        source.content.memory_scope,
                        source.content.memory_branch,
                    )
                if target_head is None or source_head is None:
                    continue
                merged_content, origins = self._merge_content(target, source)
                proposal = await self.proposal_service.propose_merge(
                    target.family_id,
                    merged_content,
                    expected_heads=(
                        (target.family_id, str(target_head.memory_scope), target_head.memory_branch, target_head.revision_id),
                        (source.family_id, str(source_head.memory_scope), source_head.memory_branch, source_head.revision_id),
                    ),
                    source_revision_ids=(target.revision_id, source.revision_id),
                    field_origins=origins,
                    requested_by="consolidation_worker",
                    reason=f"Duplicata semântica detectada (similaridade de título {ratio:.3f})",
                    idempotency_key=f"merge:{pair[0]}:{pair[1]}",
                )
                proposals.append(proposal.model_dump(mode="json"))
        return proposals

    @staticmethod
    def _shared_values(left, right) -> set[str]:  # noqa: ANN001
        def normalize(value) -> str:  # noqa: ANN001
            return str(value).strip().casefold()

        return {
            normalize(value)
            for value in left
            if normalize(value)
        }.intersection(
            {
                normalize(value)
                for value in right
                if normalize(value)
            }
        )

    @staticmethod
    def _merge_content(left, right):  # noqa: ANN001
        """Combina campos determinísticos; a aprovação humana continua obrigatória."""
        from decisionssearch.domain.memory_ledger import MemoryContent

        left_data = left.content.model_dump()
        right_data = right.content.model_dump()
        origins: list[FieldOrigin] = []
        lineage_fields = {
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
        }
        for field, right_value in right_data.items():
            left_value = left_data.get(field)
            if field in {"schema_version", "memory_scope", "memory_branch", "project", "category"}:
                continue
            if (not left_value) and right_value:
                left_data[field] = right_value
                if field in lineage_fields:
                    origins.append(FieldOrigin(field=field, source_revision_id=right.revision_id, note="campo vazio no alvo"))
            elif isinstance(left_value, (list, tuple)) and isinstance(right_value, (list, tuple)):
                merged = tuple(dict.fromkeys([*left_value, *right_value]))
                if merged != tuple(left_value):
                    left_data[field] = merged
                    # Uma união tem dois contribuidores. Até o modelo de lineage
                    # suportar múltiplas origens por campo, ela não pode ser
                    # mascarada como se viesse apenas da revisão direita.
        return MemoryContent(**left_data), tuple(origins)
    async def schedule(self, scope: str = "all") -> str:
        # MVP: só retorna id lógico; integração real com fila fica para fase posterior.
        await self.run_now(scope=scope)
        return f"job-{scope}-inline"

    async def _merge_near_duplicates(self, scope: str) -> int:
        projects = [scope] if scope != "all" else await self.neo4j.list_projects()
        by_id: list[dict] = []
        for project in projects:
            rows = await self.neo4j.query_by_project(project=project, status="active", limit=200)
            by_id.extend([row.get("memory", {}) for row in rows if row.get("memory")])
        prefix_map: dict[str, list[dict]] = {}
        for mem in by_id:
            prefix = str(mem.get("title", ""))[:4].lower()
            prefix_map.setdefault(prefix, []).append(mem)

        merged = 0
        checked: set[tuple[str, str]] = set()
        for group in prefix_map.values():
            for left in group:
                for right in group:
                    left_id = left.get("memory_id", "")
                    right_id = right.get("memory_id", "")
                    if left_id >= right_id:
                        continue
                    pair = (left_id, right_id)
                    if pair in checked:
                        continue
                    checked.add(pair)
                    ratio = jaro_winkler(
                        str(left.get("title", "")).lower(),
                        str(right.get("title", "")).lower(),
                    )
                    if ratio < 0.90:
                        continue
                    winner = (
                        left
                        if float(left.get("effective_weight", 0.0))
                        >= float(right.get("effective_weight", 0.0))
                        else right
                    )
                    loser = right if winner is left else left
                    await self.neo4j.deprecate_memory(
                        loser["memory_id"], replaced_by=winner["memory_id"]
                    )
                    try:
                        await self.qdrant.delete(loser["memory_id"])
                    except Exception:
                        logger.exception(
                            "Failed to delete orphaned vector %s from Qdrant", loser["memory_id"]
                        )
                    merged += 1
        return merged

    async def _recalculate_weights(self, scope: str) -> int:
        projects = [scope] if scope != "all" else await self.neo4j.list_projects()
        updated = 0
        for project in projects:
            rows = await self.neo4j.query_by_project(project=project, status="active", limit=500)
            for row in rows:
                memory = row.get("memory", {})
                category = memory.get("category", "")
                config = self.weight_service.get_priority_config(category)
                cat_ws = WeightService(config=config)
                new_weight = cat_ws.calculate_effective_weight(
                    weight_manual=float(memory.get("weight_manual", 0.5) or 0.5),
                    weight_confidence=float(memory.get("weight_confidence", 0.5) or 0.5),
                    weight_usage=float(memory.get("weight_usage", 0.0) or 0.0),
                    weight_feedback=float(memory.get("weight_feedback", 0.0) or 0.0),
                    significance=float(memory.get("significance", 0.5) or 0.5),
                )
                mid = memory.get("memory_id", "")
                await self.neo4j.set_weight(
                    mid,
                    float(memory.get("weight_manual", 0.5) or 0.5),
                    new_weight,
                )
                try:
                    await self.qdrant.update_payload(mid, {"effective_weight": new_weight})
                except Exception:
                    logger.exception("Failed to update Qdrant payload for %s", mid)
                updated += 1
        return updated

    async def _promote_proposed(self, scope: str) -> int:
        return await self.neo4j.promote_proposed(min_evidence=2, scope=scope)

    async def reconcile_stores(self, project: str | None = None) -> dict:
        if self.proposal_service is not None:
            return {
                "status": "canonical_ledger",
                "message": "A reconciliação deve consumir o outbox/rebuild do ledger; nenhum store foi alterado.",
                "project": project,
            }
        projects = [project] if project else await self.neo4j.list_projects()
        neo4j_ids: set[str] = set()
        for proj in projects:
            rows = await self.neo4j.query_by_project(project=proj, status="active", limit=5000)
            for row in rows:
                mid = row.get("memory", {}).get("memory_id", "")
                if mid:
                    neo4j_ids.add(mid)

        qdrant_ids = set(await self.qdrant.get_all_memory_ids(project=project))

        qdrant_orphans = qdrant_ids - neo4j_ids
        for orphan_id in qdrant_orphans:
            try:
                await self.qdrant.delete(orphan_id)
            except Exception:
                logger.exception("Failed to delete Qdrant orphan %s", orphan_id)

        neo4j_orphans = neo4j_ids - qdrant_ids
        for orphan_id in neo4j_orphans:
            logger.warning("Neo4j memory %s has no Qdrant vector", orphan_id)

        return {
            "neo4j_count": len(neo4j_ids),
            "qdrant_count": len(qdrant_ids),
            "qdrant_orphans": len(qdrant_orphans),
            "neo4j_orphans": len(neo4j_orphans),
            "cleaned": len(qdrant_orphans),
        }

    async def _deprecate_stale(self, scope: str) -> int:
        count = await self.neo4j.deprecate_low_weight(threshold=0.1, scope=scope)
        if count == 0:
            return 0
        projects = [scope] if scope != "all" else await self.neo4j.list_projects()
        for project in projects:
            rows = await self.neo4j.query_by_project(
                project=project, status="deprecated", limit=500
            )
            for row in rows:
                mid = row.get("memory", {}).get("memory_id", "")
                if not mid:
                    continue
                try:
                    await self.qdrant.delete(mid)
                except Exception:
                    logger.exception("Failed to delete stale vector %s from Qdrant", mid)
        return count
