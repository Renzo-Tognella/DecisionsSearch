from __future__ import annotations

import os
from datetime import datetime

try:
    from neo4j import AsyncGraphDatabase
except Exception:  # pragma: no cover

    class AsyncGraphDatabase:  # type: ignore[override]
        @staticmethod
        def driver(*args, **kwargs):  # noqa: ANN002,ANN003,ANN201
            raise RuntimeError("neo4j driver indisponível no ambiente atual")


from decisionssearch.domain.shared.exceptions import BootstrapError, MemoryServiceError
from decisionssearch.application.ports.abstractions import GraphStore
from decisionssearch.infrastructure.persistence.neo4j.neo4j_catalog_mixin import Neo4jCatalogMixin
from decisionssearch.infrastructure.persistence.neo4j.neo4j_pr_memory_mixin import Neo4jPRMemoryMixin


class Neo4jService(Neo4jCatalogMixin, Neo4jPRMemoryMixin, GraphStore):
    VALID_RELATIONSHIPS = {
        "RELATED_TO",
        "DEPENDS_ON",
        "REFINES",
        "DEPRECATES",
        "CONFLICTS_WITH",
        "EVOLVES_FROM",
    }

    def __init__(self, *, legacy_memory_writes_allowed: bool = True):
        # Compatibilidade permanece disponível para testes/integrações antigas,
        # mas o container oficial desliga esse caminho e usa o MemoryLedger.
        self.legacy_memory_writes_allowed = legacy_memory_writes_allowed
        self.driver = AsyncGraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(
                os.getenv("NEO4J_USER", "neo4j"),
                os.getenv("NEO4J_PASSWORD", ""),
            ),
        )

    def _assert_legacy_memory_write_allowed(self) -> None:
        if not self.legacy_memory_writes_allowed:
            raise MemoryServiceError(
                "Escrita direta de MemoryItem está bloqueada; use uma proposta do ledger versionado."
            )

    async def close(self) -> None:
        await self.driver.close()

    async def execute_write(self, query: str, **params) -> list[dict]:
        async with self.driver.session() as session:
            result = await session.run(query, **params)
            return [record.data() async for record in result]

    async def execute_write_transaction(self, work):  # noqa: ANN001
        """Executa várias mutações em uma transação gerenciada pelo driver.

        O método existe para o ledger versionado. ``execute_write`` continua
        disponível para consultas legadas, mas não deve ser usado para compor uma
        aplicação de revisão em várias chamadas independentes.
        """

        async with self.driver.session() as session:
            return await session.execute_write(work)

    async def execute_read(self, query: str, **params) -> list[dict]:
        async with self.driver.session() as session:
            result = await session.run(query, **params)
            return [record.data() async for record in result]

    async def bootstrap(self, projects: list[str], domains: list[str] | None = None) -> None:
        categories = [
            "FeatureDescription",
            "BusinessRule",
            "DesignPattern",
            "DesignRule",
            "ArchitecturalDecision",
        ]

        try:
            async with self.driver.session() as session:
                for project in projects:
                    await session.run("MERGE (p:Project {name: $name})", name=project)
                    for category in categories:
                        await session.run(
                            """
                            MERGE (p:Project {name: $project})
                            MERGE (c:Category {name: $category})
                            MERGE (p)-[:HAS_CATEGORY]->(c)
                            """,
                            project=project,
                            category=category,
                        )

                if domains:
                    for domain in domains:
                        await session.run("MERGE (d:Domain {name: $name})", name=domain)
        except Exception as error:
            raise BootstrapError(
                "Falha no bootstrap do Neo4j",
                context={"projects": projects, "domains": domains or []},
            ) from error

    async def query_at_point_in_time(
        self,
        project: str,
        point_in_time: datetime,
        category: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        query = """
            MATCH (m:MemoryItem)-[:IN_PROJECT]->(:Project {name: $project})
            WHERE m.status IN ['active', 'deprecated']
              AND m.valid_at <= $point_in_time
              AND (m.invalid_at IS NULL OR m.invalid_at > $point_in_time)
        """
        if category:
            query += "\nMATCH (m)-[:IN_CATEGORY]->(:Category {name: $category})\n"
        query += """
            OPTIONAL MATCH (m)-[related_rel]-(related:MemoryItem)
            WHERE type(related_rel) = 'RELATED_TO'
            RETURN m { .* } AS memory, collect(DISTINCT related.title) AS related_titles
            ORDER BY memory.effective_weight DESC
            LIMIT $limit
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    project=project,
                    category=category,
                    point_in_time=point_in_time.isoformat(),
                    limit=limit,
                )
                return [record.data() async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha na consulta bi-temporal no Neo4j: {error}",
                context={
                    "project": project,
                    "point_in_time": str(point_in_time),
                    "category": category,
                },
            ) from error

    async def upsert_memory(
        self,
        memory_id: str,
        project: str,
        category: str,
        domains: list[str],
        title: str,
        summary: str,
        details: str,
        status: str,
        weight: float,
        objective: str = "",
        trigger: str = "",
        stakeholders: list[str] | None = None,
        action_triggers: list[str] | None = None,
        related_files: list[str] | None = None,
        business_rules: list[str] | None = None,
        architectural_rationale: str = "",
        modules: list[str] | None = None,
        examples: list[str] | None = None,
        alternatives_considered: list[str] | None = None,
        event_date: str = "",
    ) -> None:
        self._assert_legacy_memory_write_allowed()
        try:
            async with self.driver.session() as session:
                await session.run(
                    """
                    MERGE (m:MemoryItem {memory_id: $memory_id})
                    ON CREATE SET m.title=$title, m.summary=$summary, m.details=$details,
                                  m.objective=$objective, m.trigger=$trigger,
                                  m.stakeholders=$stakeholders, m.action_triggers=$action_triggers,
                                  m.related_files=$related_files, m.business_rules=$business_rules,
                                  m.architectural_rationale=$architectural_rationale,
                                  m.status=$status, m.effective_weight=$weight,
                                  m.examples=$examples,
                                  m.alternatives_considered=$alternatives_considered,
                                  m.event_date=$event_date,
                                  m.created_at=timestamp(), m.updated_at=timestamp()
                    ON MATCH SET  m.title=$title, m.summary=$summary, m.details=$details,
                                  m.objective=$objective, m.trigger=$trigger,
                                  m.stakeholders=$stakeholders, m.action_triggers=$action_triggers,
                                  m.related_files=$related_files, m.business_rules=$business_rules,
                                  m.architectural_rationale=$architectural_rationale,
                                  m.status=$status, m.effective_weight=$weight,
                                  m.examples=$examples,
                                  m.alternatives_considered=$alternatives_considered,
                                  m.event_date=$event_date,
                                  m.updated_at=timestamp()
                    WITH m
                    MERGE (p:Project {name: $project})
                    MERGE (m)-[:IN_PROJECT]->(p)
                    WITH m
                    MERGE (c:Category {name: $category})
                    MERGE (m)-[:IN_CATEGORY]->(c)
                    """,
                    memory_id=memory_id,
                    project=project,
                    category=category,
                    title=title,
                    summary=summary,
                    details=details,
                    objective=objective,
                    trigger=trigger,
                    stakeholders=stakeholders or [],
                    action_triggers=action_triggers or [],
                    related_files=related_files or [],
                    business_rules=business_rules or [],
                    architectural_rationale=architectural_rationale,
                    status=status,
                    weight=weight,
                    examples=examples or [],
                    alternatives_considered=alternatives_considered or [],
                    event_date=event_date,
                )

                for domain in domains:
                    await session.run(
                        """
                        MATCH (m:MemoryItem {memory_id: $memory_id})
                        MERGE (d:Domain {name: $domain})
                        MERGE (m)-[:ABOUT_DOMAIN]->(d)
                        """,
                        memory_id=memory_id,
                        domain=domain,
                    )

                for module in (modules or []):
                    await session.run(
                        """
                        MATCH (m:MemoryItem {memory_id: $memory_id})
                        MERGE (mod:Module {name: $module})
                        MERGE (m)-[:AFFECTS_MODULE]->(mod)
                        """,
                        memory_id=memory_id,
                        module=module,
                    )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha no upsert de memória no Neo4j: {error}",
                context={"memory_id": memory_id, "project": project, "category": category},
            ) from error

    async def link_memories(self, from_id: str, rel_type: str, to_id: str) -> None:
        self._assert_legacy_memory_write_allowed()
        if rel_type not in self.VALID_RELATIONSHIPS:
            raise MemoryServiceError(
                "Relação inválida para linkagem",
                context={"from_id": from_id, "to_id": to_id, "rel_type": rel_type},
            )

        relationship_clause = f"MERGE (a)-[:`{rel_type}`]->(b)"
        query = (
            "MATCH (a:MemoryItem {memory_id: $from_id}) "
            "MATCH (b:MemoryItem {memory_id: $to_id}) "
            f"{relationship_clause}"
        )

        try:
            async with self.driver.session() as session:
                await session.run(query, from_id=from_id, to_id=to_id)
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao criar relação no Neo4j: {error}",
                context={"from_id": from_id, "to_id": to_id, "rel_type": rel_type},
            ) from error

    async def query_by_project(
        self,
        project: str,
        category: str | None = None,
        status: str = "active",
        limit: int = 20,
    ) -> list[dict]:
        query = """
            MATCH (m:MemoryItem)-[:IN_PROJECT]->(:Project {name: $project})
            WHERE m.status = $status
        """
        if category:
            query += "\nMATCH (m)-[:IN_CATEGORY]->(:Category {name: $category})\n"
        query += """
            OPTIONAL MATCH (m)-[related_rel]-(related:MemoryItem)
            WHERE type(related_rel) = 'RELATED_TO'
            RETURN m { .* } AS memory, collect(DISTINCT related.title) AS related_titles
            ORDER BY memory.effective_weight DESC
            LIMIT $limit
        """

        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    project=project,
                    category=category,
                    status=status,
                    limit=limit,
                )
                return [record.data() async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha na consulta por projeto no Neo4j: {error}",
                context={"project": project, "category": category, "status": status},
            ) from error

    async def list_projects(self) -> list[str]:
        query = "MATCH (p:Project) RETURN p.name AS name ORDER BY name"
        try:
            async with self.driver.session() as session:
                result = await session.run(query)
                return [record["name"] async for record in result if record.get("name")]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao listar projetos no Neo4j: {error}",
            ) from error

    async def query_by_domain(
        self,
        domain: str,
        category: str | None = None,
        status: str = "active",
        limit: int = 20,
    ) -> list[dict]:
        query = """
            MATCH (m:MemoryItem)-[:ABOUT_DOMAIN]->(:Domain {name: $domain})
            WHERE m.status = $status
        """
        if category:
            query += "\nMATCH (m)-[:IN_CATEGORY]->(:Category {name: $category})\n"
        query += """
            OPTIONAL MATCH (m)-[related_rel]-(related:MemoryItem)
            WHERE type(related_rel) = 'RELATED_TO'
            RETURN m { .* } AS memory, collect(DISTINCT related.title) AS related_titles
            ORDER BY memory.effective_weight DESC
            LIMIT $limit
        """

        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    domain=domain,
                    category=category,
                    status=status,
                    limit=limit,
                )
                return [record.data() async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha na consulta por dominio no Neo4j: {error}",
                context={"domain": domain, "category": category, "status": status},
            ) from error

    async def set_weight(
        self, memory_id: str, weight_manual: float, effective_weight: float
    ) -> None:
        self._assert_legacy_memory_write_allowed()
        query = """
            MATCH (m:MemoryItem {memory_id: $memory_id})
            SET m.weight_manual = $weight_manual,
                m.effective_weight = $effective_weight,
                m.updated_at = timestamp()
        """
        try:
            async with self.driver.session() as session:
                await session.run(
                    query,
                    memory_id=memory_id,
                    weight_manual=weight_manual,
                    effective_weight=effective_weight,
                )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao atualizar peso no Neo4j: {error}",
                context={"memory_id": memory_id},
            ) from error

    async def get_memory(self, memory_id: str) -> dict | None:
        query = """
            MATCH (m:MemoryItem {memory_id: $memory_id})
            RETURN m { .* } AS memory
            LIMIT 1
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, memory_id=memory_id)
                record = await result.single()
                return record.data()["memory"] if record else None
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao buscar memória por ID no Neo4j: {error}",
                context={"memory_id": memory_id},
            ) from error

    async def deprecate_memory(self, memory_id: str, replaced_by: str | None = None) -> None:
        self._assert_legacy_memory_write_allowed()
        try:
            async with self.driver.session() as session:
                await session.run(
                    """
                    MATCH (m:MemoryItem {memory_id: $memory_id})
                    SET m.status = 'deprecated',
                        m.invalid_at = timestamp(),
                        m.updated_at = timestamp()
                    """,
                    memory_id=memory_id,
                )
                if replaced_by:
                    await session.run(
                        """
                        MATCH (new:MemoryItem {memory_id: $new_id})
                        MATCH (old:MemoryItem {memory_id: $old_id})
                        MERGE (new)-[:DEPRECATES]->(old)
                        """,
                        new_id=replaced_by,
                        old_id=memory_id,
                    )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao deprecar memória no Neo4j: {error}",
                context={"memory_id": memory_id, "replaced_by": replaced_by},
            ) from error

    async def promote_proposed(self, min_evidence: int = 2, scope: str = "all") -> int:
        self._assert_legacy_memory_write_allowed()
        where_scope = ""
        params: dict[str, int | str] = {"min_evidence": min_evidence}
        if scope != "all":
            where_scope = "AND EXISTS { MATCH (m)-[:IN_PROJECT]->(:Project {name: $scope}) }"
            params["scope"] = scope

        query = f"""
            MATCH (m:MemoryItem)
            WHERE m.status = 'proposed'
              AND coalesce(m.evidence_count, 0) >= $min_evidence
              {where_scope}
            SET m.status = 'active', m.updated_at = timestamp()
            RETURN count(m) AS promoted
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, **params)
                record = await result.single()
                return int(record["promoted"]) if record else 0
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao promover memórias proposed: {error}",
                context={"scope": scope, "min_evidence": min_evidence},
            ) from error

    async def deprecate_low_weight(self, threshold: float = 0.1, scope: str = "all") -> int:
        self._assert_legacy_memory_write_allowed()
        where_scope = ""
        params: dict[str, float | str] = {"threshold": threshold}
        if scope != "all":
            where_scope = "AND EXISTS { MATCH (m)-[:IN_PROJECT]->(:Project {name: $scope}) }"
            params["scope"] = scope

        query = f"""
            MATCH (m:MemoryItem)
            WHERE m.status = 'active'
              AND coalesce(m.effective_weight, 0.0) < $threshold
              {where_scope}
            SET m.status = 'deprecated', m.invalid_at = timestamp(), m.updated_at = timestamp()
            RETURN count(m) AS deprecated
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query, **params)
                record = await result.single()
                return int(record["deprecated"]) if record else 0
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao deprecar memórias de baixo peso: {error}",
                context={"scope": scope, "threshold": threshold},
            ) from error
