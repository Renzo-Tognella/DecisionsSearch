from __future__ import annotations

from datetime import datetime, timezone

from decisionssearch.infrastructure.config.env_utils import env_float


class CompositeScorer:
    def __init__(
        self,
        relevance_weight: float = 0.50,
        recency_weight: float = 0.25,
        importance_weight: float = 0.25,
        recency_half_life_days: float = 90.0,
    ):
        self.relevance_weight = relevance_weight
        self.recency_weight = recency_weight
        self.importance_weight = importance_weight
        self.recency_half_life_days = recency_half_life_days

    @classmethod
    def from_env(cls) -> "CompositeScorer":
        """Pesos tunáveis por env (C4), mantendo os defaults atuais.

        Permite iterar tuning (ex.: a Auditoria propõe 0.65/0.15/0.20, half-life
        180) sem mexer em código — mas só depois de validar no gold set (G8).
        """
        return cls(
            relevance_weight=env_float("SCORER_RELEVANCE_WEIGHT", 0.50),
            recency_weight=env_float("SCORER_RECENCY_WEIGHT", 0.25),
            importance_weight=env_float("SCORER_IMPORTANCE_WEIGHT", 0.25),
            recency_half_life_days=env_float("SCORER_RECENCY_HALF_LIFE_DAYS", 90.0),
        )

    def score(
        self,
        rrf_score: float,
        updated_at: str | None = None,
        effective_weight: float = 0.5,
        significance: float = 0.5,
        vector_score: float | None = None,
    ) -> float:
        # Relevância: usar o cosseno denso real (0-1) quando o item veio da busca
        # vetorial — discrimina muito melhor que o RRF normalizado, que satura
        # (min(1, rrf*60) ≈ 1.0 para quase todos os top ranks, achatando o sinal).
        # Cai no RRF normalizado só para itens exclusivos do grafo (sem cosseno).
        relevance = vector_score if vector_score is not None else self._normalize_rrf(rrf_score)
        recency = self._calculate_recency(updated_at)
        importance = min(1.0, (effective_weight + significance) / 2)
        return (
            self.relevance_weight * relevance
            + self.recency_weight * recency
            + self.importance_weight * importance
        )

    def _normalize_rrf(self, rrf_score: float) -> float:
        return min(1.0, rrf_score * 60)

    def _calculate_recency(self, updated_at: str | None) -> float:
        if not updated_at:
            return 0.5
        try:
            if isinstance(updated_at, str):
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            else:
                dt = updated_at
            now = datetime.now(timezone.utc)
            if hasattr(dt, "astimezone"):
                dt = dt.astimezone(timezone.utc)
            days = max((now - dt).days, 0)
            return 0.5 ** (days / self.recency_half_life_days)
        except Exception:
            return 0.5
