from __future__ import annotations

import asyncio
from decisionssearch.infrastructure.ai.providers.model_provider import get_embedding_dimensions
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.infrastructure.persistence.qdrant.qdrant_service import QdrantService

PROJECTS = ["CORE"]

DOMAINS = [
    "Sazonalizacao",
    "BalancoEnergetico",
    "PLD",
    "CCEE",
    "BBCE",
    "Contratos",
    "Faturamento",
    "Medicao",
]

CATEGORIES = [
    "FeatureDescription",
    "BusinessRule",
    "DesignPattern",
    "DesignRule",
    "ArchitecturalDecision",
]


async def bootstrap() -> None:
    neo4j = Neo4jService()
    qdrant = QdrantService()
    vector_size = get_embedding_dimensions()

    print("=== Bootstrap do Sistema de Memoria ===\n")

    print(f"[Qdrant] Preparando collection 'memories' ({vector_size}d)...")
    await qdrant.ensure_collection(vector_size=vector_size)
    print("[Qdrant] Collection pronta\n")

    print("[Neo4j] Criando esqueleto semantico...")
    await neo4j.bootstrap(projects=PROJECTS, domains=DOMAINS)
    print(f"[Neo4j] {len(PROJECTS)} projeto(s) criado(s)")
    print(f"[Neo4j] {len(CATEGORIES)} categorias por projeto")
    print(f"[Neo4j] {len(DOMAINS)} dominios registrados\n")

    print("[Verificacao] Contagem de nos por label:")
    async with neo4j.driver.session() as session:
        result = await session.run("MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count")
        async for record in result:
            print(f"  {record['type']}: {record['count']}")

    await neo4j.close()
    print("\nBootstrap completo.")


if __name__ == "__main__":
    asyncio.run(bootstrap())
