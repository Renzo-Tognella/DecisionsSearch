"""Serviço de operações vetoriais no Qdrant."""

from __future__ import annotations

import os
import uuid
import asyncio
from collections import defaultdict
from datetime import datetime, timezone

from decisionssearch.infrastructure.config.env_utils import env_bool, env_int
from decisionssearch.infrastructure.ai.providers.model_provider import get_embedding_dimensions

try:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import (
        Distance,
        DatetimeRange,
        FieldCondition,
        Filter,
        MatchValue,
        PayloadSchemaType,
        PointIdsList,
        PointStruct,
        SparseIndexParams,
        SparseVector,
        SparseVectorParams,
        VectorParams,
    )
except Exception:  # pragma: no cover

    class AsyncQdrantClient:  # type: ignore[override]
        def __init__(self, *args, **kwargs):  # noqa: ANN002,ANN003
            raise RuntimeError("qdrant_client indisponível no ambiente atual")

    class _DistanceValue:
        def __init__(self, value: str):
            self.value = value

    class Distance:  # type: ignore[override]
        COSINE = _DistanceValue("Cosine")

    class VectorParams:  # type: ignore[override]
        def __init__(self, size: int, distance):
            self.size = size
            self.distance = distance

    class PayloadSchemaType:  # type: ignore[override]
        KEYWORD = "keyword"

    class MatchValue:  # type: ignore[override]
        def __init__(self, value):
            self.value = value

    class FieldCondition:  # type: ignore[override]
        def __init__(self, key: str, match=None, range=None, is_null=None):  # noqa: A002
            self.key = key
            self.match = match
            self.range = range
            self.is_null = is_null

    class DatetimeRange:  # type: ignore[override]
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Filter:  # type: ignore[override]
        def __init__(self, must=None, should=None):
            self.must = must
            self.should = should

    class PointStruct:  # type: ignore[override]
        def __init__(self, id, vector, payload):
            self.id = id
            self.vector = vector
            self.payload = payload

    class SparseIndexParams:  # type: ignore[override]
        def __init__(self, on_disk: bool = False):
            self.on_disk = on_disk

    class SparseVectorParams:  # type: ignore[override]
        def __init__(self, index=None):
            self.index = index

    class SparseVector:  # type: ignore[override]
        def __init__(self, indices, values):
            self.indices = indices
            self.values = values

    class PointIdsList:  # type: ignore[override]
        def __init__(self, points):
            self.points = points


from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.domain.memory.memory_item import MemoryItem
from decisionssearch.domain.memory_ledger import (
    MemoryRevision,
    MemoryScope,
    RevisionState,
    legacy_memory_id_for_family,
)
from decisionssearch.application.memory.ledger.views import _effective_weight
from decisionssearch.application.ports.abstractions import VectorStore


class QdrantService(VectorStore):
    """Encapsula recuperação densa e lexical sparse na mesma collection.

    A representação densa legada mantém o vetor sem nome (``""`` no payload
    híbrido). A representação BM25 usa um vetor sparse nomeado. Isso permite
    migrar sem trocar IDs/payloads nem introduzir um segundo datastore.
    """

    def __init__(
        self,
        client: AsyncQdrantClient | None = None,
        collection: str | None = None,
        sparse_enabled: bool | None = None,
    ):
        self.client = client or AsyncQdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=env_int("QDRANT_PORT", 6333),
        )
        self.collection = collection or os.getenv("QDRANT_COLLECTION", "memories")
        self.sparse_enabled = (
            env_bool("SPARSE_SEARCH_ENABLED", False)
            if sparse_enabled is None
            else sparse_enabled
        )
        self.sparse_vector_name = os.getenv("SPARSE_VECTOR_NAME", "bm25").strip() or "bm25"
        self.sparse_index_on_disk = env_bool("SPARSE_INDEX_ON_DISK", False)
        self.canonical_only = env_bool("DECISIONSSEARCH_CANONICAL_LEDGER_ONLY", False)
        self._head_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @staticmethod
    def _normalize_valid_at(valid_at: datetime | None) -> datetime:
        value = valid_at or datetime.now(timezone.utc)
        if value.tzinfo is None:
            raise ValueError("valid_at precisa conter timezone explícito")
        return value

    @staticmethod
    def _payload_is_valid_at(payload: dict, valid_at: datetime) -> bool:
        """Apply the temporal window after retrieval for local Qdrant parity."""

        def parse(value):  # noqa: ANN001
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

        valid_from = parse(payload.get("valid_from"))
        valid_to = parse(payload.get("valid_to"))
        return not (valid_from and valid_from > valid_at) and not (valid_to and valid_to <= valid_at)

    @staticmethod
    def head_point_id(
        family_id: str,
        memory_scope: MemoryScope | str,
        memory_branch: str,
    ) -> str:
        """Identidade estável do head materializado, não da revisão histórica."""

        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"decisionssearch:memory-head:{family_id}:{str(memory_scope)}:{memory_branch}",
            )
        )

    async def ensure_collection(self, vector_size: int | None = None) -> None:
        target_size = vector_size or get_embedding_dimensions()
        try:
            collections_response = await self.client.get_collections()
            collection_names = {item.name for item in collections_response.collections}

            collection_exists = self.collection in collection_names
            if not collection_exists:
                create_kwargs = {
                    "collection_name": self.collection,
                    "vectors_config": VectorParams(size=target_size, distance=Distance.COSINE),
                }
                if self.sparse_enabled:
                    create_kwargs["sparse_vectors_config"] = self._sparse_vectors_config()
                await self.client.create_collection(**create_kwargs)
            elif vector_size is not None:
                # Guard de dimensão só quando o caller passou um tamanho EXPLÍCITO.
                # Sem vector_size, o default (768) não é confiável (provider local usa
                # 384), e "garanta que a collection existe" não deve virar falso
                # positivo. Com tamanho explícito, criar/pular silenciosamente uma
                # collection de dimensão divergente faria inserts/buscas falharem
                # tarde, com erro críptico ("expected dim X, got Y") — falhamos cedo.
                existing_size = await self._existing_vector_size()
                if existing_size is not None and existing_size != vector_size:
                    raise MemoryServiceError(
                        f"Collection Qdrant '{self.collection}' já existe com dimensão "
                        f"{existing_size}, mas foi pedida com dimensão {vector_size}. "
                        f"Inserts e buscas vão falhar. Recrie a collection: "
                        f"DELETE /collections/{self.collection} e rode scripts/bootstrap.py.",
                        context={
                            "collection": self.collection,
                            "existing_dim": existing_size,
                            "expected_dim": vector_size,
                        },
                    )

            if collection_exists and self.sparse_enabled:
                await self._assert_sparse_vector_exists()

            for field in (
                "project",
                "type",
                "status",
                "domain",
                "modules",
                "memory_scope",
                "memory_branch",
                "canonical_store",
            ):
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            for field in ("valid_from", "valid_to"):
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=PayloadSchemaType.DATETIME,
                )
        except MemoryServiceError:
            raise
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao preparar collection Qdrant: {error}",
                context={"collection": self.collection, "vector_size": target_size},
            ) from error

    def _sparse_vectors_config(self) -> dict[str, SparseVectorParams]:
        return {
            self.sparse_vector_name: SparseVectorParams(
                index=SparseIndexParams(on_disk=self.sparse_index_on_disk)
            )
        }

    async def _assert_sparse_vector_exists(self) -> None:
        """Falha cedo se uma collection densa antiga ainda não foi migrada."""
        try:
            info = await self.client.get_collection(self.collection)
        except Exception as error:
            raise MemoryServiceError(
                f"Não foi possível validar o vetor sparse da collection '{self.collection}': {error}",
                context={"collection": self.collection, "sparse_vector": self.sparse_vector_name},
            ) from error

        params = getattr(getattr(info, "config", None), "params", None)
        sparse_vectors = getattr(params, "sparse_vectors", None)
        sparse_names = set(sparse_vectors.keys()) if hasattr(sparse_vectors, "keys") else set()
        if self.sparse_vector_name in sparse_names:
            return

        raise MemoryServiceError(
            "SPARSE_SEARCH_ENABLED=true, mas a collection Qdrant existente não possui "
            f"o vetor sparse '{self.sparse_vector_name}'. Não ative a feature sobre a "
            "collection antiga: crie uma collection nova com sparse habilitado, reindexe "
            "e só então altere QDRANT_COLLECTION.",
            context={
                "collection": self.collection,
                "sparse_vector": self.sparse_vector_name,
            },
        )

    async def _existing_vector_size(self) -> int | None:
        """Dimensão do vetor da collection existente, ou None se indeterminável."""
        try:
            info = await self.client.get_collection(self.collection)
        except Exception:
            return None
        params = getattr(getattr(info, "config", None), "params", None)
        vectors = getattr(params, "vectors", None)
        if vectors is None:
            return None
        size = getattr(vectors, "size", None)
        if isinstance(size, int):
            return size
        # Vetores nomeados: dict {nome: VectorParams}
        if isinstance(vectors, dict):
            for value in vectors.values():
                inner = getattr(value, "size", None)
                if isinstance(inner, int):
                    return inner
        return None

    async def upsert(
        self,
        memory_id: str,
        embedding: list[float],
        item: MemoryItem,
        sparse_vector: SparseVector | None = None,
    ) -> None:
        if self.canonical_only:
            raise MemoryServiceError(
                "Escrita legada no Qdrant está bloqueada; crie uma proposta no ledger.",
                context={"memory_id": memory_id, "collection": self.collection},
            )
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, memory_id))
        payload = {
            "canonical_store": "legacy_projection",
            "memory_id": memory_id,
            "project": item.project,
            "type": item.category,
            "domain": item.domain,
            "modules": item.modules,
            "status": item.status.value,
            "weight_manual": item.weight_manual,
            "effective_weight": item.effective_weight,
            "weight_confidence": item.weight_confidence,
            "weight_usage": item.weight_usage,
            "weight_feedback": item.weight_feedback,
            "weight_contextual": item.weight_contextual,
            "last_accessed_at": item.last_accessed_at.isoformat()
            if item.last_accessed_at
            else None,
            "significance": item.significance,
            "title": item.title,
            "summary": item.summary,
            "objective": item.objective,
            "trigger": item.trigger,
            "stakeholders": item.stakeholders,
            "action_triggers": item.action_triggers,
            "related_files": item.related_files,
            "business_rules": item.business_rules,
            "architectural_rationale": item.architectural_rationale,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
            "event_date": item.event_date.isoformat() if item.event_date else None,
            # Pontos legados continuam consultáveis no ramo semântico durante a
            # migração; o ledger versionado usa upsert_revision_head abaixo.
            "memory_scope": MemoryScope.SEMANTIC.value,
            "memory_branch": "semantic",
        }

        point_vector: list[float] | dict[str, list[float] | SparseVector] = embedding
        if self.sparse_enabled:
            if sparse_vector is None:
                raise MemoryServiceError(
                    "SPARSE_SEARCH_ENABLED=true exige um vetor sparse no upsert.",
                    context={"collection": self.collection, "memory_id": memory_id},
                )
            # Em collection com vetor denso sem nome, o Qdrant representa esse
            # vetor como chave vazia quando o ponto também contém vetores nomeados.
            point_vector = {"": embedding, self.sparse_vector_name: sparse_vector}

        try:
            await self.client.upsert(
                collection_name=self.collection,
                points=[PointStruct(id=point_id, vector=point_vector, payload=payload)],
            )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha no upsert Qdrant: {error}",
                context={"collection": self.collection, "memory_id": memory_id},
            ) from error

    async def upsert_revision_head(
        self,
        revision: MemoryRevision,
        embedding: list[float],
        *,
        ledger_sequence: int,
        sparse_vector: SparseVector | None = None,
        state: RevisionState | str = RevisionState.ACTIVE,
    ) -> None:
        point_id = self.head_point_id(
            str(revision.family_id), revision.content.memory_scope, revision.content.memory_branch
        )
        async with self._head_locks[point_id]:
            await self._upsert_revision_head_unlocked(
                revision,
                embedding,
                ledger_sequence=ledger_sequence,
                sparse_vector=sparse_vector,
                state=state,
            )

    async def _upsert_revision_head_unlocked(
        self,
        revision: MemoryRevision,
        embedding: list[float],
        *,
        ledger_sequence: int,
        sparse_vector: SparseVector | None = None,
        state: RevisionState | str = RevisionState.ACTIVE,
    ) -> None:
        """Materializa somente um head do ledger versionado.

        O ponto usa ``family_id + scope + branch`` como identidade. O payload contém metadados
        para filtragem e diagnóstico; o snapshot canônico continua no ledger.
        """
        state_value = state.value if isinstance(state, RevisionState) else str(state)
        point_id = self.head_point_id(
            str(revision.family_id), revision.content.memory_scope, revision.content.memory_branch
        )
        content = revision.content
        existing_payload = await self._existing_head_payload(point_id)
        if existing_payload is not None:
            existing_sequence = existing_payload.get("ledger_sequence")
            if existing_sequence is not None and int(existing_sequence) > ledger_sequence:
                # Um evento atrasado nunca pode sobrescrever o head mais novo.
                return
            if existing_sequence is not None and int(existing_sequence) == ledger_sequence:
                return
        payload = {
            "canonical_store": "memory_ledger",
            "memory_id": (
                dict(content.legacy_ids).get("memory_id")
                or dict(content.legacy_ids).get("episode_id")
                or dict(content.legacy_ids).get("procedure_id")
                or legacy_memory_id_for_family(revision.family_id)
            ),
            "family_id": str(revision.family_id),
            "revision_id": str(revision.revision_id),
            "project": content.project,
            "type": content.category,
            "category": content.category,
            "memory_scope": content.memory_scope.value,
            "memory_branch": content.memory_branch,
            "git_ref": content.git_ref,
            "status": state_value,
            "content_hash": revision.content_hash,
            "ledger_sequence": ledger_sequence,
            "embedding_model": os.getenv("EMBEDDING_MODEL", "local"),
            "embedding_dimensions": len(embedding),
            # Texto duplicado apenas para ranking; respostas devem hidratar o ledger.
            "title": content.title,
            "summary": content.summary,
            "weight_manual": content.weight_manual if content.weight_manual is not None else 0.5,
            "effective_weight": _effective_weight(content),
            "weight_confidence": content.weight_confidence,
            "weight_usage": content.weight_usage,
            "weight_feedback": content.weight_feedback,
            "weight_contextual": content.weight_contextual,
            "significance": content.significance,
            "last_accessed_at": content.last_accessed_at.isoformat() if content.last_accessed_at else None,
            "valid_from": content.valid_from.isoformat() if content.valid_from else None,
            "valid_to": content.valid_to.isoformat() if content.valid_to else None,
        }
        point_vector: list[float] | dict[str, list[float] | SparseVector] = embedding
        if self.sparse_enabled:
            if sparse_vector is None:
                raise MemoryServiceError(
                    "SPARSE_SEARCH_ENABLED=true exige vetor sparse para revisão.",
                    context={"revision_id": str(revision.revision_id)},
                )
            point_vector = {"": embedding, self.sparse_vector_name: sparse_vector}
        try:
            await self.client.upsert(
                collection_name=self.collection,
                points=[PointStruct(id=point_id, vector=point_vector, payload=payload)],
            )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao materializar revisão no Qdrant: {error}",
                context={"revision_id": str(revision.revision_id), "collection": self.collection},
            ) from error

    async def _existing_head_payload(self, point_id: str) -> dict | None:
        retrieve = getattr(self.client, "retrieve", None)
        if retrieve is None:
            return None
        try:
            points = await retrieve(
                collection_name=self.collection,
                ids=[point_id],
                with_payload=True,
                with_vectors=False,
            )
        except TypeError:
            # Compatibilidade com clientes/fakes que não aceitam os flags.
            points = await retrieve(collection_name=self.collection, ids=[point_id])
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao ler o head atual no Qdrant: {error}",
                context={"collection": self.collection, "point_id": point_id},
            ) from error
        if not points:
            return None
        payload = getattr(points[0], "payload", None)
        return dict(payload or {})

    async def delete_revision_head(
        self,
        revision_id: str | None = None,
        *,
        family_id: str | None = None,
        memory_scope: MemoryScope | str = MemoryScope.SEMANTIC,
        memory_branch: str = "semantic",
        ledger_sequence: int | None = None,
    ) -> None:
        point_id = (
            self.head_point_id(family_id, memory_scope, memory_branch)
            if family_id
            else str(uuid.uuid5(uuid.NAMESPACE_URL, str(revision_id)))
        )
        async with self._head_locks[point_id]:
            await self._delete_revision_head_unlocked(
                revision_id,
                family_id=family_id,
                memory_scope=memory_scope,
                memory_branch=memory_branch,
                ledger_sequence=ledger_sequence,
            )

    async def _delete_revision_head_unlocked(
        self,
        revision_id: str | None = None,
        *,
        family_id: str | None = None,
        memory_scope: MemoryScope | str = MemoryScope.SEMANTIC,
        memory_branch: str = "semantic",
        ledger_sequence: int | None = None,
    ) -> None:
        # revision_id sem família é mantido apenas como compatibilidade para
        # consumidores antigos; heads novos sempre passam a família/escopo/ramo.
        point_id = (
            self.head_point_id(family_id, memory_scope, memory_branch)
            if family_id
            else str(uuid.uuid5(uuid.NAMESPACE_URL, str(revision_id)))
        )
        try:
            if family_id and (revision_id is not None or ledger_sequence is not None):
                existing_payload = await self._existing_head_payload(point_id)
                if existing_payload is not None:
                    existing_revision_id = existing_payload.get("revision_id")
                    existing_sequence = existing_payload.get("ledger_sequence")
                    if (
                        revision_id is not None
                        and existing_revision_id not in {None, str(revision_id)}
                        and (
                            ledger_sequence is None
                            or existing_sequence is None
                            or int(existing_sequence) > ledger_sequence
                        )
                    ):
                        # Uma remoção antiga nunca pode apagar o head mais novo.
                        return
                    if (
                        ledger_sequence is not None
                        and existing_sequence is not None
                        and int(existing_sequence) > ledger_sequence
                    ):
                        return
            await self.client.delete(
                collection_name=self.collection,
                points_selector=PointIdsList(points=[point_id]),
            )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao remover revisão derivada no Qdrant: {error}",
                context={"revision_id": revision_id or "", "collection": self.collection},
            ) from error

    async def search(
        self,
        query_vector: list[float],
        project: str | None = None,
        type: str | None = None,
        status: str = "active",
        domain: str | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
        memory_scope: MemoryScope | str = MemoryScope.SEMANTIC,
        memory_branch: str | None = None,
        valid_at=None,  # noqa: ANN001
    ) -> list[dict]:
        valid_at = self._normalize_valid_at(valid_at)
        query_filter = self._build_filter(
            project=project,
            type=type,
            status=status,
            domain=domain,
            memory_scope=memory_scope,
            memory_branch=memory_branch,
            valid_at=valid_at,
        )

        try:
            # query_points substitui o .search (deprecated no qdrant-client >=1.10).
            response = await self.client.query_points(
                collection_name=self.collection,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                score_threshold=min_score,
            )
            rows = [{"score": point.score, **(point.payload or {})} for point in response.points]
            if not rows:
                # Local Qdrant does not consistently evaluate nullable datetime
                # filters. Re-query structural filters only, then enforce the
                # validity window here so local and server backends agree.
                fallback_filter = self._build_filter(
                    project=project,
                    type=type,
                    status=status,
                    domain=domain,
                    memory_scope=memory_scope,
                    memory_branch=memory_branch,
                    valid_at=None,
                )
                response = await self.client.query_points(
                    collection_name=self.collection,
                    query=query_vector,
                    query_filter=fallback_filter,
                    limit=max(top_k * 10, top_k),
                    score_threshold=min_score,
                )
                rows = [{"score": point.score, **(point.payload or {})} for point in response.points]
            return [row for row in rows if self._payload_is_valid_at(row, valid_at)][:top_k]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha na busca Qdrant: {error}",
                context={"collection": self.collection, "top_k": top_k},
            ) from error

    async def search_sparse(
        self,
        query_vector: SparseVector,
        project: str | None = None,
        type: str | None = None,
        status: str = "active",
        domain: str | None = None,
        top_k: int = 10,
        memory_scope: MemoryScope | str = MemoryScope.SEMANTIC,
        memory_branch: str | None = None,
        valid_at=None,  # noqa: ANN001
    ) -> list[dict]:
        """Busca lexical BM25; seus scores só são comparáveis via RRF, não raw."""
        if not self.sparse_enabled:
            return []

        valid_at = self._normalize_valid_at(valid_at)
        query_filter = self._build_filter(
            project=project,
            type=type,
            status=status,
            domain=domain,
            memory_scope=memory_scope,
            memory_branch=memory_branch,
            valid_at=valid_at,
        )
        try:
            response = await self.client.query_points(
                collection_name=self.collection,
                query=query_vector,
                using=self.sparse_vector_name,
                query_filter=query_filter,
                limit=top_k,
            )
            rows = [{"score": point.score, **(point.payload or {})} for point in response.points]
            if not rows:
                fallback_filter = self._build_filter(
                    project=project,
                    type=type,
                    status=status,
                    domain=domain,
                    memory_scope=memory_scope,
                    memory_branch=memory_branch,
                    valid_at=None,
                )
                response = await self.client.query_points(
                    collection_name=self.collection,
                    query=query_vector,
                    using=self.sparse_vector_name,
                    query_filter=fallback_filter,
                    limit=max(top_k * 10, top_k),
                )
                rows = [{"score": point.score, **(point.payload or {})} for point in response.points]
            return [row for row in rows if self._payload_is_valid_at(row, valid_at)][:top_k]
        except Exception as error:
            raise MemoryServiceError(
                f"Falha na busca sparse Qdrant: {error}",
                context={
                    "collection": self.collection,
                    "sparse_vector": self.sparse_vector_name,
                    "top_k": top_k,
                },
            ) from error

    def _build_filter(
        self,
        project: str | None,
        type: str | None,
        status: str,
        domain: str | None,
        memory_scope: MemoryScope | str = MemoryScope.SEMANTIC,
        memory_branch: str | None = None,
        valid_at=None,  # noqa: ANN001
    ) -> Filter:
        conditions = [FieldCondition(key="status", match=MatchValue(value=status))]
        if self.canonical_only:
            conditions.append(
                FieldCondition(key="canonical_store", match=MatchValue(value="memory_ledger"))
            )
        if project:
            conditions.append(FieldCondition(key="project", match=MatchValue(value=project)))
        if type:
            conditions.append(FieldCondition(key="type", match=MatchValue(value=type)))
        if domain:
            conditions.append(FieldCondition(key="domain", match=MatchValue(value=domain)))
        conditions.append(
            FieldCondition(key="memory_scope", match=MatchValue(value=str(memory_scope)))
        )
        if memory_branch:
            conditions.append(FieldCondition(key="memory_branch", match=MatchValue(value=memory_branch)))
        if valid_at is not None:
            conditions.append(
                Filter(
                    should=[
                        FieldCondition(key="valid_from", is_null=True),
                        FieldCondition(key="valid_from", range=DatetimeRange(lte=valid_at)),
                    ]
                )
            )
            conditions.append(
                Filter(
                    should=[
                        FieldCondition(key="valid_to", is_null=True),
                        FieldCondition(key="valid_to", range=DatetimeRange(gt=valid_at)),
                    ]
                )
            )
        return Filter(must=conditions)

    async def find_similar(
        self,
        embedding: list[float],
        project: str,
        type: str,
        threshold: float = 0.92,
        memory_scope: MemoryScope | str = MemoryScope.SEMANTIC,
        memory_branch: str | None = None,
    ) -> list[dict]:
        return await self.search(
            query_vector=embedding,
            project=project,
            type=type,
            top_k=5,
            min_score=threshold,
            memory_scope=memory_scope,
            memory_branch=memory_branch,
        )

    async def delete(self, memory_id: str) -> None:
        if self.canonical_only:
            raise MemoryServiceError("Memórias canônicas só podem ser removidas por proposta do ledger")
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, memory_id))
        try:
            await self.client.delete(
                collection_name=self.collection,
                points_selector=PointIdsList(points=[point_id]),
            )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao deletar ponto no Qdrant: {error}",
                context={"collection": self.collection, "memory_id": memory_id},
            ) from error

    async def close(self) -> None:
        if hasattr(self.client, "close"):
            await self.client.close()

    async def update_payload(self, memory_id: str, updates: dict) -> None:
        if self.canonical_only:
            raise MemoryServiceError("Payload canônico só pode ser alterado pelo materializador")
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, memory_id))
        try:
            await self.client.set_payload(
                collection_name=self.collection,
                payload=updates,
                points=[point_id],
            )
        except Exception as error:
            raise MemoryServiceError(
                f"Falha ao atualizar payload no Qdrant: {error}",
                context={"collection": self.collection, "memory_id": memory_id},
            ) from error

    async def get_all_memory_ids(self, project: str | None = None) -> list[str]:
        ids: list[str] = []
        conditions = [FieldCondition(key="status", match=MatchValue(value="active"))]
        if self.canonical_only:
            conditions.append(
                FieldCondition(key="canonical_store", match=MatchValue(value="memory_ledger"))
            )
        if project:
            conditions.append(FieldCondition(key="project", match=MatchValue(value=project)))
        offset = None
        while True:
            results, offset = await self.client.scroll(
                collection_name=self.collection,
                scroll_filter=Filter(must=conditions),
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in results:
                if point.payload:
                    ids.append(str(point.payload.get("memory_id", "")))
            if not offset:
                break
        return [mid for mid in ids if mid]

    async def delete_orphaned_heads(self, expected_point_ids: set[str]) -> int:
        """Remove somente pontos canônicos que não existem mais no ledger.

        A reconstrução precisa ser uma reconciliação, não apenas uma sequência de
        upserts: famílias arquivadas ou mescladas deixam pontos antigos órfãos.
        """

        offset = None
        orphaned: list[str] = []
        canonical_filter = Filter(
            must=[FieldCondition(key="canonical_store", match=MatchValue(value="memory_ledger"))]
        )
        while True:
            points, offset = await self.client.scroll(
                collection_name=self.collection,
                scroll_filter=canonical_filter,
                limit=100,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            orphaned.extend(str(point.id) for point in points if str(point.id) not in expected_point_ids)
            if not offset:
                break
        for start in range(0, len(orphaned), 100):
            await self.client.delete(
                collection_name=self.collection,
                points_selector=PointIdsList(points=orphaned[start : start + 100]),
            )
        return len(orphaned)
