from __future__ import annotations

from dataclasses import dataclass

from decisionssearch.domain.memory.memory_candidate import MemoryCandidate
from decisionssearch.domain.memory.memory_item import MemoryItem
from decisionssearch.application.ports.abstractions import AdmissionGate, EmbeddingProvider, VectorStore


@dataclass
class AdmissionResult:
    status: str
    action: str
    memory_id: str | None = None
    related_id: str | None = None
    reason: str = ""


class ProjectGate(AdmissionGate):
    async def evaluate(self, candidate: MemoryCandidate) -> AdmissionResult | None:
        if not candidate.project:
            return AdmissionResult(
                status="rejected", action="reject", reason="Sem projeto definido"
            )
        return None


class EvidenceGate(AdmissionGate):
    async def evaluate(self, candidate: MemoryCandidate) -> AdmissionResult | None:
        if not candidate.evidence:
            return AdmissionResult(
                status="evidence_only",
                action="reject",
                reason="Sem evidencia concreta",
            )
        return None


class DuplicateGate(AdmissionGate):
    SIMILARITY_THRESHOLD = 0.92
    REFINEMENT_THRESHOLD = 0.80

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        next_gate: AdmissionGate | None = None,
    ):
        super().__init__(next_gate=next_gate)
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider

    async def evaluate(self, candidate: MemoryCandidate) -> AdmissionResult | None:
        text = f"{candidate.title} | {candidate.summary}"
        embedding = await self.embedding_provider.embed(text)
        similar = await self.vector_store.find_similar(
            embedding=embedding,
            project=candidate.project,
            type=candidate.type,
            threshold=self.REFINEMENT_THRESHOLD,
        )
        if not similar:
            return None

        best = similar[0]
        score = float(best.get("score", 0.0))
        related_id = best.get("memory_id")
        if not related_id:
            return None

        candidate_id = MemoryItem.generate_id(candidate.project, candidate.type, candidate.title)
        if str(related_id) == candidate_id:
            return AdmissionResult(
                status="active",
                action="update",
                memory_id=related_id,
                reason=f"Identidade estável encontrada (score={score:.3f})",
            )

        if score >= self.REFINEMENT_THRESHOLD:
            return AdmissionResult(
                status="active",
                action="refine",
                memory_id=candidate_id,
                related_id=related_id,
                reason=f"Memória semanticamente próxima com identidade distinta (score={score:.3f})",
            )

        return None


class WeightGate(AdmissionGate):
    MIN_WEIGHT = 0.3

    async def evaluate(self, candidate: MemoryCandidate) -> AdmissionResult | None:
        is_adr = candidate.type == "ArchitecturalDecision"
        if candidate.proposed_weight < self.MIN_WEIGHT and not is_adr:
            return AdmissionResult(
                status="rejected",
                action="reject",
                reason=f"Peso {candidate.proposed_weight:.2f} abaixo do minimo",
            )
        return None


class ContextValidationGate(AdmissionGate):
    CONTEXT_REQUIRED_TYPES = {"BusinessRule"}

    async def evaluate(self, candidate: MemoryCandidate) -> AdmissionResult | None:
        if candidate.type in self.CONTEXT_REQUIRED_TYPES and not candidate.domain:
            return AdmissionResult(
                status="rejected",
                action="reject",
                reason=f"{candidate.type} requer ao menos um dominio",
            )
        if candidate.type == "FeatureDescription" and not (
            candidate.trigger or candidate.objective or candidate.related_files
        ):
            return AdmissionResult(
                status="rejected",
                action="reject",
                reason="FeatureDescription requer gatilho, objetivo ou arquivos relacionados",
            )
        if candidate.type == "CodePattern" and not candidate.examples:
            return AdmissionResult(
                status="rejected",
                action="reject",
                reason="CodePattern requer exemplos concretos de um padrão reutilizável",
            )
        if candidate.type == "ArchitecturalDecision":
            if not candidate.architectural_rationale:
                return AdmissionResult(
                    status="rejected",
                    action="reject",
                    reason="ArchitecturalDecision requer rationale arquitetural factual",
                )
            if not candidate.alternatives_considered:
                return AdmissionResult(
                    status="rejected",
                    action="reject",
                    reason="ArchitecturalDecision requer ao menos uma alternativa rejeitada",
                )
        return None
