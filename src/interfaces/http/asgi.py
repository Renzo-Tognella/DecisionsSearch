from __future__ import annotations

import logging
from contextlib import asynccontextmanager, nullcontext
from typing import Any

from fastapi import FastAPI

from decisionssearch.bootstrap.container import ServiceContainer, create_container
from decisionssearch.interfaces.http.http_app import create_http_app
from decisionssearch.interfaces.mcp.main import create_app as create_mcp_app

logger = logging.getLogger(__name__)


def _build_mcp_http_app(container: ServiceContainer) -> Any:
    mcp_app = create_mcp_app(container=container, streamable_http_path="/")
    streamable_http_app = getattr(mcp_app, "streamable_http_app", None)
    if callable(streamable_http_app):
        return streamable_http_app()

    fallback = FastAPI(title="DecisionsSearch Memory Server MCP")

    @fallback.get("/")
    async def root() -> dict[str, str]:
        return {"status": "ok"}

    return fallback


def _lifespan_context(app: Any):
    router = getattr(app, "router", None)
    lifespan_context = getattr(router, "lifespan_context", None)
    if callable(lifespan_context):
        return lifespan_context(app)
    return nullcontext()


def create_asgi_app(
    container: ServiceContainer | None = None,
    http_app: FastAPI | None = None,
    mcp_app: Any | None = None,
) -> FastAPI:
    owns_container = container is None
    if container is None:
        container = create_container()
        from decisionssearch.bootstrap.container import wire_error_pipeline
        wire_error_pipeline(container)

    resolved_http_app = http_app or create_http_app(container)
    resolved_mcp_app = mcp_app or _build_mcp_http_app(container)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info("DecisionsSearch Memory Server iniciando")
        async with _lifespan_context(resolved_mcp_app):
            try:
                reranker = getattr(getattr(container, "search", None), "reranker", None)
                if reranker and hasattr(reranker, "warmup"):
                    try:
                        await reranker.warmup()
                    except Exception:  # pragma: no cover - warmup é best-effort
                        logger.warning("Reranker warmup falhou", exc_info=True)
                scheduler = getattr(container, "scheduler", None)
                if scheduler and hasattr(scheduler, "start"):
                    await scheduler.start()
                yield
            finally:
                if owns_container:
                    logger.info("Encerrando container de serviços")
                    await container.close()

    app = FastAPI(title="DecisionsSearch Memory Server", lifespan=lifespan)
    app.state.container = container

    app.state.http_app = resolved_http_app
    app.state.mcp_app = resolved_mcp_app

    app.mount("/api", app.state.http_app)
    app.mount("/mcp", app.state.mcp_app)

    return app


app = create_asgi_app()


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
