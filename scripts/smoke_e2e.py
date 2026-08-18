"""Smoke test end-to-end do pipeline de memória.

Exercita o caminho real que as MCP tools usam:
  create (embedding local + Qdrant upsert + Neo4j write)
  -> query (hybrid search + RRF + composite scorer).

Requer Neo4j + Qdrant no ar (docker compose up -d) e a collection criada
(scripts/bootstrap.py ou scripts/bootstrap_qdrant.py). Roda offline com embeddings locais (MiniLM).

Uso:
    uv run python scripts/smoke_e2e.py
"""

from __future__ import annotations

import asyncio
import uuid

from decisionssearch.domain.catalog.catalog_commands import CreateManualMemoryCommand
from decisionssearch.bootstrap.container import create_container


async def main() -> int:
    container = create_container()
    marker = uuid.uuid4().hex[:8]
    project = "ExampleProject"
    title = f"Convencao de cache key Redis [{marker}]"

    try:
        # Garante a collection com a dimensão do provider local (384).
        await container.qdrant.ensure_collection(container.embeddings._provider().dimensions)

        print(f"[1/2] Criando memória manual (marker={marker})...")
        command = CreateManualMemoryCommand(
            project=project,
            category="DesignRule",
            domain=[],
            modules=["cache"],
            title=title,
            summary="No ExampleProject, cache keys no Redis usam prefixo pj:cache:{tenant_id}:{entity}.",
            details="Sempre namespacear por tenant para evitar vazamento entre clientes.",
            examples=["pj:cache:42:invoice"],
            alternatives_considered=[],
            event_date="",
        )
        created = await container.manual_memory_authoring.create_manual_memory(command)
        created_id = getattr(created, "memory_id", None) or getattr(created, "id", None)
        print(f"      criado: memory_id={created_id}")

        print("[2/2] Consultando de volta via hybrid search...")
        results = await container.search.search(
            query_text="qual a convencao de cache key no ExampleProject?",
            project=project,
            category=None,
            top_k=5,
            min_weight=0.0,
        )
        print(f"      {len(results)} resultado(s):")
        hit = False
        for i, item in enumerate(results, 1):
            t = item.get("title", "")
            score = item.get("composite_score", item.get("rrf_score"))
            src = item.get("retrieval_source")
            print(f"        {i}. [{score}] ({src}) {t}")
            if marker in str(t):
                hit = True

        print()
        if hit:
            print("RESULTADO: ✅ memória criada foi recuperada na busca. Pipeline e2e OK.")
            return 0
        print("RESULTADO: ⚠️ memória criada NÃO apareceu no top-5. Pipeline roda mas ranking não trouxe o item.")
        return 2
    finally:
        await container.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
