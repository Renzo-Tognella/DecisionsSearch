from decisionssearch.application.search.matryoshka_search_service import MatryoshkaSearchService


def test_truncate_embedding():
    svc = MatryoshkaSearchService()
    full = [0.1] * 768
    truncated = svc.truncate_embedding(full, 64)
    assert len(truncated) == 64


def test_truncate_normalizes():
    svc = MatryoshkaSearchService()
    full = [3.0, 4.0, 0.0] + [0.0] * 765
    truncated = svc.truncate_embedding(full, 3)
    norm_sq = sum(x * x for x in truncated)
    assert abs(norm_sq - 1.0) < 0.001


def test_coarse_top_k():
    svc = MatryoshkaSearchService()
    assert svc.compute_coarse_top_k(10) == 100


def test_should_use_multi_stage():
    svc = MatryoshkaSearchService()
    assert svc.should_use_multi_stage([0.1] * 768, 10)
    assert not svc.should_use_multi_stage([0.1] * 100, 10)
    assert not svc.should_use_multi_stage([0.1] * 768, 3)


def test_get_stage_params():
    svc = MatryoshkaSearchService()
    params = svc.get_stage_params(10)
    assert len(params) == 4
    assert params[0]["dimensions"] == 64
    assert params[0]["top_k"] == 100
    assert params[-1]["dimensions"] is None
    assert params[-1]["top_k"] == 10
