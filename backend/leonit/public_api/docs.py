"""Описание API для OpenAPI и страница интерактивной документации (Scalar).

Страница — статический HTML, который подключает Scalar с CDN и читает
``/api/openapi.json`` того же сервера. Она не зависит от Swagger UI FastAPI:
на проде Swagger выключен, а документация публичного API нужна именно там.

Страница живёт на одном origin с кабинетом, где сессионный JWT лежит в
localStorage, поэтому чужой скрипт здесь — XSS на кабинет. Отсюда три меры:
версия бандла зафиксирована, тег ``<script>`` несёт Subresource Integrity, а
ответ — Content-Security-Policy, которая разрешает только этот бандл и нашу
инлайн-инициализацию по хешу.
"""

from __future__ import annotations

import base64
import hashlib
import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from leonit.api_tokens.deps import (
    API_AUTH_FAILURE_WINDOW_S,
    API_AUTH_FAILURES_PER_WINDOW,
    API_RATE_LIMIT_PER_MINUTE,
)
from leonit.api_tokens.scopes import SCOPE_DESCRIPTIONS
from leonit.core.deps import SettingsDep
from leonit.core.errors import NotFoundError
from leonit.public_api.router import TAG_CANDIDATES, TAG_INTERVIEWS, TAG_REPORTS, TAG_VACANCIES

# Версия @scalar/api-reference зафиксирована: «latest» с CDN — это исполняемый код
# третьей стороны, который меняется без нашего ведома. При обновлении версии
# пересчитайте SRI-хеш бандла:
#   curl -sL "$SCALAR_CDN_URL" | openssl dgst -sha384 -binary | openssl base64 -A
SCALAR_VERSION = "1.67.0"
SCALAR_CDN_URL = f"https://cdn.jsdelivr.net/npm/@scalar/api-reference@{SCALAR_VERSION}/dist/browser/standalone.js"
SCALAR_SRI = "sha384-6c7Vmx+i0yi8gBbltn0x1cavD+zsMGw2xmXXVyacPJLIGBxwaVimW5TW0WiW17Ir"
SCALAR_CDN_ORIGIN = "https://cdn.jsdelivr.net"

_SCOPES_TABLE = "\n".join(
    f"| `{scope}` | {description} |" for scope, description in SCOPE_DESCRIPTIONS.items()
)

API_DESCRIPTION = f"""
LeonIT — платформа асинхронного видеоинтервью с ИИ-оценкой кандидатов.
Публичный API версии **v1** (`/api/v1/…`) предназначен для интеграций: ATS,
HR-ботов, скриптов импорта. Ручки без префикса `/v1` — внутренний API кабинета,
их контракт не гарантируется.

## Аутентификация

Каждый запрос к `/api/v1` передаёт API-токен организации в заголовке:

```
Authorization: Bearer leonit_<токен>
```

Токен выпускает владелец организации в кабинете («Интеграции → API»). Он
показывается один раз при создании и хранится только хешем: потерянный токен
нужно отозвать и выпустить новый. Токен привязан к организации и ограничен
**областями** — набором того, что ему разрешено. Область не может быть шире
прав того, кто выпустил токен.

| Область | Что даёт |
|---|---|
{_SCOPES_TABLE}

Ответы об ошибках: `401` — токен отсутствует, не найден, отозван или просрочен;
`403` — не хватает области; `404` — объект не в вашей организации; `429` — превышен
лимит **{API_RATE_LIMIT_PER_MINUTE} запросов в минуту на токен** (заголовок `Retry-After`
подскажет, сколько ждать). После {API_AUTH_FAILURES_PER_WINDOW} неудачных попыток
аутентификации за {API_AUTH_FAILURE_WINDOW_S // 60} минут адрес получает `429` ещё до
проверки токена. Тело ошибки всегда `{{"detail": "…"}}`.

## Сценарий интеграции

1. `GET /api/v1/vacancies?status=published` — выбрать вакансию.
2. `POST /api/v1/interviews` — пригласить кандидата; из ответа взять `link`
   (показывается один раз) или положиться на письмо (`send_email`).
3. Опрашивать `GET /api/v1/interviews/{{id}}`, пока `status` не станет
   `evaluated` (или выше).
4. `GET /api/v1/interviews/{{id}}/report` — забрать заключение и транскрипты;
   `GET /api/v1/vacancies/{{id}}/ranking` — сравнить кандидатов.

Ссылки на медиа в отчёте подписаны и живут 15 минут — не сохраняйте их.
Идентификаторы — UUID, время — ISO 8601 в UTC.
""".strip()

OPENAPI_TAGS = [
    {"name": TAG_VACANCIES, "description": "Вакансии: список, карточка, черновик."},
    {"name": TAG_CANDIDATES, "description": "Кандидаты организации."},
    {"name": TAG_INTERVIEWS, "description": "Приглашения и статусы интервью."},
    {"name": TAG_REPORTS, "description": "Заключения, транскрипты, ранжирование."},
]

router = APIRouter(tags=["docs"])


def _inline_script(openapi_url: str) -> str:
    """Инициализация Scalar. Текст хешируется для CSP — менять вместе с тестом."""
    return f"""
      Scalar.createApiReference('#app', {{
        url: {json.dumps(openapi_url)},
        theme: 'default',
        defaultOpenAllTags: true,
        // Запросы «попробовать» идут на этот же сервер, а не через proxy.scalar.com:
        // их пропускает connect-src 'self', а токен не уходит третьей стороне.
        proxyUrl: '',
        metaData: {{ title: 'LeonIT — публичный API' }},
      }});
    """


def content_security_policy(inline_script: str) -> str:
    """CSP страницы документации.

    Скрипты — только пиненный бандл с CDN (плюс SRI в теге) и наш инлайн по
    sha256-хешу, без ``'unsafe-inline'``. Стили Scalar вставляет инлайном,
    шрифты подгружает с fonts.scalar.com по ``@font-face``, картинки в описании
    могут быть внешними — отсюда остальные директивы.
    """
    digest = base64.b64encode(hashlib.sha256(inline_script.encode("utf-8")).digest()).decode()
    return "; ".join(
        (
            "default-src 'none'",
            f"script-src {SCALAR_CDN_ORIGIN} 'sha256-{digest}'",
            "style-src 'self' 'unsafe-inline'",
            "img-src data: https:",
            "connect-src 'self'",
            "font-src https: data:",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        )
    )


def scalar_page(openapi_url: str) -> tuple[str, str]:
    """HTML страницы и значение Content-Security-Policy для неё."""
    script = _inline_script(openapi_url)
    html = f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>LeonIT — публичный API</title>
    <style>body {{ margin: 0; }}</style>
  </head>
  <body>
    <div id="app"></div>
    <script src="{SCALAR_CDN_URL}" integrity="{SCALAR_SRI}" crossorigin="anonymous"></script>
    <script>{script}</script>
  </body>
</html>
"""
    return html, content_security_policy(script)


@router.get("/docs/api", include_in_schema=False, response_class=HTMLResponse)
async def public_api_docs(settings: SettingsDep) -> HTMLResponse:
    if not settings.PUBLIC_API_DOCS_ENABLED:
        raise NotFoundError("Документация отключена")
    html, csp = scalar_page(f"{settings.API_PREFIX}/openapi.json")
    return HTMLResponse(html, headers={"Content-Security-Policy": csp})
