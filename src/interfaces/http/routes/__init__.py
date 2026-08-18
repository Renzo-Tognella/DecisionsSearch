from decisionssearch.interfaces.http.routes.catalog_routes import router as catalog_router
from decisionssearch.interfaces.http.routes.memory_routes import router as memory_router
from decisionssearch.interfaces.http.routes.pr_memory_routes import router as pr_memory_router

__all__ = ["catalog_router", "memory_router", "pr_memory_router"]
