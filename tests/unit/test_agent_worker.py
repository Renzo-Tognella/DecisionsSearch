from __future__ import annotations

import pytest
from decisionssearch.infrastructure.agents.agent_worker import (
    AgentResult,
    OpenCodeWorker,
    CodexWorker,
    ClaudeWorker,
    OpenRouterWorker,
    create_agent_worker,
    _extract_json,
)


class TestAgentResult:
    def test_default_values(self):
        r = AgentResult(success=True)
        assert r.output == ""
        assert r.extracted == {}


class TestExtractJson:
    def test_json_code_block(self):
        text = 'some output\n```json\n{"status": "fixed", "confidence": 0.9}\n```\nend'
        result = _extract_json(text)
        assert result["status"] == "fixed"
        assert result["confidence"] == 0.9

    def test_bare_json(self):
        text = 'result: {"status": "needs_human"}'
        result = _extract_json(text)
        assert result["status"] == "needs_human"

    def test_no_json(self):
        assert _extract_json("no json here") == {}


class TestCodexWorker:
    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        worker = CodexWorker(api_key="")
        result = await worker.run("test prompt")
        assert result.success is False
        assert "OPENAI_API_KEY" in result.error


class TestClaudeWorker:
    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        worker = ClaudeWorker(api_key="")
        result = await worker.run("test prompt")
        assert result.success is False
        assert "ANTHROPIC_API_KEY" in result.error


class TestOpenRouterWorker:
    @pytest.mark.asyncio
    async def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        worker = OpenRouterWorker(api_key="")
        result = await worker.run("test prompt")
        assert result.success is False
        assert "OPENROUTER_API_KEY" in result.error


class TestCreateAgentWorker:
    def test_create_opencode(self):
        worker = create_agent_worker({"provider": "opencode", "workdir": "/tmp"})
        assert isinstance(worker, OpenCodeWorker)

    def test_create_codex(self):
        worker = create_agent_worker({"provider": "codex", "codex": {"api_key": "sk-test"}})
        assert isinstance(worker, CodexWorker)

    def test_create_claude(self):
        worker = create_agent_worker({"provider": "claude", "claude": {"api_key": "sk-ant-test"}})
        assert isinstance(worker, ClaudeWorker)

    def test_create_openrouter(self):
        worker = create_agent_worker(
            {"provider": "openrouter", "openrouter": {"api_key": "sk-or-test"}}
        )
        assert isinstance(worker, OpenRouterWorker)

    def test_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown agent provider"):
            create_agent_worker({"provider": "unknown"})
