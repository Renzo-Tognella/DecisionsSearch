from __future__ import annotations

from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService


class GraphClusteringService:
    RELATIONSHIP_TYPES = ["RELATED_TO", "DEPENDS_ON", "REFINES", "EVOLVES_FROM"]

    def __init__(self, neo4j: Neo4jService):
        self.neo4j = neo4j

    async def find_communities(self, project: str, min_size: int = 2) -> list[dict]:
        rel_pattern = "|".join(self.RELATIONSHIP_TYPES)
        query = f"""
            MATCH (m:MemoryItem)-[:IN_PROJECT]->(:Project {{name: $project}})
            WHERE m.status = 'active'
            MATCH (m)-[r:`{rel_pattern}`*1..3]-(neighbor:MemoryItem)
            WHERE neighbor.status = 'active'
            WITH collect(DISTINCT m) + collect(DISTINCT neighbor) AS all_nodes
            UNWIND range(0, size(all_nodes)-1) AS idx
            WITH all_nodes, idx
            RETURN all_nodes[idx].memory_id AS memory_id,
                   all_nodes[idx].title AS title,
                   all_nodes[idx].effective_weight AS weight
        """
        try:
            async with self.neo4j.driver.session() as session:
                result = await session.run(query, project=project)
                records = [record.data() async for record in result]
                if not records:
                    return []
                communities = self._group_by_connectivity(records)
                return [c for c in communities if len(c.get("members", [])) >= min_size]
        except Exception:
            return []

    def _group_by_connectivity(self, records: list[dict]) -> list[dict]:
        if not records:
            return []
        seen: set[str] = set()
        communities: list[dict] = []
        for record in records:
            mid = record.get("memory_id", "")
            if mid in seen:
                continue
            seen.add(mid)
            communities.append(
                {
                    "community_id": f"comm-{len(communities) + 1}",
                    "members": [
                        {
                            "memory_id": mid,
                            "title": record.get("title", ""),
                            "weight": record.get("weight", 0),
                        }
                    ],
                    "total_weight": float(record.get("weight", 0)),
                }
            )
        communities.sort(key=lambda c: c["total_weight"], reverse=True)
        return communities
