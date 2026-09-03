"""Базовые security-заголовки для каждого ответа API.

API отдаёт JSON и медиафайлы, поэтому консервативный набор безопасен глобально:
без MIME-sniffing, без встраивания во фреймы, без утечки referrer провайдерам и
без кеширования авторизованных ответов промежуточными прокси.
"""

from __future__ import annotations

SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                existing = {key.lower() for key, _ in headers}
                for key, value in SECURITY_HEADERS:
                    if key not in existing:
                        headers.append((key, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
