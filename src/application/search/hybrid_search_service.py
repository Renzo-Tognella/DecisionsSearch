from __future__ import annotations

import asyncio
import re

from decisionssearch.application.ports.abstractions import Reranker
from decisionssearch.application.memory.project_context import resolve_project
from decisionssearch.infrastructure.config.env_utils import env_float, env_int
from decisionssearch.infrastructure.ai.embeddings.embedding_service import EmbeddingService
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.infrastructure.persistence.qdrant.qdrant_service import QdrantService
from decisionssearch.domain.memory_ledger import MemoryScope, legacy_memory_id_for_family
from decisionssearch.application.memory.ledger.views import _effective_weight


class HybridSearchService:
    """Busca hibrida MVP.

    - Com query_text: busca semantica no Qdrant (com filtros).
    - Sem query_text: consulta estrutural no Neo4j.
    """

    def __init__(
        self,
        qdrant: QdrantService,
        neo4j: Neo4jService,
        embeddings: EmbeddingService,
        reranker: Reranker | None = None,
        hyde=None,
        spreading_activation=None,
        composite_scorer=None,
        query_rewriter=None,
        ledger=None,
    ):
        self.qdrant = qdrant
        self.neo4j = neo4j
        self.embeddings = embeddings
        self.reranker = reranker
        self.hyde = hyde
        self.spreading_activation = spreading_activation
        self.composite_scorer = composite_scorer
        self.query_rewriter = query_rewriter
        self.ledger = ledger
        # Hiperparâmetros de fusão (tunáveis por env, otimizáveis contra o gold set).
        self.sparse_rrf_weight = env_float("RRF_SPARSE_WEIGHT", 1.0)
        self.graph_rrf_weight = env_float("RRF_GRAPH_WEIGHT", 0.4)
        self.activation_rrf_weight = env_float("RRF_ACTIVATION_WEIGHT", 0.6)
        self.candidate_multiplier = env_int("RETRIEVAL_CANDIDATE_MULTIPLIER", 2)
        # Blend reranker×composite: o cross-encoder melhora recall mas pode piorar a
        # ordenação em queries indiretas. Em vez de reordenar puro pelo rerank_score,
        # mistura com o composite. alpha=1 => puro reranker; alpha=0 => puro composite.
        # Default 0.4: medido como ótimo no gold set difícil do ExampleProject (recall@5 0.955,
        # NDCG@5 0.824 — domina o reranker puro 0.955/0.799 em todas as métricas).
        self.rerank_blend_alpha = env_float("RERANK_BLEND_ALPHA", 0.4)

    async def search(
        self,
        query_text: str | None,
        project: str | None = None,
        category: str | None = None,
        top_k: int = 10,
        min_weight: float = 0.0,
        min_score: float = 0.0,
        use_hyde: bool = False,
        memory_scope: MemoryScope | str = MemoryScope.SEMANTIC,
        memory_branch: str | None = None,
    ) -> list[dict]:
        # Project is a mandatory partition even when the caller omits it. This
        # prevents a semantic or graph search from ever becoming cross-project
        # by accident; each retrieval branch receives this resolved value
        # before ranking/fusion starts.
        project = resolve_project(project)
        if not query_text:
            rows = await self._graph_rows(
                project=project, category=category, limit=top_k * self.candidate_multiplier,
                memory_scope=memory_scope,
                memory_branch=memory_branch,
            )
            graph_results = self._filter_project_results(
                [self._normalize_graph_item(row) for row in rows],
                project,
            )
            return [
                item
                for item in graph_results
                if float(item.get("effective_weight", 0.0)) >= min_weight
            ][:top_k]

        if self.query_rewriter:
            query_text = await self.query_rewriter.rewrite(
                query_text,
                project=project,
                category=category,
            )

        if self.hyde and query_text:
            query_text = await self.hyde.expand(query_text, force=use_hyde)

        sparse_enabled = bool(getattr(self.qdrant, "sparse_enabled", False))
        if sparse_enabled:
            query_embedding, sparse_query = await asyncio.gather(
                self.embeddings.embed_query(query_text),
                self.embeddings.embed_sparse(query_text),
            )
            vector_results, sparse_results, graph_rows = await asyncio.gather(
                self.qdrant.search(
                    query_vector=query_embedding,
                    project=project,
                    type=category,
                    top_k=top_k * self.candidate_multiplier,
                    min_score=min_score,
                    memory_scope=memory_scope,
                    memory_branch=memory_branch,
                ),
                self.qdrant.search_sparse(
                    query_vector=sparse_query,
                    project=project,
                    type=category,
                    top_k=top_k * self.candidate_multiplier,
                    memory_scope=memory_scope,
                    memory_branch=memory_branch,
                ),
                self._graph_rows(
                    project=project,
                    category=category,
                    limit=top_k * self.candidate_multiplier,
                    memory_scope=memory_scope,
                    memory_branch=memory_branch,
                ),
            )
        else:
            query_embedding = await self.embeddings.embed_query(query_text)
            vector_results, graph_rows = await asyncio.gather(
                self.qdrant.search(
                    query_vector=query_embedding,
                    project=project,
                    type=category,
                    top_k=top_k * self.candidate_multiplier,
                    min_score=min_score,
                    memory_scope=memory_scope,
                    memory_branch=memory_branch,
                ),
                self._graph_rows(
                    project=project,
                    category=category,
                    limit=top_k * self.candidate_multiplier,
                    memory_scope=memory_scope,
                    memory_branch=memory_branch,
                ),
            )
            sparse_results = []

        # Storage backends receive the project filter above. Keep the same
        # invariant at the fusion boundary as a defense against stale payloads,
        # backend misconfiguration, or a store that returns an unfiltered row.
        vector_results = self._filter_project_results(vector_results, project)
        sparse_results = self._filter_project_results(sparse_results, project)

        # Quando o caller pede um limiar denso explícito, não deixe o ramo
        # estrutural do grafo fabricar resultados depois que todos os vetores
        # foram rejeitados pelo limiar. O modo padrão continua compatível com
        # a busca exploratória (min_score=0.0).
        if min_score > 0.0 and not vector_results:
            return []
        graph_results = self._filter_project_results(
            [self._normalize_graph_item(row) for row in graph_rows],
            project,
        )

        vector_ids = [item.get("memory_id", "") for item in vector_results if item.get("memory_id")]
        sparse_ids = [item.get("memory_id", "") for item in sparse_results if item.get("memory_id")]
        graph_ids = [item.get("memory_id", "") for item in graph_results if item.get("memory_id")]
        vector_id_set = set(vector_ids)
        sparse_id_set = set(sparse_ids)
        graph_id_set = set(graph_ids)
        # RRF ponderado: o ramo vetorial é relevante à query; o ramo do grafo
        # (query_by_project = ORDER BY effective_weight) é cego à query e injeta as
        # mesmas memórias de peso alto em toda busca — por isso é rebaixado. A
        # ativação espalhada é semeada pelos hits vetoriais, então carrega sinal de
        # relevância e fica entre os dois.
        ranked_lists = [vector_ids]
        list_weights = [1.0]
        if sparse_ids:
            ranked_lists.append(sparse_ids)
            list_weights.append(self.sparse_rrf_weight)
        ranked_lists.append(graph_ids)
        list_weights.append(self.graph_rrf_weight)
        activation_seed_ids = list(dict.fromkeys(vector_ids + sparse_ids))[:5]
        if self.spreading_activation and activation_seed_ids:
            activation_ids = await self.spreading_activation.activate(
                seed_ids=activation_seed_ids,
                project=project,
                top_k=top_k * self.candidate_multiplier,
            )
            ranked_lists.append(activation_ids)
            list_weights.append(self.activation_rrf_weight)
        fused_scores = self.reciprocal_rank_fusion(ranked_lists, k=60, weights=list_weights)
        diversified = self._diversify(fused_scores, vector_results + sparse_results + graph_results)

        by_id: dict[str, dict] = {}
        # Preserva o score denso quando existe: raw sparse/BM25 e cosine vivem em
        # escalas diferentes e só devem ser combinados por ranks (RRF).
        for item in graph_results + sparse_results + vector_results:
            memory_id = item.get("memory_id")
            if not memory_id:
                continue
            by_id.setdefault(memory_id, {}).update(item)

        # Cosseno denso real por id (só itens vetoriais têm) -> sinal de relevância
        # para o composite scorer, no lugar do RRF saturado.
        vector_score_by_id = {
            it.get("memory_id"): float(it.get("score", 0.0))
            for it in vector_results
            if it.get("memory_id")
        }

        pre_rerank: list[dict] = []
        for memory_id, rrf_score in diversified.items():
            item = by_id.get(memory_id, {}).copy()
            if not item:
                continue
            if float(item.get("effective_weight", 0.0)) < min_weight:
                continue
            item["rrf_score"] = rrf_score
            item["retrieval_source"] = self._get_source(
                memory_id,
                vector_id_set,
                sparse_id_set,
                graph_id_set,
            )
            pre_rerank.append(item)

        if self.composite_scorer:
            for item in pre_rerank:
                item["composite_score"] = self.composite_scorer.score(
                    rrf_score=item.get("rrf_score", 0.0),
                    updated_at=item.get("updated_at"),
                    effective_weight=float(item.get("effective_weight", 0.5)),
                    significance=float(item.get("significance", 0.5)),
                    vector_score=vector_score_by_id.get(item.get("memory_id")),
                )
            pre_rerank.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)

        if self.reranker and query_text:
            reranked = await self.reranker.rerank(
                query=query_text,
                documents=pre_rerank,
                top_k=len(pre_rerank) or top_k,
            )
            pre_rerank = self._blend_rerank(reranked)

        return pre_rerank[:top_k]

    async def _graph_rows(
        self,
        *,
        project: str,
        category: str | None,
        limit: int,
        memory_scope: MemoryScope | str = MemoryScope.SEMANTIC,
        memory_branch: str | None = None,
    ) -> list[dict]:
        if self.ledger is None:
            return await self.neo4j.query_by_project(
                project=project, category=category, limit=limit
            )
        revisions = await self.ledger.list_active_revisions(
            project=project,
            category=category,
            memory_scope=memory_scope,
            memory_branch=memory_branch,
        )
        rows: list[dict] = []
        for revision in revisions[:limit]:
            content = revision.content
            legacy_ids = dict(content.legacy_ids)
            memory = {
                "memory_id": (
                    legacy_ids.get("memory_id")
                    or legacy_ids.get("episode_id")
                    or legacy_ids.get("procedure_id")
                    or legacy_memory_id_for_family(revision.family_id)
                ),
                "family_id": str(revision.family_id),
                "revision_id": str(revision.revision_id),
                "project": content.project,
                "category": content.category,
                "type": content.category,
                "memory_scope": content.memory_scope.value,
                "branch": content.memory_branch,
                "domain": list(content.domain),
                "modules": list(content.modules),
                "title": content.title,
                "summary": content.summary,
                "details": content.details,
                "objective": content.objective,
                "trigger": content.trigger,
                "stakeholders": list(content.stakeholders),
                "action_triggers": list(content.action_triggers),
                "related_files": list(content.related_files),
                "business_rules": list(content.business_rules),
                "architectural_rationale": content.architectural_rationale,
                "examples": list(content.examples),
                "alternatives_considered": list(content.alternatives_considered),
                "status": "active",
                "weight_manual": content.weight_manual if content.weight_manual is not None else 0.5,
                "effective_weight": _effective_weight(content),
                "significance": content.significance,
                "weight_confidence": content.weight_confidence,
                "weight_usage": content.weight_usage,
                "weight_feedback": content.weight_feedback,
                "weight_contextual": content.weight_contextual,
                "last_accessed_at": content.last_accessed_at.isoformat() if content.last_accessed_at else None,
                "updated_at": revision.created_at.isoformat(),
                "created_at": revision.created_at.isoformat(),
                "event_date": content.valid_from.isoformat() if content.valid_from else None,
                "source_hash": revision.content_hash,
                "content_hash": revision.content_hash,
            }
            rows.append({"memory": memory, "related_titles": []})
        return rows

    def _blend_rerank(self, docs: list[dict]) -> list[dict]:
        """Reordena combinando rerank_score (min-max normalizado) com composite_score.

        Mantém o ganho de recall do reranker sem jogar fora a boa ordenação do
        first-stage. Se não há rerank_score (ex.: NoOpReranker), retorna como veio.
        """
        scores = [d.get("rerank_score") for d in docs if d.get("rerank_score") is not None]
        if not scores:
            return docs
        lo, hi = min(scores), max(scores)
        span = (hi - lo) or 1.0
        alpha = self.rerank_blend_alpha
        for doc in docs:
            raw = doc.get("rerank_score")
            rnorm = (raw - lo) / span if raw is not None else 0.0
            composite = float(doc.get("composite_score", 0.0))
            doc["final_score"] = alpha * rnorm + (1.0 - alpha) * composite
        docs.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
        return docs

    @staticmethod
    def reciprocal_rank_fusion(
        ranked_lists: list[list[str]], k: int = 60, weights: list[float] | None = None
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        for idx, ranked_list in enumerate(ranked_lists):
            weight = 1.0 if weights is None else weights[idx]
            for rank, doc_id in enumerate(ranked_list, start=1):
                if not doc_id:
                    continue
                scores[doc_id] = scores.get(doc_id, 0.0) + weight * (1.0 / (k + rank))
        return dict(sorted(scores.items(), key=lambda pair: pair[1], reverse=True))

    @staticmethod
    def _normalize_graph_item(record: dict) -> dict:
        memory = record.get("memory", {})
        return {
            **memory,
            "related_titles": record.get("related_titles", []),
            "score": float(memory.get("effective_weight", 0.0)),
        }

    @staticmethod
    def _filter_project_results(items: list[dict], project: str) -> list[dict]:
        """Keep only candidates belonging to the resolved project partition."""

        return [item for item in items if item.get("project") == project]

    def _diversify(
        self, fused_scores: dict[str, float], items: list[dict], max_similar: int = 2
    ) -> dict[str, float]:
        by_id = {item.get("memory_id"): item for item in items if item.get("memory_id")}
        seen_prefixes: dict[str, int] = {}
        diversified: dict[str, float] = {}
        for memory_id, score in fused_scores.items():
            item = by_id.get(memory_id)
            if not item:
                continue
            # Títulos narrativos podem compartilhar um prefixo intencional
            # (por exemplo, "The business rule is being applied as follows").
            # Diversificar por esse prefixo descartava quase todas as regras;
            # usa-se o resumo, removendo a moldura narrativa genérica.
            source_text = str(item.get("summary") or item.get("title", ""))
            source_text = re.sub(
                r"^(?:the|a|o|a regra|the business rule|the feature|the architectural decision)\b.*?(?:as follows|is being|está sendo)\s*",
                "",
                source_text,
                flags=re.IGNORECASE,
            )
            prefix = source_text[:80].lower()
            count = seen_prefixes.get(prefix, 0)
            if count >= max_similar:
                continue
            diversified[memory_id] = score
            seen_prefixes[prefix] = count + 1
        return diversified

    @staticmethod
    def _get_source(
        memory_id: str,
        vector_ids: set[str],
        sparse_ids: set[str],
        graph_ids: set[str],
    ) -> str:
        in_vector = memory_id in vector_ids
        in_sparse = memory_id in sparse_ids
        in_graph = memory_id in graph_ids
        if in_sparse:
            sources = []
            if in_vector:
                sources.append("dense")
            sources.append("sparse")
            if in_graph:
                sources.append("graph")
            return "+".join(sources)
        if in_vector and in_graph:
            return "hybrid"  # rótulo legado: dense + graph
        if in_vector:
            return "vector"
        return "graph"
