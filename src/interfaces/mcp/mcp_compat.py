from __future__ import annotations

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
except Exception:  # pragma: no cover
    class FastMCP:  # type: ignore[override]
        def __init__(self, name: str):
            self.name = name

        def tool(self, name: str | None = None):  # noqa: ANN201
            del name

            def decorator(func):
                return func

            return decorator

        def resource(self, uri: str):  # noqa: ANN201
            del uri

            def decorator(func):
                return func

            return decorator

        def prompt(self):  # noqa: ANN201
            def decorator(func):
                return func

            return decorator

        def run(self) -> None:
            return None
