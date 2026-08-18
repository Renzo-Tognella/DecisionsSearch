from __future__ import annotations

from decisionssearch.application.search.composite_scorer import CompositeScorer


def test_high_rrf_and_recent_gives_high_score():
    scorer = CompositeScorer()
    result = scorer.score(
        rrf_score=0.03,
        updated_at="2026-04-10T00:00:00Z",
        effective_weight=0.9,
        significance=0.9,
    )
    assert result > 0.5


def test_low_rrf_gives_lower_score():
    scorer = CompositeScorer()
    high = scorer.score(rrf_score=0.05, effective_weight=0.9, significance=0.9)
    low = scorer.score(rrf_score=0.001, effective_weight=0.9, significance=0.9)
    assert high > low


def test_old_memory_gets_recency_penalty():
    scorer = CompositeScorer()
    recent = scorer.score(rrf_score=0.02, updated_at="2026-04-10T00:00:00Z")
    old = scorer.score(rrf_score=0.02, updated_at="2025-01-01T00:00:00Z")
    assert recent > old


def test_no_updated_at_gives_default():
    scorer = CompositeScorer()
    result = scorer.score(rrf_score=0.02)
    assert 0.0 <= result <= 1.0


def test_weights_sum_to_one():
    scorer = CompositeScorer()
    total = scorer.relevance_weight + scorer.recency_weight + scorer.importance_weight
    assert abs(total - 1.0) < 0.01


def test_vector_score_overrides_saturated_rrf_relevance():
    # Mesmo rrf (que satura), mas cosseno denso alto vs baixo -> discrimina.
    scorer = CompositeScorer()
    high = scorer.score(rrf_score=0.02, vector_score=0.9, effective_weight=0.5, significance=0.5)
    low = scorer.score(rrf_score=0.02, vector_score=0.2, effective_weight=0.5, significance=0.5)
    assert high > low


def test_falls_back_to_rrf_when_no_vector_score():
    # Itens só-grafo (sem cosseno) continuam usando o RRF normalizado.
    scorer = CompositeScorer()
    high = scorer.score(rrf_score=0.05, vector_score=None)
    low = scorer.score(rrf_score=0.001, vector_score=None)
    assert high > low


def test_composite_scorer_from_env_defaults(monkeypatch):
    for var in (
        "SCORER_RELEVANCE_WEIGHT",
        "SCORER_RECENCY_WEIGHT",
        "SCORER_IMPORTANCE_WEIGHT",
        "SCORER_RECENCY_HALF_LIFE_DAYS",
    ):
        monkeypatch.delenv(var, raising=False)
    scorer = CompositeScorer.from_env()
    assert scorer.relevance_weight == 0.50
    assert scorer.recency_half_life_days == 90.0


def test_composite_scorer_from_env_override(monkeypatch):
    monkeypatch.setenv("SCORER_RELEVANCE_WEIGHT", "0.65")
    monkeypatch.setenv("SCORER_RECENCY_WEIGHT", "0.15")
    monkeypatch.setenv("SCORER_IMPORTANCE_WEIGHT", "0.20")
    scorer = CompositeScorer.from_env()
    assert scorer.relevance_weight == 0.65
    assert scorer.recency_weight == 0.15
