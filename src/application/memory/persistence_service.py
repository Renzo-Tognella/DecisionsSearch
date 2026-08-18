from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from decisionssearch.domain.shared.exceptions import StorageConsistencyError
from decisionssearch.domain.memory.memory_candidate import MemoryCandidate
from decisionssearch.domain.memory.memory_item import MemoryItem, MemoryStatus
from decisionssearch.infrastructure.ai.embeddings.embedding_service import EmbeddingService
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.infrastructure.persistence.qdrant.qdrant_service import QdrantService
from decisionssearch.application.governance.weight_service import WeightService


class PersistenceService:
    """Orquestra persistencia canonica (Qdrant + Neo4j)."""

    def __init__(
        self,
        neo4j: Neo4jService,
        qdrant: QdrantService,
        embeddings: EmbeddingService,
        weight_service: WeightService | None = None,
        proposal_service=None,  # noqa: ANN001
    ):
        self.neo4j = neo4j
        self.qdrant = qdrant
        self.embeddings = embeddings
        self.weight_service = weight_service or WeightService()
        self.proposal_service = proposal_service

    async def persist(self, candidate: MemoryCandidate, admission: dict | object):
        if self.proposal_service is not None:
            proposal = await self.proposal_service.propose_candidate(
                candidate,
                admission,
                requested_by="agent",
                reason="Escrita legada convertida em proposta governada",
                idempotency_key=(
                    f"{candidate.source_event_id}:{candidate.type}:{candidate.title}"
                    if candidate.source_event_id
                    else ""
                ),
            )
            return {
                "proposal_id": str(proposal.proposal_id),
                "family_id": str(proposal.target_family_id) if proposal.target_family_id else None,
                "revision_id": None,
                "memory_id": None,
                "status": proposal.status.value,
                "requires_human_approval": True,
                "preview_hash": proposal.preview_hash,
                "before": [item.model_dump(mode="json") for item in proposal.before],
                "after": proposal.after.model_dump(mode="json") if proposal.after else None,
                "field_diff": [item.model_dump(mode="json") for item in proposal.field_diff],
                "evidence": [item.model_dump(mode="json") for item in proposal.evidence],
                "reason": proposal.reason,
                "operation": proposal.operation.value,
                "relation_type": proposal.relation_type or None,
                "relation_target_family_id": (
                    str(proposal.relation_target_family_id)
                    if proposal.relation_target_family_id
                    else None
                ),
                "question": "A alteração faz sentido e deve ser aprovada?",
            }
        admission_data = admission if isinstance(admission, dict) else vars(admission)
        action = str(admission_data.get("action", "create"))

        if action == "refine":
            item = await self._create_or_update(candidate, admission_data)
            related_id = admission_data.get("related_id")
            if related_id:
                await self.neo4j.link_memories(item.memory_id, "REFINES", related_id)
            return item

        if action in ("create", "update"):
            return await self._create_or_update(candidate, admission_data)

        raise ValueError(f"Ação de persistência não suportada: {action}")

    async def _create_or_update(self, candidate: MemoryCandidate, admission: dict) -> MemoryItem:
        memory_id = admission.get("memory_id") or MemoryItem.generate_id(
            project=candidate.project,
            type=candidate.type,
            title=candidate.title,
        )

        status_raw = str(admission.get("status", "proposed")).lower()
        try:
            status = MemoryStatus(status_raw)
        except ValueError:
            status = MemoryStatus.PROPOSED

        confidence = min(len(candidate.evidence) * 0.25, 1.0)
        category_config = self.weight_service.get_priority_config(candidate.type)
        effective_weight = self.weight_service.calculate_effective_weight(
            weight_manual=float(candidate.proposed_weight),
            weight_confidence=confidence,
            weight_usage=0.0,
            weight_feedback=0.0,
            significance=self.weight_service.significance_for_category(candidate.type),
            config=category_config,
        )

        item = MemoryItem(
            memory_id=memory_id,
            project=candidate.project,
            category=candidate.type,
            domain=candidate.domain,
            modules=candidate.modules,
            title=candidate.title,
            summary=candidate.summary,
            details=candidate.details,
            objective=candidate.objective,
            trigger=candidate.trigger,
            stakeholders=candidate.stakeholders,
            action_triggers=candidate.action_triggers,
            related_files=candidate.related_files,
            business_rules=candidate.business_rules,
            architectural_rationale=candidate.architectural_rationale,
            examples=candidate.examples,
            alternatives_considered=candidate.alternatives_considered,
            event_date=candidate.event_date,
            status=status,
            weight_manual=float(candidate.proposed_weight),
            weight_confidence=confidence,
            weight_contextual=0.5,
            significance=self.weight_service.significance_for_category(candidate.type),
            effective_weight=effective_weight,
            evidence_count=len(candidate.evidence),
            updated_at=datetime.now(timezone.utc),
        )

        embedding_text = self.embeddings.build_text_for_embedding(
            title=item.title,
            summary=item.summary,
            details=item.details,
            modules=item.modules,
            objective=item.objective,
            trigger=item.trigger,
            business_rules=item.business_rules,
            architectural_rationale=item.architectural_rationale,
        )
        if getattr(self.qdrant, "sparse_enabled", False):
            embedding, sparse_embedding = await asyncio.gather(
                self.embeddings.embed(embedding_text),
                self.embeddings.embed_sparse(embedding_text),
            )
        else:
            embedding = await self.embeddings.embed(embedding_text)
            sparse_embedding = None

        try:
            upsert_kwargs = {
                "memory_id": item.memory_id,
                "embedding": embedding,
                "item": item,
            }
            if sparse_embedding is not None:
                upsert_kwargs["sparse_vector"] = sparse_embedding
            await self.qdrant.upsert(**upsert_kwargs)
        except Exception as error:
            raise StorageConsistencyError(
                f"Falha ao persistir no Qdrant: {error}",
                memory_id=item.memory_id,
                store="qdrant",
            ) from error

        try:
            await self.neo4j.upsert_memory(
                memory_id=item.memory_id,
                project=item.project,
                category=item.category,
                domains=item.domain,
                title=item.title,
                summary=item.summary,
                details=item.details,
                status=item.status.value,
                weight=item.effective_weight,
                objective=item.objective,
                trigger=item.trigger,
                stakeholders=item.stakeholders,
                action_triggers=item.action_triggers,
                related_files=item.related_files,
                business_rules=item.business_rules,
                architectural_rationale=item.architectural_rationale,
                modules=item.modules,
                examples=item.examples,
                alternatives_considered=item.alternatives_considered,
                event_date=item.event_date.isoformat() if item.event_date else "",
            )
        except Exception as error:
            await self.qdrant.delete(item.memory_id)
            raise StorageConsistencyError(
                f"Falha ao persistir no Neo4j (compensado no Qdrant): {error}",
                memory_id=item.memory_id,
                store="neo4j",
            ) from error
        return item
