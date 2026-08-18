"""Abstrações base para Strategy/Repository/Chain patterns."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from decisionssearch.domain.memory.memory_candidate import MemoryCandidate
from decisionssearch.domain.memory.memory_item import MemoryItem

if TYPE_CHECKING:
    from decisionssearch.application.memory.admission_gates import AdmissionResult


class EmbeddingProvider(ABC):
    """Strategy para geração de embeddings."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Gera embedding para um único texto."""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Gera embeddings para múltiplos textos."""


class VectorStore(ABC):
    """Repository para operações vetoriais."""

    @abstractmethod
    async def ensure_collection(self, vector_size: int | None = None) -> None:
        """Garante collection e índices de payload."""

    @abstractmethod
    async def upsert(self, memory_id: str, embedding: list[float], item: MemoryItem) -> None:
        """Upsert de memória vetorial."""

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        project: str | None = None,
        type: str | None = None,
        status: str = "active",
        domain: str | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[dict]:
        """Busca vetorial com filtros de payload."""

    @abstractmethod
    async def find_similar(
        self,
        embedding: list[float],
        project: str,
        type: str,
        threshold: float = 0.92,
    ) -> list[dict]:
        """Busca similaridade para deduplicação."""

    @abstractmethod
    async def delete(self, memory_id: str) -> None:
        """Remove ponto vetorial por memory_id."""


class GraphStore(ABC):
    """Repository para operações de grafo."""

    @abstractmethod
    async def bootstrap(self, projects: list[str], domains: list[str] | None = None) -> None:
        """Bootstrapping semântico do grafo."""

    @abstractmethod
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
        """Upsert de MemoryItem no grafo."""

    @abstractmethod
    async def link_memories(self, from_id: str, rel_type: str, to_id: str) -> None:
        """Cria relação entre memórias."""

    @abstractmethod
    async def query_by_project(
        self,
        project: str,
        category: str | None = None,
        status: str = "active",
        limit: int = 20,
    ) -> list[dict]:
        """Consulta memórias por projeto."""

    @abstractmethod
    async def get_memory(self, memory_id: str) -> dict | None:
        """Retorna uma memória pelo memory_id."""

    @abstractmethod
    async def close(self) -> None:
        """Libera recursos do driver."""


class Reranker(ABC):
    """Strategy para reranking semântico pós-fusão."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: int = 10,
    ) -> list[dict]:
        """Reordena documentos por relevância semântica profunda."""

    async def warmup(self) -> None:
        """Pré-carrega modelos pesados (no-op por padrão).

        Chamar no startup evita o cold-start (~400MB no cross-encoder local) na
        primeira query real — ver Q5 no plano de melhorias.
        """
        return None


class AdmissionGate(ABC):
    """Chain of Responsibility para gates de admissão."""

    def __init__(self, next_gate: "AdmissionGate | None" = None):
        self.next_gate = next_gate

    @abstractmethod
    async def evaluate(self, candidate: MemoryCandidate) -> "AdmissionResult | None":
        """Decisão do gate atual. None para seguir a chain."""

    async def handle(self, candidate: MemoryCandidate) -> "AdmissionResult":
        from decisionssearch.application.memory.admission_gates import AdmissionResult

        result = await self.evaluate(candidate)
        if result:
            return result
        if self.next_gate:
            return await self.next_gate.handle(candidate)
        return AdmissionResult(status="active", action="create", reason="Passed all gates")
