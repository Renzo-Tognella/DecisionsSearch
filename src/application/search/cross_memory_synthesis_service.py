from __future__ import annotations

import hashlib
import logging

from decisionssearch.application.shared.jaro_winkler import jaro_winkler
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService

logger = logging.getLogger(__name__)


class CrossMemorySynthesisService:
    def __init__(self, neo4j: Neo4jService, similarity_threshold: float = 0.75):
        self.neo4j = neo4j
        self.similarity_threshold = similarity_threshold

    async def find_clusters(self, project: str, min_cluster_size: int = 2) -> list[dict]:
        rows = await self.neo4j.query_by_project(project=project, status="active", limit=500)
        memories = [row.get("memory", {}) for row in rows if row.get("memory")]
        clusters = self._cluster_by_title_similarity(memories)
        return [
            {
                "cluster_id": hashlib.md5(
                    "|".join(sorted(m.get("memory_id", "") for m in cluster)).encode()
                ).hexdigest()[:12],
                "size": len(cluster),
                "titles": [m.get("title", "") for m in cluster],
                "memory_ids": [m.get("memory_id", "") for m in cluster],
                "avg_weight": sum(float(m.get("effective_weight", 0.0)) for m in cluster)
                / len(cluster),
            }
            for cluster in clusters
            if len(cluster) >= min_cluster_size
        ]

    def _cluster_by_title_similarity(self, memories: list[dict]) -> list[list[dict]]:
        clusters: list[list[dict]] = []
        assigned: set[int] = set()
        for i, mem in enumerate(memories):
            if i in assigned:
                continue
            cluster = [mem]
            assigned.add(i)
            for j, other in enumerate(memories):
                if j in assigned or j == i:
                    continue
                score = jaro_winkler(
                    str(mem.get("title", "")).lower(),
                    str(other.get("title", "")).lower(),
                )
                if score >= self.similarity_threshold:
                    cluster.append(other)
                    assigned.add(j)
            clusters.append(cluster)
        return clusters

    async def synthesize_cluster(self, cluster: dict, project: str) -> dict:
        return {
            "cluster_id": cluster.get("cluster_id", ""),
            "synthesis": f"Cluster with {cluster.get('size', 0)} memories",
            "themes": cluster.get("titles", [])[:3],
            "recommendation": "Consider merging related memories via consolidation",
        }
