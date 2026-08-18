from __future__ import annotations

from decisionssearch.application.memory.project_context import resolve_project
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService


class ContextResolver:
    """Resolve contexto minimo (project/domain/categoria provavel)."""

    CATEGORY_KEYWORDS: dict[str, list[str]] = {
        "FeatureDescription": ["feature", "fluxo", "flow", "gatilho", "trigger", "stakeholder"],
        "BusinessRule": ["regra", "rule", "obrigatorio", "deve", "proibido"],
        "DesignPattern": ["pattern", "padrao", "factory", "strategy", "service"],
        "DesignRule": ["convencao", "naming", "estilo", "guard clause"],
        "ArchitecturalDecision": ["decisao", "decision", "adr", "optamos", "escolhemos"],
    }

    DOMAIN_KEYWORDS: dict[str, list[str]] = {
        "Sazonalizacao": ["sazonaliz", "sazonal", "perfil"],
        "BalancoEnergetico": ["balanco", "energetico", "energia"],
        "PLD": ["pld", "preco de liquidacao"],
        "Contratos": ["contrato", "contract", "ccv"],
    }

    PROJECT_KEYWORDS: dict[str, list[str]] = {
        "CORE": ["core", "sazonal", "balanco", "pld", "ccee"],
        "RETUSD": ["retusd"],
    }

    def __init__(self, neo4j: Neo4jService):
        self.neo4j = neo4j

    async def resolve(
        self,
        text: str,
        project_hint: str | None = None,
        domain_hint: str | None = None,
    ) -> dict:
        # The workspace is the authoritative project partition for agent-driven
        # ingestion. A hint remains supported for batch/import workflows, but
        # lexical matches in the payload must never silently move a memory to a
        # different project.
        project = resolve_project(project_hint)
        domain = domain_hint or self._infer_domain(text)
        category = self._infer_category(text)

        return {
            "project": project,
            "domain": [domain] if domain else [],
            "probable_category": category,
            "has_project": project is not None,
        }

    def _infer_category(self, text: str) -> str | None:
        text_lower = text.lower()
        scores = {
            category: sum(1 for kw in keywords if kw in text_lower)
            for category, keywords in self.CATEGORY_KEYWORDS.items()
        }
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else None

    def _infer_domain(self, text: str) -> str | None:
        text_lower = text.lower()
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return domain
        return None

    def _infer_project(self, text: str) -> str | None:
        text_lower = text.lower()
        for project, keywords in self.PROJECT_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return project
        return None
