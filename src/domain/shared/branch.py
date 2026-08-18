"""Identidade e escopo de ramos de memória (spec memory-branching).

Um ramo é uma dimensão lógica de primeira classe: todo item de memória pertence a
exatamente um ramo. O padrão é `semantic` (regras/decisões/patterns — o acervo atual).
Não importa camadas externas; fica na base da direção de dependência do domínio.
"""

from __future__ import annotations

from pydantic import BaseModel

# Ramo default: o acervo existente é memória semântica (regras/decisões/patterns).
DEFAULT_BRANCH: str = "semantic"
# Sentinela de escopo "todos os ramos registrados".
ALL_BRANCHES: str = "*"

# Escopo de busca:
#   None            -> [DEFAULT_BRANCH]   (retrocompat)
#   ALL_BRANCHES    -> todos os registrados
#   str | list[str] -> explícito (validado contra o registry)
BranchScope = str | list[str] | None


def normalize_branch(value: str) -> str:
    """Normaliza um identificador de ramo (strip + lower). Não aplica default."""
    return (value or "").strip().lower()


class BranchMeta(BaseModel):
    """Metadados de um ramo registrado."""

    branch_id: str
    description: str = ""
    # Invariante do single-collection: todos os ramos compartilham o mesmo modelo.
    embedding_model: str = "minilm-384"
