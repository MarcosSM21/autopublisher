"""In-memory login rate limit (Feature 020 T012, research §12)."""

from datetime import timedelta

from app.auth import (
    MAX_FAILURES_GLOBAL,
    MAX_FAILURES_PER_IP,
    MAX_TRACKED_IPS,
    RATE_WINDOW,
    LoginRateLimiter,
)
from tests.fakes import FakeClock


def test_sixth_failure_from_one_ip_is_blocked() -> None:
    limiter = LoginRateLimiter(FakeClock().now)
    for _ in range(MAX_FAILURES_PER_IP):
        assert not limiter.blocked("10.0.0.1")
        limiter.record_failure("10.0.0.1")
    assert limiter.blocked("10.0.0.1")
    assert not limiter.blocked("10.0.0.2")


def test_global_limit_blocks_every_ip() -> None:
    limiter = LoginRateLimiter(FakeClock().now)
    for index in range(MAX_FAILURES_GLOBAL):
        limiter.record_failure(f"10.0.1.{index}")
    assert limiter.blocked("10.0.9.9")


def test_window_expires_and_never_blocks_forever() -> None:
    clock = FakeClock()
    limiter = LoginRateLimiter(clock.now)
    for _ in range(MAX_FAILURES_GLOBAL):
        limiter.record_failure("10.0.0.1")
    assert limiter.blocked("10.0.0.1")
    clock.advance(RATE_WINDOW.total_seconds() - 1)
    assert limiter.blocked("10.0.0.1")
    clock.advance(1)
    assert not limiter.blocked("10.0.0.1")
    assert limiter.tracked_ips == 0  # pruned


def test_sliding_window_counts_only_recent_failures() -> None:
    clock = FakeClock()
    limiter = LoginRateLimiter(clock.now)
    for _ in range(MAX_FAILURES_PER_IP - 1):
        limiter.record_failure("10.0.0.1")
    clock.advance(timedelta(minutes=10).total_seconds())
    limiter.record_failure("10.0.0.1")
    assert limiter.blocked("10.0.0.1")
    clock.advance(timedelta(minutes=5).total_seconds())  # the first four expire
    assert not limiter.blocked("10.0.0.1")


def test_success_clears_that_ip_only() -> None:
    limiter = LoginRateLimiter(FakeClock().now)
    for _ in range(MAX_FAILURES_PER_IP):
        limiter.record_failure("10.0.0.1")
        limiter.record_failure("10.0.0.2")
    limiter.record_success("10.0.0.1")
    assert not limiter.blocked("10.0.0.1")
    assert limiter.blocked("10.0.0.2")


def test_tracked_ips_stay_bounded() -> None:
    limiter = LoginRateLimiter(FakeClock().now)
    for index in range(MAX_TRACKED_IPS + 50):
        limiter.record_failure(f"ip-{index}")
    assert limiter.tracked_ips == MAX_TRACKED_IPS
