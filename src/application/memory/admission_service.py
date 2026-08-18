from __future__ import annotations

from decisionssearch.domain.shared.exceptions import AdmissionError
from decisionssearch.domain.memory.memory_candidate import MemoryCandidate
from decisionssearch.application.ports.abstractions import VectorStore
from decisionssearch.application.memory.admission_gates import (
    AdmissionResult,
    ContextValidationGate,
    DuplicateGate,
    EvidenceGate,
    ProjectGate,
    WeightGate,
)
from decisionssearch.infrastructure.ai.embeddings.embedding_service import EmbeddingService


class AdmissionService:
    """Política de admissão via Chain of Responsibility."""

    def __init__(self, vector_store: VectorStore, embeddings: EmbeddingService):
        self.chain = self._build_chain(vector_store=vector_store, embeddings=embeddings)

    def _build_chain(self, vector_store: VectorStore, embeddings: EmbeddingService):
        weight_gate = WeightGate()
        context_gate = ContextValidationGate(next_gate=weight_gate)
        duplicate_gate = DuplicateGate(
            vector_store=vector_store,
            embedding_provider=embeddings,
            next_gate=context_gate,
        )
        evidence_gate = EvidenceGate(next_gate=duplicate_gate)
        return ProjectGate(next_gate=evidence_gate)

    async def evaluate(self, candidate: MemoryCandidate) -> AdmissionResult:
        try:
            return await self.chain.handle(candidate)
        except Exception as error:
            raise AdmissionError(
                f"Erro na avaliação de admissão: {error}",
                gate="unknown",
                candidate_title=candidate.title,
            ) from error
