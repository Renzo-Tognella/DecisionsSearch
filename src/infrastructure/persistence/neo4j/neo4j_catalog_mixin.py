from __future__ import annotations

from decisionssearch.domain.catalog.catalog_nodes import CategoryNode, DomainNode, ProjectNode
from decisionssearch.domain.shared.exceptions import MemoryServiceError


class Neo4jCatalogMixin:
    VALID_CATALOG_RELATIONSHIPS = {
        "HAS_CATEGORY",
        "HAS_DOMAIN",
        "RELATED_TO",
        "DEPENDS_ON",
        "REFINES",
        "DEPRECATES",
        "CONFLICTS_WITH",
        "EVOLVES_FROM",
    }

    CATALOG_NODE_LABELS = {
        "project": "Project",
        "category": "Category",
        "domain": "Domain",
    }

    def _catalog_label(self, kind: str) -> str:
        normalized = kind.strip().lower()
        try:
            return self.CATALOG_NODE_LABELS[normalized]
        except KeyError as error:
            raise MemoryServiceError(
                "Tipo de no catalogo invalido",
                context={"kind": kind},
            ) from error

    def _catalog_node_payload(self, node: ProjectNode | CategoryNode | DomainNode) -> dict:
        payload = node.model_dump(mode="json")
        payload["aliases"] = list(payload.get("aliases", []))
        payload["tags"] = list(payload.get("tags", []))
        return payload

    @staticmethod
    def _catalog_select_fields(include_project_id: bool = False) -> str:
        fields = [
            "n.id AS id",
            "n.slug AS slug",
            "n.name AS name",
            "n.description AS description",
            "n.status AS status",
            "n.aliases AS aliases",
            "n.tags AS tags",
        ]
        if include_project_id:
            fields.append("n.project_id AS project_id")
        return ", ".join(fields)

    @staticmethod
    def _identity_where_clause(alias: str, prefix: str) -> str:
        return (
            f"{alias}.id = ${prefix}_id OR "
            f"{alias}.name = ${prefix}_name OR "
            f"{alias}.slug = ${prefix}_slug"
        )

    async def _resolve_catalog_node(
        self,
        session,
        label: str,
        identity: dict[str, str],
    ) -> dict | None:
        params = {f"identity_{field}": value for field, value in identity.items()}
        query = f"""
            MATCH (n:{label})
            WHERE {self._identity_where_clause("n", "identity")}
            RETURN {self._catalog_select_fields(include_project_id=(label != "Project"))}
            LIMIT 1
        """
        result = await session.run(query, **params)
        record = await result.single()
        return record.data() if record else None

    @staticmethod
    def _identity_params(prefix: str, identity: dict[str, str]) -> dict[str, str]:
        return {f"{prefix}_{field}": value for field, value in identity.items()}

    async def _resolve_identity(self, session, label: str, identity: dict[str, str]) -> dict | None:
        query = f"""
            MATCH (n:{label})
            WHERE {self._identity_where_clause("n", "identity")}
            RETURN {self._catalog_select_fields(include_project_id=(label != "Project"))}
            LIMIT 1
        """
        result = await session.run(query, **self._identity_params("identity", identity))
        record = await result.single()
        return record.data() if record else None

    async def _upsert_catalog_node(
        self,
        session,
        label: str,
        payload: dict,
    ) -> None:
        identity = {
            "id": payload["id"],
            "name": payload["name"],
            "slug": payload["slug"],
        }
        set_parts = [
            "n.id = coalesce(n.id, $identity_id)",
            "n.slug = $identity_slug",
            "n.name = $identity_name",
            "n.description = $description",
            "n.status = $status",
            "n.aliases = $aliases",
            "n.tags = $tags",
            "n.updated_at = timestamp()",
        ]
        if "project_id" in payload:
            set_parts.append("n.project_id = $project_id")
        query = f"""
            MATCH (n:{label})
            WHERE {self._identity_where_clause("n", "identity")}
            SET {", ".join(set_parts)}
            RETURN {self._catalog_select_fields(include_project_id=("project_id" in payload))}
        """
        params = self._identity_params("identity", identity)
        params.update(
            {
                "description": payload["description"],
                "status": payload["status"],
                "aliases": payload["aliases"],
                "tags": payload["tags"],
            }
        )
        if "project_id" in payload:
            params["project_id"] = payload["project_id"]
        result = await session.run(query, **params)
        record = await result.single()
        if not record:
            raise MemoryServiceError(
                "Falha ao atualizar no estruturural do catalogo",
                context={"label": label, "id": payload["id"]},
            )

    async def _create_catalog_node(
        self,
        session,
        label: str,
        payload: dict,
    ) -> None:
        identity = {
            "id": payload["id"],
            "name": payload["name"],
            "slug": payload["slug"],
        }
        set_parts = [
            "n.id = coalesce(n.id, $identity_id)",
            "n.slug = $identity_slug",
            "n.description = $description",
            "n.status = $status",
            "n.aliases = $aliases",
            "n.tags = $tags",
            "n.updated_at = timestamp()",
        ]
        if "project_id" in payload:
            set_parts.append("n.project_id = $project_id")
        query = f"""
            MERGE (n:{label} {{name: $name}})
            SET {", ".join(set_parts)}
            RETURN {self._catalog_select_fields(include_project_id=("project_id" in payload))}
        """
        params = self._identity_params("identity", identity)
        params.update(
            {
                "name": payload["name"],
                "description": payload["description"],
                "status": payload["status"],
                "aliases": payload["aliases"],
                "tags": payload["tags"],
            }
        )
        if "project_id" in payload:
            params["project_id"] = payload["project_id"]
        result = await session.run(query, **params)
        record = await result.single()
        if not record:
            raise MemoryServiceError(
                "Falha ao criar no estruturural do catalogo",
                context={"label": label, "id": payload["id"]},
            )

    async def _resolve_required_project(self, session, project_id: str) -> dict:
        identity = {"id": project_id, "name": project_id, "slug": project_id}
        project = await self._resolve_catalog_node(session, "Project", identity)
        if not project:
            raise MemoryServiceError(
                "Projeto pai nao encontrado para o catalogo",
                context={"project_id": project_id},
            )
        return project

    async def upsert_project_node(self, node: ProjectNode) -> None:
        payload = self._catalog_node_payload(node)
        try:
            async with self.driver.session() as session:
                identity = {"id": node.id, "name": node.name, "slug": node.slug}
                existing = await self._resolve_catalog_node(session, "Project", identity)
                if existing:
                    await self._upsert_catalog_node(session, "Project", payload)
                else:
                    await self._create_catalog_node(session, "Project", payload)
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao persistir projeto no Neo4j: {error}",
                context={"id": node.id, "slug": node.slug},
            ) from error

    async def upsert_category_node(self, node: CategoryNode) -> None:
        payload = self._catalog_node_payload(node)
        try:
            async with self.driver.session() as session:
                await self._resolve_required_project(session, node.project_id)
                identity = {"id": node.id, "name": node.name, "slug": node.slug}
                existing = await self._resolve_catalog_node(session, "Category", identity)
                if existing:
                    await self._upsert_catalog_node(session, "Category", payload)
                else:
                    await self._create_catalog_node(session, "Category", payload)
                relation_query = """
                    MATCH (p:Project)
                    WHERE p.id = $project_identity
                       OR p.name = $project_identity
                       OR p.slug = $project_identity
                    MATCH (c:Category)
                    WHERE c.id = $category_id
                       OR c.name = $category_name
                       OR c.slug = $category_slug
                    MERGE (p)-[:HAS_CATEGORY]->(c)
                    RETURN 1 AS linked
                """
                result = await session.run(
                    relation_query,
                    project_identity=node.project_id,
                    category_id=node.id,
                    category_name=node.name,
                    category_slug=node.slug,
                )
                if not await result.single():
                    raise MemoryServiceError(
                        "Falha ao vincular categoria ao projeto no Neo4j",
                        context={"id": node.id, "project_id": node.project_id},
                    )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao persistir categoria no Neo4j: {error}",
                context={"id": node.id, "project_id": node.project_id},
            ) from error

    async def upsert_domain_node(self, node: DomainNode) -> None:
        payload = self._catalog_node_payload(node)
        try:
            async with self.driver.session() as session:
                await self._resolve_required_project(session, node.project_id)
                identity = {"id": node.id, "name": node.name, "slug": node.slug}
                existing = await self._resolve_catalog_node(session, "Domain", identity)
                if existing:
                    await self._upsert_catalog_node(session, "Domain", payload)
                else:
                    await self._create_catalog_node(session, "Domain", payload)
                relation_query = """
                    MATCH (p:Project)
                    WHERE p.id = $project_identity
                       OR p.name = $project_identity
                       OR p.slug = $project_identity
                    MATCH (d:Domain)
                    WHERE d.id = $domain_id
                       OR d.name = $domain_name
                       OR d.slug = $domain_slug
                    MERGE (p)-[:HAS_DOMAIN]->(d)
                    RETURN 1 AS linked
                """
                result = await session.run(
                    relation_query,
                    project_identity=node.project_id,
                    domain_id=node.id,
                    domain_name=node.name,
                    domain_slug=node.slug,
                )
                if not await result.single():
                    raise MemoryServiceError(
                        "Falha ao vincular dominio ao projeto no Neo4j",
                        context={"id": node.id, "project_id": node.project_id},
                    )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao persistir dominio no Neo4j: {error}",
                context={"id": node.id, "project_id": node.project_id},
            ) from error

    async def list_project_nodes(self) -> list[dict]:
        query = """
            MATCH (p:Project)
            RETURN p.id AS id,
                   p.slug AS slug,
                   p.name AS name,
                   p.description AS description,
                   p.status AS status,
                   p.aliases AS aliases,
                   p.tags AS tags
            ORDER BY p.name
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query)
                return [record.data() async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao listar projetos do catalogo no Neo4j: {error}",
            ) from error

    async def list_category_nodes(self) -> list[dict]:
        query = """
            MATCH (c:Category)
            RETURN c.id AS id,
                   c.slug AS slug,
                   c.name AS name,
                   c.description AS description,
                   c.status AS status,
                   c.aliases AS aliases,
                   c.tags AS tags,
                   c.project_id AS project_id
            ORDER BY c.name
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query)
                return [record.data() async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao listar categorias do catalogo no Neo4j: {error}",
            ) from error

    async def list_domain_nodes(self) -> list[dict]:
        query = """
            MATCH (d:Domain)
            RETURN d.id AS id,
                   d.slug AS slug,
                   d.name AS name,
                   d.description AS description,
                   d.status AS status,
                   d.aliases AS aliases,
                   d.tags AS tags,
                   d.project_id AS project_id
            ORDER BY d.name
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(query)
                return [record.data() async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao listar dominios do catalogo no Neo4j: {error}",
            ) from error

    async def delete_catalog_node(self, node_id: str, kind: str) -> None:
        label = self._catalog_label(kind)
        query = f"""
            MATCH (n:{label})
            WHERE n.id = $node_id OR n.name = $node_id OR n.slug = $node_id
            OPTIONAL MATCH (n)-[r]-()
            WITH n,
                 collect(DISTINCT type(r)) AS relation_types,
                 sum(
                     CASE
                         WHEN r IS NULL THEN 0
                         WHEN 'MemoryItem' IN labels(
                           CASE WHEN startNode(r) = n
                             THEN endNode(r)
                             ELSE startNode(r) END)
                         THEN 1
                         ELSE 0
                     END
                 ) AS memory_edges
            WITH n, relation_types, coalesce(memory_edges, 0) AS memory_edges
            WHERE size([rt IN relation_types
              WHERE rt IS NOT NULL AND rt <> ''
              AND NOT rt IN $allowed_relations]) = 0
              AND memory_edges = 0
            DETACH DELETE n
            RETURN 1 AS deleted
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    node_id=node_id,
                    allowed_relations=sorted(self.VALID_CATALOG_RELATIONSHIPS),
                )
                if not await result.single():
                    raise MemoryServiceError(
                        "No catalogo nao pode ser removido com relacoes inseguras",
                        context={"node_id": node_id, "kind": kind},
                    )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao remover no do catalogo no Neo4j: {error}",
                context={"node_id": node_id, "kind": kind},
            ) from error

    async def create_catalog_relation(
        self,
        source_id: str,
        source_kind: str,
        relation_type: str,
        target_id: str,
        target_kind: str,
        rationale: str = "",
    ) -> None:
        if relation_type not in self.VALID_CATALOG_RELATIONSHIPS:
            raise MemoryServiceError(
                "Relacao invalida para catalogo",
                context={
                    "source_id": source_id,
                    "source_kind": source_kind,
                    "relation_type": relation_type,
                    "target_id": target_id,
                    "target_kind": target_kind,
                },
            )

        source_label = self._catalog_label(source_kind)
        target_label = self._catalog_label(target_kind)
        query = f"""
            MATCH (a:{source_label})
            WHERE a.id = $source_identity OR a.name = $source_identity OR a.slug = $source_identity
            MATCH (b:{target_label})
            WHERE b.id = $target_identity OR b.name = $target_identity OR b.slug = $target_identity
            MERGE (a)-[r:`{relation_type}`]->(b)
            SET r.rationale = $rationale
            RETURN 1 AS created
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    source_identity=source_id,
                    target_identity=target_id,
                    relation_type=relation_type,
                    rationale=rationale,
                )
                if not await result.single():
                    raise MemoryServiceError(
                        "Relacao do catalogo nao pode ser criada sem origem e destino validos",
                        context={
                            "source_id": source_id,
                            "source_kind": source_kind,
                            "relation_type": relation_type,
                            "target_id": target_id,
                            "target_kind": target_kind,
                        },
                    )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao criar relacao do catalogo no Neo4j: {error}",
                context={
                    "source_id": source_id,
                    "source_kind": source_kind,
                    "relation_type": relation_type,
                    "target_id": target_id,
                    "target_kind": target_kind,
                },
            ) from error

    async def delete_catalog_relation(
        self,
        source_id: str,
        source_kind: str,
        relation_type: str,
        target_id: str,
        target_kind: str,
    ) -> None:
        if relation_type not in self.VALID_CATALOG_RELATIONSHIPS:
            raise MemoryServiceError(
                "Relacao invalida para catalogo",
                context={
                    "source_id": source_id,
                    "source_kind": source_kind,
                    "relation_type": relation_type,
                    "target_id": target_id,
                    "target_kind": target_kind,
                },
            )

        source_label = self._catalog_label(source_kind)
        target_label = self._catalog_label(target_kind)
        query = f"""
            MATCH (a:{source_label})
            WHERE a.id = $source_identity OR a.name = $source_identity OR a.slug = $source_identity
            MATCH (b:{target_label})
            WHERE b.id = $target_identity OR b.name = $target_identity OR b.slug = $target_identity
            MATCH (a)-[r:`{relation_type}`]->(b)
            DELETE r
            RETURN 1 AS deleted
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    source_identity=source_id,
                    target_identity=target_id,
                    relation_type=relation_type,
                )
                if not await result.single():
                    raise MemoryServiceError(
                        "Relacao do catalogo nao encontrada para remocao",
                        context={
                            "source_id": source_id,
                            "source_kind": source_kind,
                            "relation_type": relation_type,
                            "target_id": target_id,
                            "target_kind": target_kind,
                        },
                    )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao remover relacao do catalogo no Neo4j: {error}",
                context={
                    "source_id": source_id,
                    "source_kind": source_kind,
                    "relation_type": relation_type,
                    "target_id": target_id,
                    "target_kind": target_kind,
                },
            ) from error

    async def list_allowed_relations(self) -> list[str]:
        return sorted(self.VALID_CATALOG_RELATIONSHIPS)

    async def list_catalog_relations(self) -> list[dict]:
        query = """
            MATCH (a)-[r]->(b)
            WHERE any(label IN labels(a) WHERE label IN ['Project', 'Category', 'Domain'])
              AND any(label IN labels(b) WHERE label IN ['Project', 'Category', 'Domain'])
              AND type(r) IN $allowed_relations
            RETURN coalesce(a.id, a.slug, a.name) AS source_id,
                   toLower(head(labels(a))) AS source_kind,
                   type(r) AS relation_type,
                   coalesce(b.id, b.slug, b.name) AS target_id,
                   toLower(head(labels(b))) AS target_kind,
                   coalesce(r.rationale, '') AS rationale
            ORDER BY source_kind, source_id, relation_type, target_kind, target_id
        """
        try:
            async with self.driver.session() as session:
                result = await session.run(
                    query,
                    allowed_relations=sorted(self.VALID_CATALOG_RELATIONSHIPS),
                )
                return [record.data() async for record in result]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao listar relacoes do catalogo no Neo4j: {error}",
            ) from error
