from __future__ import annotations

import pytest

from leonit.core.config import Settings
from leonit.core.rate_limit import SlidingWindowRateLimiter


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET="change-me-local-only",
            CORS_ORIGINS=["https://example.com"],
        )


def test_production_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValueError, match="32 characters"):
        Settings(ENVIRONMENT="production", JWT_SECRET="short", CORS_ORIGINS=["https://example.com"])


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValueError, match="Wildcard"):
        Settings(ENVIRONMENT="production", JWT_SECRET="x" * 40, CORS_ORIGINS=["*"])


def test_public_url_trailing_slash_is_stripped() -> None:
    assert Settings(PUBLIC_URL="https://leonit.example/").PUBLIC_URL == "https://leonit.example"


def test_sync_database_url_variants() -> None:
    assert (
        Settings(DATABASE_URL="postgresql+asyncpg://u:p@h/db").sync_database_url
        == "postgresql://u:p@h/db"
    )
    assert Settings(DATABASE_URL="sqlite+aiosqlite:///./x.db").sync_database_url == (
        "sqlite:///./x.db"
    )


def test_rate_limiter_blocks_after_budget_and_reports_retry_after() -> None:
    limiter = SlidingWindowRateLimiter(max_attempts=2, window_s=60)
    assert limiter.check("k").allowed
    assert limiter.check("k").allowed
    decision = limiter.check("k")
    assert not decision.allowed
    assert decision.retry_after_s >= 1
    limiter.reset("k")
    assert limiter.check("k").allowed


def test_rate_limiter_evicts_stalest_half_when_full() -> None:
    limiter = SlidingWindowRateLimiter(max_attempts=1, window_s=60, max_keys=4)
    for key in "abcd":
        limiter.check(key)
    limiter.check("e")
    assert len(limiter._attempts) <= 4
