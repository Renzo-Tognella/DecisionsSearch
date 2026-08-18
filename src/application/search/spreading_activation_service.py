from __future__ import annotations

from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.domain.memory_ledger import RelationState, legacy_memory_id_for_family


class SpreadingActivationService:
    TRAVERSABLE_RELATIONS = frozenset(
        {"RELATED_TO", "DEPENDS_ON", "REFINES", "EVOLVES_FROM"}
    )

    def __init__(self, neo4j: Neo4jService, decay: float = 0.5, max_depth: int = 2, ledger=None):  # noqa: ANN001
        self.neo4j = neo4j
        self.decay = decay
        self.max_depth = max_depth
        self.ledger = ledger

    async def activate(self, seed_ids: list[str], project: str, top_k: int = 20) -> list[str]:
        if not seed_ids:
            return []
        if self.ledger is not None:
            return await self._activate_ledger(seed_ids, project, top_k)
        scores: dict[str, float] = {mid: 1.0 for mid in seed_ids}
        frontier = list(seed_ids)
        for _ in range(self.max_depth):
            next_frontier: list[str] = []
            neighbors = await self._fetch_neighbors(frontier, project)
            for source_id, neighbor_list in neighbors.items():
                source_score = scores.get(source_id, 0.0)
                for neighbor_id in neighbor_list:
                    propagated = source_score * self.decay
                    if propagated > scores.get(neighbor_id, 0.0):
                        scores[neighbor_id] = propagated
                    if neighbor_id not in scores or propagated > 0.1:
                        next_frontier.append(neighbor_id)
            frontier = list(set(next_frontier))
            if not frontier:
                break
        ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
        return [mid for mid, score in ranked[:top_k] if score > 0.05]

    async def _activate_ledger(self, seed_ids: list[str], project: str, top_k: int) -> list[str]:
        family_by_id = {}
        for memory_id in seed_ids:
            alias = await self.ledger.resolve_alias(memory_id)
            if alias is not None and alias.family_id is not None:
                family_by_id[memory_id] = alias.family_id
        if not family_by_id:
            return []
        scores = {family_id: 1.0 for family_id in family_by_id.values()}
        frontier = set(scores)
        for _ in range(self.max_depth):
            next_frontier: set = set()
            for relation in await self.ledger.list_relations(state=RelationState.ACTIVE):
                if relation.relation_type not in self.TRAVERSABLE_RELATIONS:
                    # DEPRECATES/MERGED_INTO/CONFLICTS_WITH são lineage ou
                    # governança; não devem reintroduzir conhecimento obsoleto
                    # no contexto semântico por ativação espalhada.
                    continue
                if relation.source_family_id not in frontier and relation.target_family_id not in frontier:
                    continue
                source = relation.source_family_id
                target = relation.target_family_id
                neighbor = target if source in frontier else source
                family = await self.ledger.get_family(neighbor)
                if family is None or family.project != project:
                    continue
                propagated = scores.get(source if source in frontier else target, 0.0) * self.decay
                if propagated > scores.get(neighbor, 0.0):
                    scores[neighbor] = propagated
                if propagated > 0.1:
                    next_frontier.add(neighbor)
            frontier = next_frontier
            if not frontier:
                break
        ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
        result = []
        for family_id, score in ranked:
            if score <= 0.05:
                continue
            family = await self.ledger.get_family(family_id)
            if family is not None:
                result.append(family.legacy_memory_id or legacy_memory_id_for_family(family_id))
            if len(result) >= top_k:
                break
        return result

    async def _fetch_neighbors(self, node_ids: list[str], project: str) -> dict[str, list[str]]:
        if not node_ids:
            return {}
        query = """
            MATCH (m:MemoryItem)-[:IN_PROJECT]->(:Project {name: $project})
            WHERE m.memory_id IN $ids AND m.status = 'active'
            MATCH (m)-[r]-(neighbor:MemoryItem)
            WHERE neighbor.status = 'active'
            AND type(r) IN ['RELATED_TO','DEPENDS_ON','REFINES','EVOLVES_FROM']
            RETURN m.memory_id AS source, collect(DISTINCT neighbor.memory_id) AS neighbors
        """
        try:
            async with self.neo4j.driver.session() as session:
                result = await session.run(query, project=project, ids=node_ids)
                records = [record.data() async for record in result]
                return {r["source"]: r["neighbors"] for r in records if r.get("source")}
        except Exception:
            return {}
