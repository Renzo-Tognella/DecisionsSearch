from __future__ import annotations

import os
from typing import TYPE_CHECKING

from decisionssearch.interfaces.mcp.mcp_compat import FastMCP

if TYPE_CHECKING:
    from decisionssearch.bootstrap.container import ServiceContainer


class LazyMCPApp:
    def __init__(self) -> None:
        self._app: FastMCP | None = None

    def _resolve(self) -> FastMCP:
        if self._app is None:
            self._app = create_app()
        return self._app

    def __getattr__(self, name: str):
        return getattr(self._resolve(), name)


def create_app(
    container: ServiceContainer | None = None,
    *,
    streamable_http_path: str = "/mcp",
) -> FastMCP:
    try:
        app = FastMCP(
            "DecisionsSearch Memory Server",
            streamable_http_path=streamable_http_path,
        )
    except TypeError:
        app = FastMCP("DecisionsSearch Memory Server")

    try:
        from decisionssearch.interfaces.mcp.prompts import register_prompts
        from decisionssearch.interfaces.mcp.resources import register_resources
        from decisionssearch.interfaces.mcp.tools import register_operator_tools, register_tools
    except ImportError:
        # Permite import do módulo sem dependências externas opcionais.
        return app

    from decisionssearch.bootstrap.container import create_container

    active_container = container or create_container()
    register_tools(app, active_container)
    if os.getenv("DECISIONSSEARCH_ENABLE_OPERATOR_TOOLS", "false").strip().lower() in {"1", "true", "yes"}:
        register_operator_tools(app, active_container)
    register_resources(app, active_container)
    register_prompts(app)
    return app


app = LazyMCPApp()


if __name__ == "__main__":
    app.run()


def main() -> None:
    app.run()
