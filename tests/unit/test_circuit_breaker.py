import asyncio
from decisionssearch.application.shared.circuit_breaker import CircuitBreaker, CircuitState


def test_initial_state_is_closed():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    assert cb.state == CircuitState.CLOSED


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_rejects_calls_when_open():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    cb.record_failure()
    assert not cb.allow_request()


def test_allows_calls_when_closed():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    assert cb.allow_request()


def test_half_open_after_recovery_timeout():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
    cb.record_failure()
    assert cb.allow_request()
    assert cb.state == CircuitState.HALF_OPEN


def test_success_resets_to_closed():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
    cb.record_failure()
    cb.allow_request()
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_protects_async_call():
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
    for _ in range(4):
        try:
            asyncio.run(cb.call(flaky))
        except RuntimeError:
            pass
    assert call_count == 2
