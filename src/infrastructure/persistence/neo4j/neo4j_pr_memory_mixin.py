from __future__ import annotations

from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.domain.pr_memory.pr_memory import PRMemory


class Neo4jPRMemoryMixin:
    PR_MEMORY_RELATIONS = {"IMPLEMENTS", "EVIDENCES", "MODIFIES"}

    async def upsert_pr_memory(self, memory: PRMemory) -> None:
        payload = memory.model_dump(mode="json")
        query = """
            MERGE (m:PRMemory {memory_id: $memory_id})
            SET m.project = $project,
                m.repo = $repo,
                m.pr_number = $pr_number,
                m.title = $title,
                m.summary = $summary,
                m.objective = $objective,
                m.changed_files = $changed_files,
                m.pr_url = $pr_url,
                m.branch = $branch,
                m.work_item_id = $work_item_id,
                m.work_item_url = $work_item_url,
                m.work_item_summary = $work_item_summary,
                m.work_item_provider = $work_item_provider,
                m.areas = $areas,
                m.touches_frontend = $touches_frontend,
                m.touches_backend = $touches_backend,
                m.authors = $authors,
                m.status = $status,
                m.merged_at = $merged_at,
                m.event_date = $event_date,
                m.updated_at = timestamp()
        """
        try:
            async with self.driver.session() as session:
                await session.run(query, **payload)
                for area in memory.areas:
                    await session.run(
                        """
                        MATCH (m:PRMemory {memory_id: $memory_id})
                        MERGE (a:Area {name: $area})
                        MERGE (m)-[:TOUCHES_AREA]->(a)
                        """,
                        memory_id=memory.memory_id,
                        area=area,
                    )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao persistir PR memory no Neo4j: {error}",
                context={
                    "memory_id": memory.memory_id,
                    "repo": memory.repo,
                    "pr_number": memory.pr_number,
                },
            ) from error

    async def query_pr_memories(
        self,
        project: str,
        repo: str | None = None,
        pr_number: int | None = None,
        changed_file_contains: str | None = None,
    ) -> list[dict]:
        query = """
            MATCH (m:PRMemory)
            WHERE m.project = $project
              AND ($repo IS NULL OR m.repo = $repo)
              AND ($pr_number IS NULL OR m.pr_number = $pr_number)
              AND (
                $changed_file_contains IS NULL
                OR any(path IN m.changed_files WHERE path CONTAINS $changed_file_contains)
              )
            RETURN m { .* } AS pr
            ORDER BY m.pr_number DESC
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    project=project,
                    repo=repo,
                    pr_number=pr_number,
                    changed_file_contains=changed_file_contains,
                )
                return [record["pr"] async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao consultar PR memories no Neo4j: {error}",
                context={
                    "project": project,
                    "repo": repo,
                    "pr_number": pr_number,
                    "changed_file_contains": changed_file_contains,
                },
            ) from error

    async def find_related_pr_candidates(self, memory: PRMemory, limit: int = 3) -> list[dict]:
        query = """
            MATCH (m:PRMemory)
            WHERE m.project = $project
              AND NOT (m.memory_id = $memory_id)
            WITH m,
                 [path IN coalesce(m.changed_files, [])
                   WHERE path IN $changed_files] AS overlapping_files,
                 [area IN coalesce(m.areas, [])
                   WHERE area IN $areas] AS overlapping_areas
            WITH m,
                 overlapping_files,
                 overlapping_areas,
                 size(overlapping_files) AS file_overlap_count,
                 size(overlapping_areas) AS area_overlap_count
            WHERE file_overlap_count > 0 OR area_overlap_count > 0
            WITH m,
                 file_overlap_count,
                 area_overlap_count,
                 overlapping_files,
                 overlapping_areas,
                 (file_overlap_count * 3) + area_overlap_count AS score
            RETURN
                m.memory_id AS memory_id,
                m.repo AS repo,
                m.pr_number AS pr_number,
                m.title AS title,
                CASE
                    WHEN file_overlap_count > 0
                      AND area_overlap_count > 0
                    THEN 'shared files: '
                      + overlapping_files[0]
                      + '; shared area: '
                      + overlapping_areas[0]
                    WHEN file_overlap_count > 0
                    THEN 'shared file: ' + overlapping_files[0]
                    ELSE 'shared area: ' + overlapping_areas[0]
                END AS reason,
                CASE
                    WHEN 'frontend' IN coalesce(m.areas, [])
                      AND 'backend' IN $areas THEN 'RELATED_TO'
                    WHEN 'backend' IN coalesce(m.areas, [])
                      AND 'frontend' IN $areas THEN 'RELATED_TO'
                    ELSE 'RELATED_TO'
                END AS relation_type,
                score AS score
            ORDER BY score DESC, m.pr_number DESC
            LIMIT $limit
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    project=memory.project,
                    memory_id=memory.memory_id,
                    changed_files=memory.changed_files,
                    areas=memory.areas,
                    limit=limit,
                )
                return [record.data() async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao sugerir PR memories relacionadas no Neo4j: {error}",
                context={
                    "memory_id": memory.memory_id,
                    "repo": memory.repo,
                    "pr_number": memory.pr_number,
                },
            ) from error

    async def link_pr_to_memory(
        self,
        pr_memory_id: str,
        memory_id: str,
        relation_type: str,
        rationale: str = "",
    ) -> None:
        if relation_type not in self.PR_MEMORY_RELATIONS:
            raise MemoryServiceError(
                "Relacao invalida entre PR e MemoryItem",
                context={
                    "pr_memory_id": pr_memory_id,
                    "memory_id": memory_id,
                    "relation_type": relation_type,
                },
            )

        query = f"""
            MATCH (pr:PRMemory {{memory_id: $pr_memory_id}})
            MATCH (m:MemoryItem {{memory_id: $memory_id}})
            MERGE (pr)-[r:`{relation_type}`]->(m)
            SET r.rationale = $rationale
            RETURN 1 AS created
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    pr_memory_id=pr_memory_id,
                    memory_id=memory_id,
                    rationale=rationale,
                )
                if not await result.single():
                    raise MemoryServiceError(
                        "PR ou MemoryItem nao encontrado para linkagem",
                        context={"pr_memory_id": pr_memory_id, "memory_id": memory_id},
                    )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao linkar PR com MemoryItem no Neo4j: {error}",
                context={
                    "pr_memory_id": pr_memory_id,
                    "memory_id": memory_id,
                    "relation_type": relation_type,
                },
            ) from error

    async def query_pr_linked_memories(self, pr_memory_id: str) -> list[dict]:
        query = """
            MATCH (pr:PRMemory {memory_id: $pr_memory_id})-[r]->(m:MemoryItem)
            WHERE type(r) IN $allowed_relations
            RETURN m { .* } AS memory,
                   type(r) AS relation_type,
                   coalesce(r.rationale, '') AS rationale,
                   coalesce(m.effective_weight, 0.0) AS effective_weight
            ORDER BY m.effective_weight DESC
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    pr_memory_id=pr_memory_id,
                    allowed_relations=sorted(self.PR_MEMORY_RELATIONS),
                )
                rows = []
                async for record in result:
                    data = record.data()
                    memory = dict(data.get("memory", {}))
                    memory["relation_type"] = data.get("relation_type", "")
                    memory["rationale"] = data.get("rationale", "")
                    memory["effective_weight"] = data.get("effective_weight", 0.0)
                    rows.append(memory)
                return rows
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao consultar memorias linkadas ao PR no Neo4j: {error}",
                context={"pr_memory_id": pr_memory_id},
            ) from error

    async def query_memory_linked_prs(self, memory_id: str) -> list[dict]:
        query = """
            MATCH (pr:PRMemory)-[r]->(m:MemoryItem {memory_id: $memory_id})
            WHERE type(r) IN $allowed_relations
            RETURN pr.memory_id AS memory_id,
                   pr.repo AS repo,
                   pr.pr_number AS pr_number,
                   pr.title AS title,
                   coalesce(pr.status, 'open') AS status,
                   type(r) AS relation_type,
                   coalesce(r.rationale, '') AS rationale
            ORDER BY pr.pr_number DESC
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    memory_id=memory_id,
                    allowed_relations=sorted(self.PR_MEMORY_RELATIONS),
                )
                return [record.data() async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao consultar PRs linkados a memoria no Neo4j: {error}",
                context={"memory_id": memory_id},
            ) from error
