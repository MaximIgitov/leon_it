# LeonIT — бэкенд

FastAPI-монолит: API кабинета и комнаты интервью, фоновые задачи обработки
медиа, шлюз к моделям, интеграции.

## Локальный запуск

Нужны Python 3.12 и [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn leonit.main:app --reload
uv run python -m leonit.jobs.worker      # воркер фоновых задач, отдельный процесс
```

По умолчанию используется SQLite (`./leonit.db`). Для PostgreSQL задайте
`DATABASE_URL=postgresql+asyncpg://user:pass@host/db`.

Проверка: `curl http://localhost:8000/api/health`, документация —
http://localhost:8000/api/docs.

## Проверки

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Тесты не ходят в сеть: `conftest.py` принудительно включает фейковый провайдер
моделей, а HTTP-слой реального провайдера проверяется через `respx`.

## Устройство

```
leonit/
├── main.py         фабрика приложения и реестр роутеров
├── models.py       реестр модулей с моделями (для Alembic и тестов)
├── core/           настройки, БД, ошибки, наблюдаемость, rate limit, хранилище файлов
├── ai/             шлюз к моделям: провайдеры LLM/STT/TTS, structured output, диагностика
├── jobs/           очередь задач в базе и воркер
├── media/          подписанные ссылки на файлы и отдача с Range
├── pipeline/       медиа-пайплайн ответа: ffmpeg, транскрибация, срок хранения
├── hh/             интеграция с HH.ru: OAuth, вакансии, отклики, диалог в чате
└── <area>/         предметные области: models · schemas · service · router
```

Миграции: `uv run alembic revision --autogenerate -m "описание"` после
изменения моделей; каждая миграция должна применяться и на SQLite, и на
PostgreSQL (см. `render_as_batch` в `alembic/env.py`).

### `ai/` — шлюз к моделям

Пять ролей моделей, у каждой своя конфигурация: `evaluator` (заключение по
кандидату), `assistant` (агент в кабинете), `interviewer` (уточняющие вопросы),
`stt` (транскрибация), `tts` (озвучка вопросов). Предметный код получает
провайдера через `leonit.ai.gateway`:

```python
from leonit.ai.gateway import get_llm, get_stt, get_tts
from leonit.ai.structured import complete_structured

conclusion, raw = await complete_structured(get_llm("evaluator"), messages, ConclusionSchema)
transcript = await get_stt().transcribe(audio, content_type="audio/webm", prompt="FastAPI, Django")
```

* `providers/base.py` — абстракции `LLMProvider` (`chat`, `stream_chat`),
  `STTProvider`, `TTSProvider` и ошибки `ProviderConfigurationError` /
  `ProviderUnavailableError` / `ProviderResponseError` (наружу — 502).
* `providers/openai_compatible.py` — любой OpenAI-совместимый API: keep-alive пул
  (`http_client.py`), ретраи с линейным бэкоффом на 408/429/5xx и сетевые ошибки,
  circuit breaker на роль (`circuit_breaker.py`), `json_schema` с фолбэком на
  `json_object`, SSE-стриминг с tool-вызовами, `verbose_json` для таймкодов STT,
  лимит аудио 25 МБ. HTTP 402 пишется в лог как инцидент.
* `providers/fake.py` — детерминированный провайдер без сети для CI и e2e:
  JSON по схеме, tool-вызов по маркеру `[[call:<tool> <json>]]`, сайдкар
  `prompt="sidecar:<текст>"` для STT, WAV-тишина для TTS.
* `structured.py` — JSON по `model_json_schema` с валидацией pydantic и одним
  repair-запросом; сырой ответ возвращается для сохранения.
* `diagnostics.py` — `check_models()` делает крошечный запрос на каждую роль
  (страница «настройки моделей», smoke-тест стенда).
* `tts_cache.py` — озвучка кэшируется в хранилище по хешу текста, голоса и модели.

Переменные окружения (`<ROLE>` — `EVALUATOR`, `ASSISTANT`, `INTERVIEWER`, `STT`, `TTS`):

| Переменная | Назначение |
|---|---|
| `MODEL_PROVIDER` | `openai_compatible` или `fake`. Не задано — `fake`, если ни у одной роли нет ключа, иначе `openai_compatible`. В production `fake` запрещён без `MODEL_ALLOW_FAKE_IN_PRODUCTION=true`. |
| `MODEL_DEFAULT_BASE_URL` | Фолбэк base URL, по умолчанию `https://api.aitunnel.ru/v1` (умеет `/audio/*`, доступен из РФ). |
| `MODEL_DEFAULT_API_KEY`, `MODEL_DEFAULT_PROXY_URL` | Фолбэк ключ и прокси для ролей без своих значений. |
| `MODEL_<ROLE>_BASE_URL`, `MODEL_<ROLE>_API_KEY`, `MODEL_<ROLE>_PROXY_URL` | Настройки конкретной роли (перекрывают фолбэки). |
| `MODEL_<ROLE>_MODEL` | Модель роли. По умолчанию: `claude-sonnet-5` (evaluator, assistant), `claude-haiku-4.5` (interviewer), `gpt-4o-transcribe` (stt), `gpt-4o-mini-tts` (tts). |
| `MODEL_<ROLE>_TIMEOUT_S` | Таймаут запроса роли в секундах. |

### `jobs/` — фоновые задачи

Очередь живёт в таблице `jobs`: постановка попадает в одну транзакцию с
доменным изменением. Воркер захватывает задачи через
`UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED) RETURNING` на PostgreSQL
(на SQLite — то же без блокировок, один воркер), держит аренду `lease_until` и
продлевает её heartbeat-ом; задачи с истёкшей арендой подбираются как зомби.
Ошибка обработчика — повтор с экспоненциальной паузой (5с × 2^attempts, до 10
минут), после `max_attempts` — `failed`; кнопка «Переобработать» —
`service.retry()`. Незарегистрированный `kind` падает без повторов.

```python
from leonit.jobs.registry import job, JobContext
from leonit.jobs import service


@job("media.extract_audio", resource="ffmpeg")  # ресурсы: llm · ffmpeg · default
async def extract_audio(payload: dict, ctx: JobContext) -> dict | None:
    await ctx.heartbeat()  # для долгих шагов без await
    return {"audio_key": ...}


await service.enqueue(
    session, "media.extract_audio", {"answer_id": ...}, dedupe_key=f"audio:{answer_id}"
)
```

Модули с обработчиками перечисляются в `JOB_HANDLER_MODULES`
(`leonit/jobs/registry.py`). Воркер: `python -m leonit.jobs.worker` (флаги
`--once`, `--poll-interval`, `--worker-id`); семафоры по умолчанию — 1 ffmpeg,
3 llm, 4 default; по SIGTERM/SIGINT новые задачи не берутся, текущие
дорабатывают до 60 с, остальные возвращаются в очередь без потери попытки.

Хуки воркера (`jobs/registry.py`): `@on_worker_start` выполняется один раз
после старта (поставить периодическую задачу), `@on_worker_tick` — сразу после
старта и затем раз в `Worker.tick_interval_s` (час) независимо от того, чем
закончились предыдущие задачи: сюда ставят страховку расписаний и возврат
брошенных сущностей в очередь. Сбой хука пишется в лог и не останавливает воркер.

### `core/storage.py` и `media/` — файлы

`Storage` — абстракция над томом (`LocalStorage` под `MEDIA_ROOT`): `put`,
`append(key, data, offset)` для последовательной докачки чанков (несовпадение
смещения — `StorageOffsetConflict` с фактическим размером), `open_range`,
`size`, `exists`, `delete`. Ключи нормализуются, выход за корень запрещён.

Наружу файлы отдаются только по подписанной ссылке:
`sign_media_url(key, ttl_s=900, content_type=..., filename=...)` возвращает
`/api/media/{token}` (JWT с `typ=media`), роутер проверяет подпись и срок и
отдаёт файл потоково с поддержкой `Range` (206 / 416) и `HEAD`.

### `pipeline/` — медиа-пайплайн

Видео на сервере никогда не перекодируется: оригинал ответа хранится как
записал браузер. После `complete` записи в очередь встаёт задача
`answer.process` (ресурс `ffmpeg` — один процесс на воркер), которая делает
четыре шага (`pipeline/service.py`):

1. `ffprobe` → `answer.media_meta`: `duration_s`, `format_name`, кодеки,
   размер кадра, частота кадров, `tags` (`format.encoder`,
   `video.handler_name`, …). По тегам integrity отличает MediaRecorder
   Chrome/Safari от Lavf/OBS/HandBrake — это «истина» о том, чем записан файл.
2. Аудио → `answer.audio_key` (`….ogg` рядом с видео). Opus из WebM копируется
   без перекодирования (`-c:a copy`), остальное (AAC из Safari/iOS) сводится в
   моно 16 кГц Opus 32 кбит/с — достаточно для STT и в разы меньше лимита
   провайдера.
3. Для WebM — ремукс `-c copy` в `….playback.webm` (`media_meta.playback_key`):
   MediaRecorder не пишет длительность и cues, без ремукса перемотка к цитате
   в отчёте не работает. `InterviewRoomService.media_url` отдаёт ремукс, если
   он есть, `audio_url` — аудио (поле `audio_url` в `GET /interviews/{id}/answers`).
   Сбой ремукса обработку не останавливает (`media_meta.playback_error`).
4. STT: `get_stt().transcribe(audio, content_type="audio/ogg",
   language=<язык вакансии>, prompt=<название вакансии и её навыки>)` →
   `transcript_text`, `transcript_segments` (`[{start_s, end_s, text}]`),
   `transcript_language`.

Статусы ответа: `uploaded`/`failed` → `processing` → `done` (`processed_at`)
или `failed` (`processing_error`, до 2000 символов) с пробросом исключения —
очередь повторит задачу с паузой, а повтор корректно стартует из `failed`.
Метаданные, аудио и ремукс коммитятся до вызова STT: если упал провайдер,
аудио у сотрудника уже есть.

Переход в `processing` — один условный `UPDATE` (`claim_answer`): два воркера
не возьмут один ответ, даже если очередь отдала задачу «зомби»-перехватом.
Ответ, который прямо сейчас держит живой воркер, даёт `AnswerBusyError` —
очередь повторит задачу позже. Отмена обработки (graceful stop воркера,
потеря аренды) возвращает ответ в `uploaded` с пометкой в `processing_error`.
Ответ, брошенный в `processing` убитым воркером (SIGKILL, OOM), считается
протухшим, когда `updated_at` старше `PIPELINE_STALE_PROCESSING_S` (30 минут;
пайплайн двигает `updated_at` между шагами): его берёт следующая задача, а
без неё — тик воркера (`pipeline_maintenance`, раз в час) возвращает такие
ответы в `uploaded` и ставит `answer.process` заново. Скопированный Opus
длиннее лимита STT-провайдера (25 МБ) перекодируется в моно 16 кГц
(`media_meta.audio_copied = false`). Если срок хранения сработал, пока шла
обработка, транскрипт сохраняется, а созданные файлы удаляются.

`pipeline/ffmpeg.py` — async-обёртки `probe`, `extract_audio`, `remux` поверх
`asyncio.create_subprocess_exec`: всегда `-hide_banner -loglevel error
-threads 1`, таймаут `FFMPEG_TIMEOUT_S` (10 минут, процесс убивается), на
POSIX — `nice -n 10`, результат пишется во временный файл и переименовывается
атомарно (временное имя случайное, осиротевшие `.part` от убитого воркера
убираются перед новым запуском). Ошибка → `PipelineError` с хвостом stderr, в
котором пути внутри `MEDIA_ROOT` заменены на `<media>` — текст ошибки виден
сотрудникам в карточке ответа. Настройки: `FFMPEG_BIN`, `FFPROBE_BIN`,
`FFMPEG_TIMEOUT_S`, `RETENTION_PURGE_HOUR_UTC`, `PIPELINE_STALE_PROCESSING_S`.
Пайплайн работает с локальным томом (`LocalStorage.path_for`), а читает,
проверяет и удаляет файлы через абстракцию `Storage`.

**Срок хранения.** Задача `retention.purge` (ресурс `default`) для каждой
организации удаляет видео, аудио и ремукс ответов интервью, завершённых
(`completed_at`; для отменённых — `cancelled_at`) раньше, чем
`retention_days` организации; брошенные интервью (`in_progress`, `expired`)
попадают под срок от истечения ссылки (`expires_at`). Ключи обнуляются, в
`media_meta.purged_at` пишется время, транскрипты, метаданные и оценки не
трогаются, каталог `interviews/<id>` удаляется целиком (вместе с осиротевшими
временными файлами), каждое удаление попадает в лог. Ответы в `processing`
пропускаются до следующего прогона. Расписание: воркер на старте ставит чистку
на сегодня (`schedule_daily_purge`: ключ `retention:purge:<дата>`, не раньше
`RETENTION_PURGE_HOUR_UTC`, одна задача в сутки), сама задача ставит
следующую на завтра ещё до начала работы, а тик воркера раз в час проверяет,
что задачи на сегодня и завтра существуют, — цепочка не рвётся, даже если
чистка дня исчерпала попытки. Вручную, мимо очереди:
`uv run python -m leonit.pipeline.purge [--dry-run]`.

Тесты `tests/test_pipeline.py` и `tests/test_pipeline_resilience.py`
генерируют файлы самим ffmpeg (`-f lavfi`, фикстура `samples` в conftest).
Локально без ffmpeg/ffprobe они пропускаются; в CI (`CI=1`) ffmpeg обязателен —
без него модуль падает на импорте, а не пропускает сценарии молча.

### `hh/` — интеграция с HH.ru

OAuth-подключение работодателя, импорт вакансий и откликов, трёхшаговый диалог
с кандидатом в чате HH (приветствие → удобный день → ссылка на интервью) и
связка «кандидат ↔ отклик ↔ интервью». API — `/api/integrations/hh/*`,
страница кабинета — `/integrations/hh`, история диалога показывается в
карточке кандидата.

**Режимы.** Без ключей интеграция работает в `fake`-режиме: `FakeHhClient`
отдаёт работодателя, три вакансии и пять откликов с резюме из
`hh/fixtures/*.json`, а ответы кандидатов заданы сценарием (`replies` у
отклика: k-я реплика «приходит» после k-го сообщения бота; номера зашиты в id
сообщений, поэтому сценарий воспроизводится в любом процессе и после рестарта
воркера). Владелец нажимает «Подключить демо-аккаунт», дальше всё как в
реальном режиме, но без сети. `RealHhClient` (`hh/client.py`) включается при
заданных `HH_CLIENT_ID`/`HH_CLIENT_SECRET`: httpx с таймаутами, обновление
токена по сроку и по 401 (`refresh_token` у HH одноразовый — под замком),
один повтор на 429/5xx с `Retry-After`, `idempotency_key` в отправке
сообщений (409 = уже отправлено). Тесты ходят в него через
`httpx.MockTransport`.

**OAuth.** `POST /oauth/start` (владелец) отдаёт ссылку авторизации с PKCE;
`state` — подписанный JWT на 10 минут с id организации, инициатором, nonce и
зашифрованным `code_verifier`, поэтому до callback ничего не хранится, а
подделанный или просроченный state даёт редирект `…/integrations/hh?status=error`.
`GET /callback` обменивает код, читает `/me`, сохраняет подключение (токены —
только через `SecretBox`) и редиректит на `PUBLIC_URL/integrations/hh?status=connected`.

**Модели** (`hh/models.py`): `HhConnection` (одно на организацию; токены и
секрет вебхука зашифрованы, для поиска по адресу вебхука хранится хеш),
`HhVacancyLink` (вакансия HH ↔ локальная + настройка диалога JSON:
`enabled`, `max_days`, реплики `greeting`/`clarify`/`link` с плейсхолдерами
`{candidate_name}` `{vacancy_title}` `{link}` `{days}` `{date}`),
`HhNegotiation` (отклик: кандидат, интервью, состояние диалога, выбранный
день, история сообщений `[{role: bot|candidate|recruiter, text, at,
hh_message_id, step}]`; уникален по `(connection_id, negotiation_id)`).

**Диалог** (`hh/dialog.py`, `hh/slots.py`). Состояния: `new → greeting_sent →
awaiting_slot → link_sent → done`, ветки `declined` и `needs_recruiter`.
Новый отклик → кандидат из резюме (ФИО, e-mail, телефон, текст резюме,
`source=hh`, без дублей по e-mail в организации; резюме без e-mail получает
синтетический адрес `hh-<id>@candidates.hh.example`, на который письма не
уходят) → приветствие. Ответ кандидата разбирает модель роли `assistant`
(structured output: день / отказ / непонятно), фолбэк — правила («сегодня»,
«завтра», «послезавтра», «через N дней», день недели, дата); всё сверяется с
окном `max_days`. День найден → приглашение через ту же модель `Interview`
(ссылка действует до конца дня, следующего за выбранным; письмо тоже уходит),
ссылка в чат, `link_sent`; не разобрали — переспрос один раз, затем
`needs_recruiter` (кнопка «Взять в работу» отправляет ссылку от имени
рекрутера); отказ — `declined`; завершённое интервью — `done`. Диалог
стартует только для опубликованной локальной вакансии с включённым диалогом;
шаги идемпотентны (ключ `uuid5(отклик, шаг)`, отправленный шаг не
повторяется), повторная синхронизация не создаёт дублей.

**Синхронизация.** Задача `hh.sync` (ресурс `llm`): по всем активным
подключениям тянет новые отклики и сообщения и гоняет диалог. Периодическая
задача ставит следующую сама через `HH_SYNC_INTERVAL_MINUTES`, воркер на старте
и тиком раз в час проверяет, что активная задача есть. Вебхук
`POST /api/integrations/hh/webhook/{secret}` (адрес виден владельцу на
странице интеграции; неверный секрет — 404) и кнопка «Синхронизировать сейчас»
ставят внеочередную задачу организации с dedupe-ключом.

**Права.** Подключение и отключение — владелец (`integrations.manage`);
синхронизация, импорт и привязка вакансий, настройка диалога, «взять в
работу» — владелец и рекрутер (`integrations.operate`); чтение —
`integrations.read`. Нанимающий менеджер — 403 везде.

| Переменная | Назначение |
|---|---|
| `HH_MODE` | `auto` (по умолчанию: `real` при заданных ключах, иначе `fake`), `fake`, `real`. |
| `HH_CLIENT_ID`, `HH_CLIENT_SECRET` | Ключи приложения из dev.hh.ru. |
| `HH_REDIRECT_URL` | Адрес возврата OAuth; по умолчанию `PUBLIC_URL/api/integrations/hh/callback` — его же указывают в настройках приложения HH. |
| `HH_API_BASE`, `HH_OAUTH_BASE` | `https://api.hh.ru` и `https://hh.ru`. |
| `HH_USER_AGENT` | Заголовок `HH-User-Agent`, по умолчанию `LeonIT/1.0 (info@napoleonit.ru)`. |
| `HH_SYNC_INTERVAL_MINUTES` | Период фоновой синхронизации, по умолчанию 10. |

Ограничения: подписка на вебхуки HH не регистрируется автоматически (адрес
задаётся вручную в кабинете разработчика), берутся только входящие отклики
(коллекция `response`), один аккаунт менеджера на организацию, время суток в
ответе кандидата не учитывается — только день.
