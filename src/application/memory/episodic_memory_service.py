from __future__ import annotations

from decisionssearch.domain.episodic.episodic_memory import EpisodicMemory
from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.application.memory.ledger.adapters import episode_to_content, hydrate_legacy, pending_envelope
from decisionssearch.domain.memory_ledger import MemoryScope


class EpisodicMemoryService:
    def __init__(self, neo4j: Neo4jService | None = None, *, proposal_service=None, ledger=None):  # noqa: ANN001
        self.neo4j = neo4j
        self.proposal_service = proposal_service
        self.ledger = ledger

    async def create_episode(self, episode: EpisodicMemory) -> dict:
        if self.proposal_service is not None:
            proposal = await self.proposal_service.propose_create(
                episode_to_content(episode),
                requested_by="agent",
                reason="Registro de episódio",
                idempotency_key=f"episode:{episode.episode_id}",
            )
            revision = (
                await self.ledger.get_revision(proposal.applied_revision_id)
                if proposal.applied_revision_id and self.ledger is not None
                else None
            )
            return pending_envelope(proposal, legacy_id=episode.episode_id, revision=revision)
        if self.neo4j is None:
            raise MemoryServiceError("Serviço episódico sem ledger ou Neo4j")
        query = """
            CREATE (e:EpisodicMemory {episode_id: $episode_id})
            SET e.project = $project,
                e.task_description = $task_description,
                e.approach = $approach,
                e.outcome = $outcome,
                e.lessons = $lessons,
                e.tags = $tags,
                e.created_at = timestamp(),
                e.updated_at = timestamp()
            WITH e
            MATCH (p:Project {name: $project})
            MERGE (e)-[:IN_PROJECT]->(p)
        """
        try:
            async with self.neo4j.driver.session() as session:
                await session.run(
                    query,
                    episode_id=episode.episode_id,
                    project=episode.project,
                    task_description=episode.task_description,
                    approach=episode.approach,
                    outcome=episode.outcome.value,
                    lessons=episode.lessons,
                    tags=episode.tags,
                )
                for mid in episode.related_memory_ids:
                    await session.run(
                        """
                        MATCH (e:EpisodicMemory {episode_id: $episode_id})
                        MATCH (m:MemoryItem {memory_id: $memory_id})
                        CREATE (e)-[:LEARNED_FROM]->(m)
                        """,
                        episode_id=episode.episode_id,
                        memory_id=mid,
                    )
            return {"episode_id": episode.episode_id, "status": "created"}
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao criar episodio: {error}",
                context={"episode_id": episode.episode_id},
            ) from error

    async def query_episodes(
        self,
        project: str,
        outcome: str | None = None,
        tag: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        if self.ledger is not None:
            revisions = await self.ledger.list_effective_revisions(
                project=project,
                memory_scope=MemoryScope.EPISODIC,
                memory_branch="episodic",
            )
            rows = []
            for revision in reversed(revisions):
                row = hydrate_legacy(revision)
                if outcome is not None and row.get("outcome") != outcome:
                    continue
                if tag is not None and tag not in row.get("tags", []):
                    continue
                rows.append(row)
            return rows[:limit]
        if self.neo4j is None:
            raise MemoryServiceError("Serviço episódico sem ledger ou Neo4j")
        query = """
            MATCH (e:EpisodicMemory)-[:IN_PROJECT]->(:Project {name: $project})
            WHERE ($outcome IS NULL OR e.outcome = $outcome)
              AND ($tag IS NULL OR $tag IN e.tags)
            RETURN e { .* } AS episode
            ORDER BY e.created_at DESC
            LIMIT $limit
        """
        try:
            async with self.neo4j.driver.session() as session:
                result = await session.run(
                    query, project=project, outcome=outcome, tag=tag, limit=limit
                )
                return [record["episode"] async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao consultar episodios: {error}",
                context={"project": project},
            ) from error
