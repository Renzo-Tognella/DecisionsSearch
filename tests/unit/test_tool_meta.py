from __future__ import annotations

import asyncio
import inspect

from decisionssearch.interfaces.mcp.tools import TOOL_SURFACE_VERSION, deprecated_tool
from decisionssearch.infrastructure.ai.reranking.reranking_service import NoOpReranker, create_reranker


def test_tool_surface_version_present():
    assert TOOL_SURFACE_VERSION


def test_deprecated_tool_injects_migration_metadata():
    @deprecated_tool("memory.create_sync")
    async def old_tool(x: int) -> dict:
        return {"x": x}

    result = asyncio.run(old_tool(1))
    assert result["_deprecated"] is True
    assert "memory.create_sync" in result["_migration"]
    assert result["x"] == 1


def test_deprecated_tool_preserves_signature():
    @deprecated_tool("new")
    async def old(project: str, top_k: int = 10) -> dict:
        return {}

    params = list(inspect.signature(old).parameters)
    assert params == ["project", "top_k"]


def test_noop_reranker_warmup_is_noop():
    reranker = NoOpReranker()
    assert asyncio.run(reranker.warmup()) is None


def test_create_reranker_defaults_to_noop():
    assert isinstance(create_reranker("none"), NoOpReranker)
    assert isinstance(create_reranker("bogus-provider"), NoOpReranker)
