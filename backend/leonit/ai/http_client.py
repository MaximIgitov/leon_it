"""Общие HTTP-клиенты к провайдерам моделей.

Один ``httpx.AsyncClient`` на пару (base_url, proxy): keep-alive пул экономит
TLS-рукопожатие на каждом запросе, а роли с одним агрегатором делят
соединения. Таймаут задаётся на запрос, потому что у ролей он разный.
"""

from __future__ import annotations

import httpx

_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

_clients: dict[tuple[str, str | None], httpx.AsyncClient] = {}


def get_http_client(base_url: str, proxy_url: str | None = None) -> httpx.AsyncClient:
    key = (base_url.rstrip("/"), proxy_url or None)
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            base_url=key[0],
            proxy=proxy_url or None,
            limits=_LIMITS,
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=False,
        )
        _clients[key] = client
    return client


async def close_http_clients() -> None:
    """Закрыть пулы (lifespan приложения, остановка воркера)."""
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        await client.aclose()


def forget_http_clients() -> None:
    """Забыть клиентов без закрытия: для тестов, где event loop уже другой."""
    _clients.clear()
