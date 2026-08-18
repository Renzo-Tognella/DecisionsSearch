from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from decisionssearch.interfaces.http.routes import catalog_router, memory_router, pr_memory_router
from decisionssearch.interfaces.http.routes.webhook_routes import router as webhook_router


def create_http_app(container: Any) -> FastAPI:
    app = FastAPI(title="DecisionsSearch Graph Catalog API")
    app.state.container = container
    app.include_router(catalog_router)
    app.include_router(memory_router)
    app.include_router(pr_memory_router)
    app.include_router(webhook_router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
