"""Описание API для OpenAPI и страница интерактивной документации (Scalar).

Страница — статический HTML, который подключает Scalar с CDN и читает
``/api/openapi.json`` того же сервера. Она не зависит от Swagger UI FastAPI:
на проде Swagger выключен, а документация публичного API нужна именно там.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from leonit.api_tokens.deps import API_RATE_LIMIT_PER_MINUTE
from leonit.api_tokens.scopes import SCOPE_DESCRIPTIONS
from leonit.core.deps import SettingsDep
from leonit.core.errors import NotFoundError
from leonit.public_api.router import TAG_CANDIDATES, TAG_INTERVIEWS, TAG_REPORTS, TAG_VACANCIES

SCALAR_CDN_URL = "https://cdn.jsdelivr.net/npm/@scalar/api-reference"

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
подскажет, сколько ждать). Тело ошибки всегда `{{"detail": "…"}}`.

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


def scalar_page(openapi_url: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>LeonIT — публичный API</title>
    <style>body {{ margin: 0; }}</style>
  </head>
  <body>
    <div id="app"></div>
    <script src="{SCALAR_CDN_URL}"></script>
    <script>
      Scalar.createApiReference("#app", {{
        url: "{openapi_url}",
        theme: "default",
        hideDownloadButton: false,
        defaultOpenAllTags: true,
        metaData: {{ title: "LeonIT — публичный API" }},
      }});
    </script>
  </body>
</html>
"""


@router.get("/docs/api", include_in_schema=False, response_class=HTMLResponse)
async def public_api_docs(settings: SettingsDep) -> HTMLResponse:
    if not settings.PUBLIC_API_DOCS_ENABLED:
        raise NotFoundError("Документация отключена")
    return HTMLResponse(scalar_page(f"{settings.API_PREFIX}/openapi.json"))
