"""Registro de ramos de memória: fonte da verdade de ramos válidos.

Responsável por registrar, listar e validar ramos, e por resolver o escopo de uma
busca (isolada, cross-ramo ou default). Cf. spec memory-branching (R1, R3.3, R5.3, R6.1).
"""

from __future__ import annotations

from decisionssearch.domain.shared.branch import (
    ALL_BRANCHES,
    DEFAULT_BRANCH,
    BranchMeta,
    BranchScope,
    normalize_branch,
)
from decisionssearch.domain.shared.exceptions import MemoryServiceError

# Taxonomia canônica de memória de agente (semantic/episodic/procedural).
_SEED_BRANCHES: tuple[tuple[str, str], ...] = (
    (DEFAULT_BRANCH, "Memória semântica: regras, decisões e padrões (ramo default)."),
    ("episodic", "Memória episódica: resultados e eventos de sessões."),
    ("procedural", "Memória procedural: planos, recipes e reasoning de agentes."),
)


class BranchRegistry:
    """Registra, lista e valida ramos; resolve escopos de busca."""

    def __init__(self, seed: dict[str, str] | None = None) -> None:
        self._branches: dict[str, BranchMeta] = {}
        source = seed if seed is not None else dict(_SEED_BRANCHES)
        for branch_id, description in source.items():
            self.register(branch_id, description)

    def register(self, branch_id: str, description: str = "") -> BranchMeta:
        """Registra um ramo novo. Rejeita vazio e duplicado (R1.1, R1.3)."""
        normalized = normalize_branch(branch_id)
        if not normalized:
            raise MemoryServiceError(
                "Identificador de ramo vazio.", context={"branch": branch_id}
            )
        if normalized in self._branches:
            raise MemoryServiceError(
                f"Ramo '{normalized}' já registrado.",
                context={"branch": normalized},
            )
        meta = BranchMeta(branch_id=normalized, description=description)
        self._branches[normalized] = meta
        return meta

    def is_registered(self, branch_id: str) -> bool:
        return normalize_branch(branch_id) in self._branches

    def require(self, branch_id: str) -> str:
        """Retorna o ramo normalizado se registrado; senão erro acionável (R3.3, R4.3)."""
        normalized = normalize_branch(branch_id)
        if normalized not in self._branches:
            raise MemoryServiceError(
                f"Ramo desconhecido: '{normalized}'. Registrados: {sorted(self._branches)}.",
                context={"branch": normalized, "registered": sorted(self._branches)},
            )
        return normalized

    def list(self) -> list[BranchMeta]:
        return list(self._branches.values())

    def resolve_scope(self, scope: BranchScope = None) -> list[str]:
        """Resolve um escopo em lista de ramos válidos (R5.3, R7.1)."""
        if scope is None:
            return [DEFAULT_BRANCH]
        if scope == ALL_BRANCHES:
            return sorted(self._branches)
        if isinstance(scope, str):
            return [self.require(scope)]
        return [self.require(branch) for branch in scope]
