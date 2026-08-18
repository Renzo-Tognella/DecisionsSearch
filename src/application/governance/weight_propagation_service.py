from __future__ import annotations

import logging

from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService

logger = logging.getLogger(__name__)


class WeightPropagationService:
    RELATIONSHIP_TYPES = ["RELATED_TO", "DEPENDS_ON", "REFINES", "EVOLVES_FROM"]
    ITERATIONS = 3
    DAMPING = 0.85

    def __init__(self, neo4j: Neo4jService):
        self.neo4j = neo4j

    async def propagate_weights(self, project: str) -> dict:
        rel_pattern = "|".join(self.RELATIONSHIP_TYPES)
        total_updates = 0
        try:
            async with self.neo4j.driver.session() as session:
                for _ in range(self.ITERATIONS):
                    query = f"""
                        MATCH (m:MemoryItem)-[:IN_PROJECT]->(:Project {{name: $project}})
                        WHERE m.status = 'active'
                        OPTIONAL MATCH (m)-[r:`{rel_pattern}`]-(neighbor:MemoryItem)
                        WHERE neighbor.status = 'active'
                        WITH m, coalesce(avg(neighbor.effective_weight), 0) AS neighbor_avg
                        WITH m, m.effective_weight AS current,
                             $damping * neighbor_avg
                             + (1 - $damping) * coalesce(m.effective_weight, 0.5)
                             AS propagated
                        WHERE abs(propagated - current) > 0.001
                        SET m.propagated_weight = round(propagated, 4)
                        RETURN count(m) AS updated
                    """
                    result = await session.run(query, project=project, damping=self.DAMPING)
                    record = await result.single()
                    updated = int(record["updated"]) if record else 0
                    total_updates += updated
            return {
                "project": project,
                "iterations": self.ITERATIONS,
                "total_updates": total_updates,
            }
        except Exception as error:
            logger.warning("Weight propagation failed: %s", error)
            return {"project": project, "iterations": 0, "total_updates": 0, "error": str(error)}

    async def get_top_propagated(self, project: str, limit: int = 10) -> list[dict]:
        query = """
            MATCH (m:MemoryItem)-[:IN_PROJECT]->(:Project {name: $project})
            WHERE m.status = 'active' AND m.propagated_weight IS NOT NULL
            RETURN m.memory_id AS memory_id,
                   m.title AS title,
                   m.effective_weight AS original_weight,
                   m.propagated_weight AS propagated_weight
            ORDER BY m.propagated_weight DESC
            LIMIT $limit
        """
        try:
            async with self.neo4j.driver.session() as session:
                result = await session.run(query, project=project, limit=limit)
                return [record.data() async for record in result]
        except Exception:
            return []
