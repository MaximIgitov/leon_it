"""Реестр раннеров кода.

Как подключить реальный раннер:

* **Внешний сервис (Piston, Judge0).** Реализовать ``CodeRunner`` в
  ``leonit/code_runner/runners/<name>.py``: ``run`` отправляет исходник в API
  через ``httpx.AsyncClient(timeout=...)`` и переводит ответ в ``RunResult``
  (статус, stdout/stderr, код выхода, длительность). Ключ сервиса — из
  настроек (``CODE_RUNNER_<NAME>_API_KEY``), не из БД; если ключ всё же
  хранится в БД — только через ``leonit.core.crypto.SecretBox``.
* **Своя песочница (docker / firecracker).** Та же реализация протокола, но
  ``run`` поднимает одноразовый контейнер с образом под язык, без сети, с
  лимитами CPU/памяти/pids и убивает его по ``timeout_s`` (``status="timeout"``).
  Запуск стоит вынести в задачу воркера (ресурс ``default``), а ручка комнаты
  тогда ставит задачу и отдаёт результат по опросу.

Затем ``register_code_runner("piston", PistonRunner.from_settings)``, имя —
в ``CodeRunnerKind`` Literal в ``leonit.core.config``, и ``CODE_RUNNER=piston``.
Валидацию языка и размера ручка делает до раннера (``CODE_LANGUAGES``,
``CODE_MAX_SOURCE_BYTES``), поэтому реализация получает уже проверенный ввод.
"""

from __future__ import annotations

from collections.abc import Callable

from leonit.code_runner.base import CodeRunner, NullCodeRunner
from leonit.core.config import Settings, get_settings

RunnerFactory = Callable[[Settings], CodeRunner]

_factories: dict[str, RunnerFactory] = {"none": lambda _settings: NullCodeRunner()}


def register_code_runner(name: str, factory: RunnerFactory) -> None:
    _factories[name] = factory


def registered_code_runners() -> list[str]:
    return sorted(_factories)


def get_code_runner(settings: Settings | None = None) -> CodeRunner:
    settings = settings or get_settings()
    factory = _factories.get(settings.CODE_RUNNER)
    if factory is None:
        raise ValueError(
            f"unknown code runner {settings.CODE_RUNNER!r}; registered: {registered_code_runners()}"
        )
    return factory(settings)
