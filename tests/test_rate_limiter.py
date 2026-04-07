"""Testes para SlidingWindowRateLimiter."""

import time

import pytest
from src.services.rate_limiter import SlidingWindowRateLimiter


def test_allows_requests_within_limit():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        allowed, _ = limiter.is_allowed("client1")
        assert allowed is True


def test_blocks_after_limit():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.is_allowed("client1")
    allowed, retry_after = limiter.is_allowed("client1")
    assert allowed is False
    assert retry_after > 0


def test_different_clients_independent():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    limiter.is_allowed("client1")
    limiter.is_allowed("client1")
    allowed_1, _ = limiter.is_allowed("client1")
    allowed_2, _ = limiter.is_allowed("client2")
    assert allowed_1 is False
    assert allowed_2 is True


def test_window_expiry():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=1)
    limiter.is_allowed("client1")
    limiter.is_allowed("client1")
    allowed, _ = limiter.is_allowed("client1")
    assert allowed is False
    time.sleep(1.1)
    allowed, _ = limiter.is_allowed("client1")
    assert allowed is True


def test_retry_after_is_positive():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.is_allowed("c1")
    _, retry_after = limiter.is_allowed("c1")
    assert retry_after >= 1
