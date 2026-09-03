from __future__ import annotations

import pytest
from httpx import AsyncClient

from leonit.core.observability import MetricsRegistry, metrics


async def test_response_carries_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.headers["x-request-id"]


async def test_incoming_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-ID": "trace-123"})
    assert response.headers["x-request-id"] == "trace-123"


async def test_malformed_incoming_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-ID": "bad id\n"})
    assert response.headers["x-request-id"] != "bad id\n"
    assert response.headers["x-request-id"].isalnum()


async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


async def test_health_probes_do_not_count_as_requests(client: AsyncClient) -> None:
    await client.get("/api/health")
    await client.get("/api/ready")
    assert metrics.snapshot()["counters"].get("http_requests_total", 0) == 0


async def test_regular_requests_are_counted(client: AsyncClient) -> None:
    await client.get("/api/does-not-exist")
    counters = metrics.snapshot()["counters"]
    assert counters["http_requests_total"] == 1
    assert counters["http_requests_4xx"] == 1


@pytest.mark.parametrize(
    ("value_ms", "bucket"),
    [(10, "50"), (50, "50"), (51, "100"), (99_999, "inf")],
)
def test_histogram_buckets(value_ms: float, bucket: str) -> None:
    registry = MetricsRegistry()
    registry.observe_ms("x", value_ms)
    snapshot = registry.snapshot()["latency"]["x"]
    assert snapshot["count"] == 1
    assert snapshot["buckets"][bucket] == 1
