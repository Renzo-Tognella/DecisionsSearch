import asyncio
from unittest.mock import patch

from decisionssearch.application.search.hyde_service import HyDEService


def test_should_expand_short_query():
    with patch("decisionssearch.application.search.hyde_service.get_llm_api_key", return_value=""):
        svc = HyDEService()
    assert svc.should_expand("design")


def test_should_not_expand_long_query():
    with patch("decisionssearch.application.search.hyde_service.get_llm_api_key", return_value=""):
        svc = HyDEService()
    assert not svc.should_expand("how to implement authentication flow with JWT tokens")


def test_expand_without_client_returns_original():
    with patch("decisionssearch.application.search.hyde_service.get_llm_api_key", return_value=""):
        svc = HyDEService()
    result = asyncio.run(svc.expand("short"))
    assert result == "short"


def test_min_query_length_configurable():
    with patch("decisionssearch.application.search.hyde_service.get_llm_api_key", return_value=""):
        svc = HyDEService()
    svc.min_query_length = 5
    assert not svc.should_expand("design patterns")


def test_expand_long_query_returns_original():
    with patch("decisionssearch.application.search.hyde_service.get_llm_api_key", return_value=""):
        svc = HyDEService()
    long_query = "this is a very long query that should not be expanded"
    result = asyncio.run(svc.expand(long_query))
    assert result == long_query


def test_force_expand_overrides_length_gate():
    # Q6: HyDE opt-in pelo caller — força expansão mesmo em query longa.
    with patch("decisionssearch.application.search.hyde_service.get_llm_api_key", return_value=""):
        svc = HyDEService()
    long_query = "how to implement authentication flow with JWT tokens"
    assert not svc.should_expand(long_query)
    assert svc.should_expand(long_query, force=True)
