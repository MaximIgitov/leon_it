"""Правила достоверности: события и метаданные записи → наблюдения.

Чистые функции без базы: на входе — события интервью, ответы с таймингами и
метаданными ffprobe, на выходе — список наблюдений с уровнем. Так правила
проверяются тестами на граничных случаях, а не «в бою».

Против ложных срабатываний:

* одиночные короткие события (моргнул фокусом, свернул окно на секунду) не
  считаются: у каждого правила есть порог по длительности или числу повторов;
* всё, что объясняется техникой (одна смена устройства до записи, разрыв сети,
  один пропуск хартбита), попадает в факты, а не в наблюдения;
* правила смотрят на окно записи ответа: то, что произошло между вопросами,
  кандидату не в упрёк.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import Any, Literal

Level = Literal["info", "attention", "risk"]

# Порядок важности: по нему считается итоговый уровень интервью.
LEVEL_ORDER: dict[str, int] = {"info": 0, "attention": 1, "risk": 2}

# Пороги подобраны так, чтобы обычное поведение (глянул на часы, поправил окно)
# не превращалось в наблюдение.
AWAY_MIN_MS = 4_000
AWAY_TOTAL_MS = 15_000
AWAY_MIN_COUNT = 2
PASTE_MIN_CHARS = 40
HEARTBEAT_GAP_MS = 20_000
DURATION_MISMATCH_RATIO = 0.25
DURATION_MISMATCH_MIN_MS = 5_000
FACES_MANY_MIN_SAMPLES = 2
FACES_NONE_RATIO = 0.6

# Подписи ПО, которое пишет файл вместо браузера: у записи с камеры в тегах
# контейнера стоит Chrome/Firefox/Core Media, а не Lavf или OBS.
_RECORDER_HINTS = re.compile(r"lavf|obs|ffmpeg|handbrake|xsplit|streamlabs|vmix", re.IGNORECASE)
_BROWSER_HINTS = re.compile(
    r"chrome|chromium|firefox|safari|core\s*media|webkit|edge", re.IGNORECASE
)
# Метки виртуальных камер в названиях устройств.
_VIRTUAL_CAMERA = re.compile(
    r"obs|virtual|manycam|snap\s*camera|droidcam|epoccam|xsplit|camtwist|iriun|e2esoft",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Observation:
    """Наблюдение по интервью или конкретному ответу."""

    code: str
    level: Level
    title: str
    detail: str
    question_index: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level,
            "title": self.title,
            "detail": self.detail,
            "question_index": self.question_index,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class EventRow:
    """Событие интервью в виде, удобном для правил."""

    kind: str
    at_server: datetime
    at_client_ms: int | None = None
    question_index: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnswerRow:
    """Ответ с серверными таймингами и метаданными файла."""

    question_index: int
    attempt: int = 1
    duration_ms: int | None = None
    client_duration_ms: int | None = None
    chunk_count: int = 0
    media_meta: dict[str, Any] = field(default_factory=dict)
    media_content_type: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


def _ms(value: datetime, base: datetime) -> float:
    return (value - base).total_seconds() * 1000


def _windows(events: list[EventRow]) -> dict[int, tuple[datetime, datetime]]:
    """Окна записи по вопросам: от recorder_started до recorder_stopped."""
    windows: dict[int, tuple[datetime, datetime]] = {}
    starts: dict[int, datetime] = {}
    for event in events:
        index = event.question_index
        if index is None:
            continue
        if event.kind == "recorder_started":
            starts[index] = event.at_server
        elif event.kind == "recorder_stopped" and index in starts:
            windows[index] = (starts.pop(index), event.at_server)
    return windows


def _inside(event: EventRow, windows: dict[int, tuple[datetime, datetime]]) -> bool:
    window = windows.get(event.question_index if event.question_index is not None else -1)
    if window is None:
        return False
    start, end = window
    return start <= event.at_server <= end


# ------------------------------------------------------------------ правила


def away_observations(
    events: list[EventRow], windows: dict[int, tuple[datetime, datetime]]
) -> list[Observation]:
    """Уходы с вкладки и потери фокуса во время записи ответа."""
    away_kinds = {"visibility_hidden": "visibility_visible", "window_blur": "window_focus"}
    per_question: dict[int, list[float]] = {}
    open_at: dict[tuple[int, str], datetime] = {}
    for event in events:
        index = event.question_index
        if index is None or not _inside(event, windows):
            continue
        if event.kind in away_kinds:
            open_at[(index, event.kind)] = event.at_server
        elif event.kind in away_kinds.values():
            opener = next(k for k, v in away_kinds.items() if v == event.kind)
            started = open_at.pop((index, opener), None)
            if started is not None:
                per_question.setdefault(index, []).append(_ms(event.at_server, started))
    # Ушёл и не вернулся до конца записи — считаем до конца окна.
    for (index, _kind), started in open_at.items():
        window = windows.get(index)
        if window is not None:
            per_question.setdefault(index, []).append(_ms(window[1], started))

    result: list[Observation] = []
    for index, spans in sorted(per_question.items()):
        long_spans = [span for span in spans if span >= AWAY_MIN_MS]
        total = sum(long_spans)
        if not long_spans:
            continue
        if total < AWAY_TOTAL_MS and len(long_spans) < AWAY_MIN_COUNT:
            continue
        result.append(
            Observation(
                code="away_during_answer",
                level="attention",
                title="Кандидат переключался с вкладки во время ответа",
                detail=(
                    f"Вопрос {index + 1}: окно интервью теряло фокус {len(long_spans)} раз(а), "
                    f"суммарно {total / 1000:.0f} с. Это может быть подсказка на другом экране, "
                    "а может — уведомление или звонок."
                ),
                question_index=index,
                evidence={"count": len(long_spans), "total_ms": int(total)},
            )
        )
    return result


def paste_observations(
    events: list[EventRow], windows: dict[int, tuple[datetime, datetime]]
) -> list[Observation]:
    """Вставка длинного текста во время ответа (важно для вопросов с кодом)."""
    per_question: dict[int, int] = {}
    for event in events:
        if event.kind != "paste" or event.question_index is None:
            continue
        if not _inside(event, windows):
            continue
        length = int(event.payload.get("length") or 0)
        if length >= PASTE_MIN_CHARS:
            per_question[event.question_index] = per_question.get(event.question_index, 0) + length
    return [
        Observation(
            code="paste_during_answer",
            level="attention",
            title="Во время ответа вставляли текст",
            detail=(
                f"Вопрос {index + 1}: вставлено {chars} символов. Для вопроса с кодом это "
                "нормально, если разрешено; для устного ответа стоит уточнить."
            ),
            question_index=index,
            evidence={"chars": chars},
        )
        for index, chars in sorted(per_question.items())
    ]


def device_observations(events: list[EventRow]) -> list[Observation]:
    """Виртуальные камеры и смена устройства во время записи."""
    result: list[Observation] = []
    virtual: set[str] = set()
    for event in events:
        if event.kind != "devices_enumerated":
            continue
        if event.payload.get("virtual_camera"):
            virtual.add("флаг клиента")
        for device in event.payload.get("devices") or []:
            label = str(device.get("label") or device) if isinstance(device, dict) else str(device)
            if _VIRTUAL_CAMERA.search(label):
                virtual.add(label[:120])
    if virtual:
        result.append(
            Observation(
                code="virtual_camera",
                level="risk",
                title="Похоже на виртуальную камеру",
                detail=(
                    "Среди устройств есть виртуальная камера: "
                    + ", ".join(sorted(virtual))
                    + ". Через неё в интервью можно подать заранее записанное видео."
                ),
                evidence={"labels": sorted(virtual)},
            )
        )
    return result


def media_observations(answers: list[AnswerRow]) -> list[Observation]:
    """Метаданные файла: чем записано и совпадает ли длительность."""
    result: list[Observation] = []
    for answer in answers:
        tags = {
            str(key): str(value)
            for key, value in (answer.media_meta.get("tags") or {}).items()
            if value is not None
        }
        joined = " ".join(tags.values())
        if joined and _RECORDER_HINTS.search(joined) and not _BROWSER_HINTS.search(joined):
            result.append(
                Observation(
                    code="foreign_recorder",
                    level="risk",
                    title="Файл записан не браузером",
                    detail=(
                        f"Вопрос {answer.question_index + 1}: в метаданных записи нет подписи "
                        "браузера, зато есть подпись стороннего ПО. Обычно это значит, что файл "
                        "получен не с камеры в комнате интервью."
                    ),
                    question_index=answer.question_index,
                    evidence={"tags": tags},
                )
            )
        server_ms = answer.duration_ms
        client_ms = answer.client_duration_ms
        if server_ms and client_ms:
            diff = abs(server_ms - client_ms)
            if diff >= DURATION_MISMATCH_MIN_MS and diff / max(server_ms, client_ms) >= (
                DURATION_MISMATCH_RATIO
            ):
                result.append(
                    Observation(
                        code="duration_mismatch",
                        level="attention",
                        title="Длительность записи расходится с замером браузера",
                        detail=(
                            f"Вопрос {answer.question_index + 1}: файл длиной "
                            f"{server_ms / 1000:.0f} с, браузер сообщил {client_ms / 1000:.0f} с. "
                            "Чаще всего это сбой записи, но стоит посмотреть ответ целиком."
                        ),
                        question_index=answer.question_index,
                        evidence={"server_ms": server_ms, "client_ms": client_ms},
                    )
                )
    return result


def faces_observations(
    events: list[EventRow], windows: dict[int, tuple[datetime, datetime]]
) -> list[Observation]:
    """Число лиц в кадре по снимкам клиента (если браузер умеет их считать)."""
    samples: dict[int, list[int]] = {}
    for event in events:
        if event.kind != "faces" or event.question_index is None:
            continue
        if not _inside(event, windows):
            continue
        count = event.payload.get("count")
        if isinstance(count, int):
            samples.setdefault(event.question_index, []).append(count)

    result: list[Observation] = []
    for index, counts in sorted(samples.items()):
        many = [value for value in counts if value > 1]
        none = [value for value in counts if value == 0]
        if len(many) >= FACES_MANY_MIN_SAMPLES:
            result.append(
                Observation(
                    code="multiple_faces",
                    level="attention",
                    title="В кадре несколько лиц",
                    detail=(
                        f"Вопрос {index + 1}: на {len(many)} снимках из {len(counts)} видно "
                        "больше одного лица. Возможно, рядом кто-то есть — посмотрите запись."
                    ),
                    question_index=index,
                    evidence={"samples": len(counts), "with_many": len(many)},
                )
            )
        elif counts and len(none) / len(counts) >= FACES_NONE_RATIO:
            result.append(
                Observation(
                    code="no_face",
                    level="attention",
                    title="Кандидата почти не видно в кадре",
                    detail=(
                        f"Вопрос {index + 1}: на {len(none)} снимках из {len(counts)} лицо не "
                        "распознано. Это бывает при плохом свете или если камера отвёрнута."
                    ),
                    question_index=index,
                    evidence={"samples": len(counts), "without_face": len(none)},
                )
            )
    return result


def heartbeat_facts(
    events: list[EventRow], windows: dict[int, tuple[datetime, datetime]]
) -> list[Observation]:
    """Долгие паузы в хартбите: вкладка была заморожена или потеряна сеть."""
    beats = [event for event in events if event.kind == "heartbeat"]
    if not beats:
        # Хартбита нет вовсе: комната его не слала (старая запись, отключённая
        # телеметрия) — судить не о чем, молчим вместо ложного факта.
        return []
    result: list[Observation] = []
    for index, (start, end) in sorted(windows.items()):
        inside = [event.at_server for event in beats if start <= event.at_server <= end]
        marks = [start, *inside, end]
        gaps = [
            _ms(later, earlier)
            for earlier, later in pairwise(marks)
            if _ms(later, earlier) >= HEARTBEAT_GAP_MS
        ]
        if gaps:
            result.append(
                Observation(
                    code="heartbeat_gap",
                    level="info",
                    title="Связь с комнатой прерывалась",
                    detail=(
                        f"Вопрос {index + 1}: пауза в сигналах до {max(gaps) / 1000:.0f} с. "
                        "Обычно это слабая сеть или свёрнутая вкладка."
                    ),
                    question_index=index,
                    evidence={"max_gap_ms": int(max(gaps))},
                )
            )
    return result


def analyze(events: list[EventRow], answers: list[AnswerRow]) -> list[Observation]:
    """Все правила разом; наблюдения отсортированы по важности и вопросам."""
    windows = _windows(events)
    observations = [
        *away_observations(events, windows),
        *paste_observations(events, windows),
        *device_observations(events),
        *media_observations(answers),
        *faces_observations(events, windows),
        *heartbeat_facts(events, windows),
    ]
    return sorted(
        observations,
        key=lambda item: (-LEVEL_ORDER[item.level], item.question_index or -1, item.code),
    )


def summary_level(observations: list[Observation]) -> Level:
    """Итог по интервью: «без замечаний», «обратить внимание» или «высокий риск»."""
    if any(item.level == "risk" for item in observations):
        return "risk"
    if any(item.level == "attention" for item in observations):
        return "attention"
    return "info"


LEVEL_LABELS: dict[str, str] = {
    "info": "без замечаний",
    "attention": "обратить внимание",
    "risk": "высокий риск",
}
