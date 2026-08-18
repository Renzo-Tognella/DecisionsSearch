from __future__ import annotations

import asyncio
import os

import pytest


@pytest.fixture(scope="module")
def loop():
    """Um único event loop para todo o módulo e2e.

    O driver async do Neo4j (e o cliente Qdrant) ligam recursos ao loop do
    primeiro await. Usar vários ``asyncio.run()`` (um por operação) fechava esse
    loop e quebrava as conexões na chamada seguinte. Um loop compartilhado para
    setup + teste + teardown resolve.
    """
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture(scope="module")
def container(loop):
    if os.getenv("RUN_E2E", "0") != "1":
        pytest.skip("E2E desabilitado. Defina RUN_E2E=1 para executar.")
    from decisionssearch.bootstrap.container import create_container

    c = create_container()
    loop.run_until_complete(c.qdrant.ensure_collection())
    loop.run_until_complete(c.neo4j.bootstrap(projects=["CORE"], domains=["Sazonalizacao"]))
    yield c
    loop.run_until_complete(c.close())
