import time
from decisionssearch.application.shared.rate_limiter import RateLimiter


def test_allows_within_limit():
    limiter = RateLimiter(max_calls=5, window_seconds=1.0)
    for _ in range(5):
        assert limiter.allow("memory.query")


def test_blocks_over_limit():
    limiter = RateLimiter(max_calls=2, window_seconds=60.0)
    limiter.allow("memory.query")
    limiter.allow("memory.query")
    assert not limiter.allow("memory.query")


def test_separate_keys_independent():
    limiter = RateLimiter(max_calls=1, window_seconds=60.0)
    assert limiter.allow("memory.query")
    assert limiter.allow("memory.upsert")
    assert not limiter.allow("memory.query")


def test_window_resets():
    limiter = RateLimiter(max_calls=1, window_seconds=0.0)
    limiter.allow("memory.query")
    time.sleep(0.01)
    assert limiter.allow("memory.query")
