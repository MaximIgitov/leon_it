"""Наблюдаемость без внешних зависимостей.

* ``request_id_var`` — contextvar с идентификатором запроса; фильтр логгера
  добавляет его в каждую строку, так что один запрос прослеживается через все
  сервисы (загрузка → транскрибация → оценка).
* ``RequestContextMiddleware`` — чистый ASGI: присваивает/пробрасывает
  ``X-Request-ID``, меряет время, пишет access-лог и метрики.
* ``MetricsRegistry`` — счётчики и гистограммы латентности для ``/metrics``.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from time import perf_counter
from typing import Any
from uuid import uuid4

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
access_log = logging.getLogger("leonit.access")

_QUIET_PATH_SUFFIXES = ("/health", "/ready", "/metrics")
LATENCY_BUCKETS_MS = (50, 100, 250, 500, 1000, 2500, 5000, 10000)


class MetricsRegistry:
    """Счётчики и гистограммы в памяти процесса (один event loop — без блокировок)."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._histograms: dict[str, dict[str, Any]] = {}

    def increment(self, name: str, value: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value

    def observe_ms(self, name: str, value_ms: float) -> None:
        histogram = self._histograms.get(name)
        if histogram is None:
            histogram = {
                "count": 0,
                "sum_ms": 0.0,
                "max_ms": 0.0,
                "buckets": dict.fromkeys([*LATENCY_BUCKETS_MS, "inf"], 0),
            }
            self._histograms[name] = histogram
        histogram["count"] += 1
        histogram["sum_ms"] += value_ms
        histogram["max_ms"] = max(histogram["max_ms"], value_ms)
        for bound in LATENCY_BUCKETS_MS:
            if value_ms <= bound:
                histogram["buckets"][bound] += 1
                break
        else:
            histogram["buckets"]["inf"] += 1

    def snapshot(self) -> dict[str, Any]:
        latency = {}
        for name, histogram in self._histograms.items():
            count = histogram["count"]
            latency[name] = {
                "count": count,
                "avg_ms": round(histogram["sum_ms"] / count, 1) if count else 0.0,
                "max_ms": round(histogram["max_ms"], 1),
                "buckets": {str(key): value for key, value in histogram["buckets"].items()},
            }
        return {"counters": dict(self._counters), "latency": latency}

    def reset(self) -> None:
        self._counters.clear()
        self._histograms.clear()


metrics = MetricsRegistry()


def _incoming_request_id(scope) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == b"x-request-id":
            candidate = value.decode("latin-1").strip()[:64]
            if candidate and all(ch.isalnum() or ch in "-_." for ch in candidate):
                return candidate
    return None


class RequestContextMiddleware:
    """ASGI middleware: correlation id + access-лог + метрики запросов."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = perf_counter()
        status_holder = {"status": 500}

        async def send_with_request_id(message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = (perf_counter() - started) * 1000
            path = scope.get("path", "")
            if not path.endswith(_QUIET_PATH_SUFFIXES):
                status = status_holder["status"]
                metrics.increment("http_requests_total")
                if status >= 500:
                    metrics.increment("http_requests_5xx")
                elif status >= 400:
                    metrics.increment("http_requests_4xx")
                metrics.observe_ms("http_request_ms", duration_ms)
                access_log.info(
                    "%s %s status=%s duration_ms=%s",
                    scope.get("method", "?"),
                    path,
                    status,
                    int(duration_ms),
                )
            request_id_var.reset(token)


class RequestIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True
