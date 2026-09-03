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
├── dashboard/      агрегаты по интервью: воронка, сроки, баллы, согласие с ИИ
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

### `core/storage.py` и `media/` — файлы

`Storage` — абстракция над томом (`LocalStorage` под `MEDIA_ROOT`): `put`,
`append(key, data, offset)` для последовательной докачки чанков (несовпадение
смещения — `StorageOffsetConflict` с фактическим размером), `open_range`,
`size`, `exists`, `delete`. Ключи нормализуются, выход за корень запрещён.

Наружу файлы отдаются только по подписанной ссылке:
`sign_media_url(key, ttl_s=900, content_type=..., filename=...)` возвращает
`/api/media/{token}` (JWT с `typ=media`), роутер проверяет подпись и срок и
отдаёт файл потоково с поддержкой `Range` (206 / 416) и `HEAD`.

### `dashboard/` — метрики организации и вакансии

Три ручки под правом `dashboard.read` (у нанимающего менеджера — только по
допущенным вакансиям, периметр берётся из `visible_vacancy_ids`):

| Ручка | Что возвращает |
|---|---|
| `GET /dashboard/overview` | Сводка по организации. |
| `GET /dashboard/vacancies/{id}` | Та же сводка по одной вакансии (плюс `vacancy`). |
| `GET /dashboard/timeseries?vacancy_id=` | Ряд по дням: приглашено / завершено / оценено. |

Период задаётся `from` и `to` (ISO-даты, без зоны — UTC); без параметров —
последние 30 дней, `all_time=true` снимает нижнюю границу. У ряда по дням есть
`tz_offset_minutes` (как `-Date.getTimezoneOffset()`), чтобы дни считались в
зоне пользователя.

Все цифры выводятся из таймстемпов интервью (`invited_at … decided_at`), без
отдельной таблицы событий:

* **воронка** `invited → opened → consented → started → completed → evaluated →
  decided` — когортная: интервью попадает в период по `invited_at`, дальше
  считается, до какого шага оно дошло; у каждого шага конверсия с предыдущего
  и от приглашённых;
* `completion_rate`, медианы `median_time_to_complete_h` (приглашение →
  завершение) и `median_time_to_result_h` (завершение → заключение),
  `avg_retakes` (перезаписи зачётных ответов);
* `recommendation_breakdown` (`fit / no_fit / needs_check`),
  `decision_breakdown` (`advance / reject / hold / pending`, где `pending` —
  завершили, решения нет), `avg_fit_score`;
* `ai_agreement` — доля решений «дальше»/«отказ», совпавших с рекомендацией
  (`advance ↔ fit`, `reject ↔ no_fit`); «пауза» и «нужна проверка» не считаются
  позицией и в пары не попадают, число пар — `ai_agreement_pairs`;
* `flags_rate` — доля интервью с integrity-флагами; до PR 13 плана всегда 0;
* `active_vacancies`, `interviews_last_7d / _30d` — «пульс» без учёта периода.

Ряд по дням, в отличие от воронки, считает события по их собственным датам:
завершение сегодня относится к сегодняшнему дню, даже если пригласили месяц
назад. Дни без событий заполняются нулями.

Модуль оценки подключается через `evaluation_model()` (импорт
`leonit.evaluation.models.Evaluation` в try/except, контракт колонок —
`interview_id`, `fit_score`, `recommendation`); без него `evaluation_available`
= false, а баллы и согласие с ИИ пустые. SQL — только переносимые агрегаты
(`count` / `case`): в SQLite нет `percentile_cont` и `date_trunc`, а интервью в
организации немного, поэтому медианы и разбивка по дням считаются в Python по
выборке значений.
