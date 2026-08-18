from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class WeightConfig:
    alpha: float = 0.30
    beta: float = 0.25
    gamma: float = 0.20
    delta: float = 0.15
    epsilon: float = 0.10

    def __post_init__(self):
        total = self.alpha + self.beta + self.gamma + self.delta + self.epsilon
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Weight coefficients must sum to 1.0, got {total:.4f}")


class WeightService:
    def __init__(self, config: WeightConfig | None = None):
        self.config = config or WeightConfig()

    def calculate_effective_weight(
        self,
        weight_manual: float,
        weight_confidence: float,
        weight_usage: float,
        weight_feedback: float,
        weight_contextual: float = 0.5,
        last_accessed_at: datetime | str | None = None,
        significance: float = 0.5,
        config: WeightConfig | None = None,
    ) -> float:
        c = config or self.config
        base_weight = (
            c.alpha * weight_manual
            + c.beta * weight_confidence
            + c.gamma * weight_usage
            + c.delta * weight_feedback
            + c.epsilon * weight_contextual
        )
        if last_accessed_at:
            if isinstance(last_accessed_at, str):
                last_accessed_at = datetime.fromisoformat(last_accessed_at.replace("Z", "+00:00"))
            decay = self.calculate_decay(significance, last_accessed_at)
            return max(0.0, min(1.0, round(base_weight * decay, 4)))
        return max(0.0, min(1.0, round(base_weight, 4)))

    def calculate_decay(self, significance: float, last_accessed_at: datetime) -> float:
        now = datetime.now(timezone.utc)
        reference = last_accessed_at.astimezone(timezone.utc)
        days_since = max((now - reference).days, 0)
        half_life = 30 + (max(0.0, min(1.0, significance)) * 335)
        return 0.5 ** (days_since / half_life)

    def update_on_retrieval(self, current_usage: float, was_accepted: bool) -> float:
        increment = 0.05 if was_accepted else 0.01
        return min(current_usage + increment, 1.0)

    def update_on_feedback(self, current_feedback: float, score: float) -> float:
        return round(current_feedback * 0.8 + score * 0.2, 4)

    def reinforce_on_retrieval(
        self,
        weight_manual: float,
        weight_usage: float,
        was_accepted: bool,
        reinforcement_factor: float = 0.1,
    ) -> tuple[float, float]:
        if was_accepted:
            boosted = min(1.0, weight_manual + reinforcement_factor)
            updated_usage = self.update_on_retrieval(weight_usage, was_accepted)
            return boosted, updated_usage
        return weight_manual, self.update_on_retrieval(weight_usage, was_accepted)

    def get_priority_config(self, category: str) -> WeightConfig:
        configs = {
            "FeatureDescription": WeightConfig(
                alpha=0.45, beta=0.20, gamma=0.15, delta=0.10, epsilon=0.10
            ),
            "DesignRule": WeightConfig(alpha=0.40, beta=0.20, gamma=0.15, delta=0.15, epsilon=0.10),
            "BusinessRule": WeightConfig(
                alpha=0.20, beta=0.35, gamma=0.20, delta=0.15, epsilon=0.10
            ),
            "ArchitecturalDecision": WeightConfig(
                alpha=0.35, beta=0.25, gamma=0.10, delta=0.20, epsilon=0.10
            ),
            "DesignPattern": WeightConfig(
                alpha=0.25, beta=0.25, gamma=0.25, delta=0.15, epsilon=0.10
            ),
        }
        return configs.get(category, WeightConfig())

    def significance_for_category(self, category: str) -> float:
        """Significância intrínseca por categoria (governa o half-life do decay).

        Conhecimento mais estrutural/duradouro (decisão arquitetural, regra de
        design) decai mais devagar; regra de negócio muda mais. Antes era
        hardcoded 0.5 na persistência (dead parameter) — ver Q11 no plano de
        melhorias 2026-06-04.
        """
        significances = {
            "FeatureDescription": 0.85,
            "ArchitecturalDecision": 0.9,
            "DesignRule": 0.8,
            "DesignPattern": 0.75,
            "BusinessRule": 0.6,
        }
        return significances.get(category, 0.5)
