from __future__ import annotations

from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.domain.procedural.procedural_memory import ProceduralMemory
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.application.memory.ledger.adapters import hydrate_legacy, pending_envelope, procedure_to_content
from decisionssearch.domain.memory_ledger import MemoryScope, UsageObservation, usage_payload_hash
import uuid
from datetime import datetime, timezone


class ProceduralMemoryService:
    def __init__(self, neo4j: Neo4jService | None = None, *, proposal_service=None, ledger=None):  # noqa: ANN001
        self.neo4j = neo4j
        self.proposal_service = proposal_service
        self.ledger = ledger

    async def create_procedure(self, proc: ProceduralMemory) -> dict:
        if self.proposal_service is not None:
            proposal = await self.proposal_service.propose_create(
                procedure_to_content(proc),
                requested_by="agent",
                reason="Registro de procedimento reutilizável",
                idempotency_key=f"procedure:{proc.procedure_id}",
            )
            revision = (
                await self.ledger.get_revision(proposal.applied_revision_id)
                if proposal.applied_revision_id and self.ledger is not None
                else None
            )
            return pending_envelope(proposal, legacy_id=proc.procedure_id, revision=revision)
        if self.neo4j is None:
            raise MemoryServiceError("Serviço procedural sem ledger ou Neo4j")
        query = """
            MERGE (p:ProceduralMemory {procedure_id: $procedure_id})
            SET p.project = $project,
                p.task_type = $task_type,
                p.steps = $steps,
                p.preconditions = $preconditions,
                p.tools_required = $tools_required,
                p.success_rate = $success_rate,
                p.usage_count = $usage_count,
                p.tags = $tags,
                p.created_at = timestamp(),
                p.updated_at = timestamp()
            WITH p
            MATCH (proj:Project {name: $project})
            MERGE (p)-[:IN_PROJECT]->(proj)
        """
        try:
            async with self.neo4j.driver.session() as session:
                await session.run(
                    query,
                    procedure_id=proc.procedure_id,
                    project=proc.project,
                    task_type=proc.task_type,
                    steps=proc.steps,
                    preconditions=proc.preconditions,
                    tools_required=proc.tools_required,
                    success_rate=proc.success_rate,
                    usage_count=proc.usage_count,
                    tags=proc.tags,
                )
            return {"procedure_id": proc.procedure_id, "status": "created"}
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao criar procedimento: {error}",
                context={"procedure_id": proc.procedure_id},
            ) from error

    async def query_procedures(
        self,
        project: str,
        task_type: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        if self.ledger is not None:
            revisions = await self.ledger.list_effective_revisions(
                project=project,
                memory_scope=MemoryScope.PROCEDURAL,
                memory_branch="procedural",
            )
            rows = []
            for revision in reversed(revisions):
                row = hydrate_legacy(revision)
                usage_reader = getattr(self.ledger, "list_usage_observations", None)
                if usage_reader is not None:
                    observations = await usage_reader(revision.family_id)
                    if observations:
                        row["usage_count"] = len(observations)
                        row["success_rate"] = sum(item.success for item in observations) / len(observations)
                if task_type is not None and row.get("task_type") != task_type:
                    continue
                rows.append(row)
            rows.sort(key=lambda item: (float(item.get("success_rate", 0.0)), int(item.get("usage_count", 0))), reverse=True)
            return rows[:limit]
        if self.neo4j is None:
            raise MemoryServiceError("Serviço procedural sem ledger ou Neo4j")
        query = """
            MATCH (p:ProceduralMemory)-[:IN_PROJECT]->(:Project {name: $project})
            WHERE ($task_type IS NULL OR p.task_type = $task_type)
            RETURN p { .* } AS procedure
            ORDER BY p.success_rate DESC, p.usage_count DESC
            LIMIT $limit
        """
        try:
            async with self.neo4j.driver.session() as session:
                result = await session.run(query, project=project, task_type=task_type, limit=limit)
                return [record["procedure"] async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao consultar procedimentos: {error}",
                context={"project": project},
            ) from error

    EMA_ALPHA = 0.2

    async def record_usage(
        self,
        procedure_id: str,
        success: bool,
        *,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        observed_at: datetime | None = None,
        actor_id: str = "system",
        result: str = "",
    ) -> dict:
        """Registra uso e atualiza success_rate via EMA."""
        if self.ledger is not None:
            alias = await self.ledger.resolve_alias(procedure_id)
            if alias is None or alias.family_id is None:
                return {"error": "Procedure not found"}
            head = await self.ledger.get_head(alias.family_id, MemoryScope.PROCEDURAL, "procedural")
            if head is None:
                return {"error": "Procedure has no current head"}
            idempotency_key = idempotency_key or f"usage:{uuid.uuid4()}"
            correlation_id = correlation_id or str(uuid.uuid4())
            payload_hash = usage_payload_hash(
                procedure_family_id=alias.family_id,
                procedure_revision_id=head.revision_id,
                success=success,
                correlation_id=correlation_id,
                actor_id=actor_id,
                result=result,
            )
            observation = UsageObservation(
                procedure_family_id=alias.family_id,
                procedure_revision_id=head.revision_id,
                success=success,
                observed_at=observed_at or datetime.now(timezone.utc),
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                actor_id=actor_id,
                result=result,
                payload_hash=payload_hash,
            )
            saved = await self.ledger.record_usage_observation(observation)
            return {
                "status": "recorded",
                "observation_id": str(saved.observation_id),
                "procedure_id": procedure_id,
                "idempotency_key": saved.idempotency_key,
                "success": saved.success,
                "family_id": str(saved.procedure_family_id),
                "revision_id": str(saved.procedure_revision_id),
            }
        if self.neo4j is None:
            raise MemoryServiceError("Serviço procedural sem ledger ou Neo4j")
        query = """
            MATCH (p:ProceduralMemory {procedure_id: $procedure_id})
            WITH p,
                 coalesce(p.success_rate, 0.0) AS old_rate,
                 CASE WHEN $success THEN 1.0 ELSE 0.0 END AS outcome
            SET p.usage_count = coalesce(p.usage_count, 0) + 1,
                p.success_rate = old_rate * (1.0 - $alpha)
                    + outcome * $alpha,
                p.updated_at = timestamp()
            RETURN p { .* } AS procedure
        """
        try:
            async with self.neo4j.driver.session() as session:
                result = await session.run(
                    query,
                    procedure_id=procedure_id,
                    success=success,
                    alpha=self.EMA_ALPHA,
                )
                record = await result.single()
                if not record:
                    return {"error": "Procedure not found"}
                return record["procedure"]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao registrar uso: {error}",
                context={"procedure_id": procedure_id},
            ) from error
