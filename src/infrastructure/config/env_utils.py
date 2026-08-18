"""Helpers para leitura robusta de variáveis de ambiente.

Motivação: ``int(os.getenv("X", "768"))`` levanta ``ValueError`` quando a
variável existe porém está **vazia** (``X=``), porque o default do
``os.getenv`` só se aplica quando a chave está ausente — não quando está
vazia. Arquivos ``.env`` frequentemente trazem chaves vazias como template,
o que transformava isso em um crash de boot. ``env_int`` trata
ausente/vazia/whitespace/inválida como o default.
"""

from __future__ import annotations

import os

# Carrega o .env de forma centralizada. Antes, o .env só era lido como efeito
# colateral de importar ``embedding_providers`` — qualquer entrypoint que não
# passasse por lá (ex.: scripts/bootstrap.py) subia sem NEO4J_PASSWORD e
# falhava com "missing key credentials". env_utils é foundational (importado
# por qdrant/embeddings/hyde/scripts), então carregar aqui cobre todos os
# caminhos. ``override=False`` (default) preserva vars já setadas no ambiente.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv é dependência, mas seja defensivo
    pass


def env_int(name: str, default: int) -> int:
    """Lê ``name`` como int, caindo no ``default`` se ausente/vazia/inválida."""
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    """Lê ``name`` como float, caindo no ``default`` se ausente/vazia/inválida."""
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    """Lê ``name`` como booleano sem tratar uma string não-vazia como ``True``.

    Arquivos ``.env`` normalmente expressam flags como ``true``/``false``. Usar
    ``bool(os.getenv(...))`` faria ``"false"`` habilitar uma feature por engano.
    Valores ausentes, vazios ou inválidos mantêm o default para permitir rollout
    gradual de recursos que mudam o schema de armazenamento.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default
