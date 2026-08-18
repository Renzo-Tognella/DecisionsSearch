from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from decisionssearch.infrastructure.ai.reranking.reranking_service import (
    CohereReranker,
    CrossEncoderReranker,
    JinaReranker,
    NoOpReranker,
    OpenAIReranker,
    OpenRouterReranker,
    create_reranker,
)


def test_noop_reranker_returns_documents_unchanged() -> None:
    reranker = NoOpReranker()
    docs = [
        {"memory_id": "mem-1", "title": "First", "score": 0.8},
        {"memory_id": "mem-2", "title": "Second", "score": 0.5},
    ]
    result = asyncio.run(reranker.rerank(query="test query", documents=docs, top_k=10))
    assert result == docs
    assert len(result) == 2


def test_noop_reranker_respects_top_k() -> None:
    reranker = NoOpReranker()
    docs = [{"title": f"doc-{i}"} for i in range(10)]
    result = asyncio.run(reranker.rerank(query="test", documents=docs, top_k=3))
    assert len(result) == 3


def test_create_reranker_returns_noop_for_unknown_provider(monkeypatch) -> None:
    monkeypatch.setenv("RERANKER_PROVIDER", "none")
    assert isinstance(create_reranker(provider="none"), NoOpReranker)
    assert isinstance(create_reranker(provider="unknown"), NoOpReranker)
    assert isinstance(create_reranker(provider=""), NoOpReranker)


def test_create_reranker_returns_cross_encoder() -> None:
    reranker = create_reranker(provider="local")
    assert isinstance(reranker, CrossEncoderReranker)


def test_create_reranker_returns_cross_encoder_bge() -> None:
    reranker = create_reranker(provider="bge")
    assert isinstance(reranker, CrossEncoderReranker)


def test_create_reranker_cohere_fallback_without_key() -> None:
    with patch.dict("os.environ", {}, clear=False):
        reranker = create_reranker(provider="cohere")
    assert isinstance(reranker, NoOpReranker)


def test_create_reranker_jina_fallback_without_key() -> None:
    with patch.dict("os.environ", {}, clear=False):
        reranker = create_reranker(provider="jina")
    assert isinstance(reranker, NoOpReranker)


def test_create_reranker_openrouter_fallback_without_key() -> None:
    with patch.dict("os.environ", {}, clear=True):
        reranker = create_reranker(provider="openrouter")
    assert isinstance(reranker, NoOpReranker)


def test_create_reranker_returns_openrouter() -> None:
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}, clear=False):
        reranker = create_reranker(provider="openrouter")
    assert isinstance(reranker, OpenRouterReranker)


def test_create_reranker_returns_openai() -> None:
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
        reranker = create_reranker(provider="openai")
    assert isinstance(reranker, OpenAIReranker)


def test_openrouter_reranker_accepts_generic_key_only_when_llm_is_openrouter() -> None:
    with patch.dict(
        "os.environ",
        {"LLM_PROVIDER": "openrouter", "LLM_API_KEY": "generic-or-key"},
        clear=True,
    ):
        reranker = OpenRouterReranker()
    assert reranker.api_key == "generic-or-key"


def test_cross_encoder_extract_text() -> None:
    reranker = CrossEncoderReranker()
    assert reranker._extract_text({"title": "T", "summary": "S"}) == "T | S"
    assert reranker._extract_text({"title": "T"}) == "T"
    assert reranker._extract_text({"summary": "S"}) == "S"
    assert reranker._extract_text({"details": "D" * 500}) != ""
    assert reranker._extract_text({}) == ""


def test_cross_encoder_rerank_empty() -> None:
    reranker = CrossEncoderReranker()
    result = asyncio.run(reranker.rerank(query="test", documents=[], top_k=5))
    assert result == []


def test_cohere_extract_text() -> None:
    with patch.dict("os.environ", {"COHERE_API_KEY": "test-key"}):
        reranker = CohereReranker()
    assert reranker._extract_text({"title": "T", "summary": "S"}) == "T | S"


def test_jina_extract_text() -> None:
    with patch.dict("os.environ", {"JINA_API_KEY": "test-key"}):
        reranker = JinaReranker()
    assert reranker._extract_text({"title": "T", "summary": "S"}) == "T | S"


def test_cohere_rerank_api_call() -> None:
    with patch.dict("os.environ", {"COHERE_API_KEY": "test-key"}):
        reranker = CohereReranker()

    docs = [
        {"memory_id": "m1", "title": "Rule A", "summary": "About auth"},
        {"memory_id": "m2", "title": "Rule B", "summary": "About database"},
    ]

    async def fake_rerank():
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.6},
            ]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            return await reranker.rerank(query="auth", documents=docs, top_k=5)

    result = asyncio.run(fake_rerank())
    assert len(result) == 2
    assert result[0]["memory_id"] == "m2"
    assert result[0]["rerank_score"] == 0.95


def test_jina_rerank_api_call() -> None:
    with patch.dict("os.environ", {"JINA_API_KEY": "test-key"}):
        reranker = JinaReranker()

    docs = [
        {"memory_id": "m1", "title": "Rule A", "summary": "About caching"},
        {"memory_id": "m2", "title": "Rule B", "summary": "About security"},
    ]

    async def fake_rerank():
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.88},
                {"index": 1, "relevance_score": 0.45},
            ]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            return await reranker.rerank(query="caching", documents=docs, top_k=5)

    result = asyncio.run(fake_rerank())
    assert len(result) == 2
    assert result[0]["memory_id"] == "m1"
    assert result[0]["rerank_score"] == 0.88


def test_openrouter_rerank_api_call_uses_native_endpoint_and_headers() -> None:
    environment = {
        "OPENROUTER_API_KEY": "test-key",
        "OPENROUTER_HTTP_REFERER": "https://decisionssearch.test",
        "OPENROUTER_APP_TITLE": "DecisionsSearch tests",
        "OPENROUTER_RERANK_MODEL": "cohere/rerank-v3.5",
        "OPENROUTER_RERANK_ZDR": "true",
    }
    with patch.dict(
        "os.environ",
        environment,
        clear=False,
    ):
        reranker = OpenRouterReranker()

    docs = [
        {"memory_id": "m1", "title": "Rule A", "summary": "About caching"},
        {"memory_id": "m2", "title": "Rule B", "summary": "About security"},
    ]

    async def fake_rerank():
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 1, "relevance_score": 0.91},
                {"index": 0, "relevance_score": 0.44},
            ]
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await reranker.rerank(query="security", documents=docs, top_k=2)
        return result, mock_client

    with patch.dict("os.environ", environment, clear=False):
        result, client = asyncio.run(fake_rerank())

    assert [doc["memory_id"] for doc in result] == ["m2", "m1"]
    assert result[0]["rerank_score"] == 0.91
    _, kwargs = client.post.call_args
    assert client.post.call_args.args[0] == "https://openrouter.ai/api/v1/rerank"
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["headers"]["HTTP-Referer"] == "https://decisionssearch.test"
    assert kwargs["headers"]["X-Title"] == "DecisionsSearch tests"
    assert kwargs["json"]["model"] == "cohere/rerank-v3.5"
    assert kwargs["json"]["provider"] == {"zdr": True}


def test_openai_rerank_api_call_uses_structured_chat_output() -> None:
    with patch.dict(
        "os.environ",
        {"OPENAI_API_KEY": "test-key", "OPENAI_RERANK_MODEL": "gpt-test"},
        clear=True,
    ):
        reranker = OpenAIReranker()

    docs = [
        {"memory_id": "m1", "title": "Rule A", "summary": "About caching"},
        {"memory_id": "m2", "title": "Rule B", "summary": "About security"},
    ]
    response = MagicMock()
    response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "ranking": [
                            {"index": 1, "score": 0.91},
                            {"index": 0, "score": 0.44},
                        ]
                    }
                )
            )
        )
    ]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    client.close = AsyncMock()

    async def fake_rerank():
        with patch("openai.AsyncOpenAI", return_value=client):
            return await reranker.rerank(query="security", documents=docs, top_k=2)

    result = asyncio.run(fake_rerank())

    assert [doc["memory_id"] for doc in result] == ["m2", "m1"]
    assert result[0]["rerank_score"] == 0.91
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-test"
    assert kwargs["temperature"] == 0
    assert kwargs["response_format"]["type"] == "json_schema"
    client.close.assert_awaited_once()


def test_openai_rerank_rejects_incomplete_ranking() -> None:
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
        reranker = OpenAIReranker()

    docs = [
        {"memory_id": "m1", "title": "Rule A"},
        {"memory_id": "m2", "title": "Rule B"},
    ]
    response = MagicMock()
    response.choices = [
        MagicMock(message=MagicMock(content='{"ranking": [{"index": 0, "score": 1}]}'))
    ]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    client.close = AsyncMock()

    async def fake_rerank():
        with patch("openai.AsyncOpenAI", return_value=client):
            return await reranker.rerank(query="security", documents=docs, top_k=2)

    result = asyncio.run(fake_rerank())

    assert result == docs
    assert reranker.failure_count == 1
    assert reranker.success_count == 0


def test_reranker_abstraction_exists() -> None:
    from decisionssearch.application.ports.abstractions import Reranker

    assert hasattr(Reranker, "rerank")
