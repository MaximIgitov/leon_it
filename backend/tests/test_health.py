from __future__ import annotations

from httpx import AsyncClient

from leonit.core.config import Settings


async def test_health_is_alive(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_checks_database(client: AsyncClient) -> None:
    response = await client.get("/api/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["media_disk_free_mb"] > 0


async def test_metrics_open_outside_production(client: AsyncClient) -> None:
    await client.get("/api/health")
    response = await client.get("/api/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "counters" in body and "latency" in body


def test_metrics_hidden_in_production_without_token() -> None:
    settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET="x" * 40,
        CORS_ORIGINS=["https://example.com"],
        METRICS_TOKEN=None,
        DATA_ENCRYPTION_KEY="k",
        MODEL_PROVIDER="openai_compatible",
        MODEL_DEFAULT_API_KEY="test-key",
    )
    assert settings.is_production
    assert settings.METRICS_TOKEN is None
