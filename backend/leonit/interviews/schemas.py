from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AnswerStatusLiteral = Literal["recording", "uploaded", "processing", "done", "failed", "abandoned"]

# Что клиент может прислать как событие. Список закрыт: неизвестные виды не
# попадают в журнал, чтобы integrity-анализ работал с известной семантикой.
EVENT_KINDS: frozenset[str] = frozenset(
    {
        "heartbeat",
        "visibility_hidden",
        "visibility_visible",
        "window_blur",
        "window_focus",
        "fullscreen_enter",
        "fullscreen_exit",
        "paste",
        "copy",
        "device_change",
        "devices_enumerated",
        "faces",
        "recorder_error",
        "recorder_started",
        "recorder_stopped",
        "reload",
        "mobile_pause",
        "mobile_resume",
        "network_error",
        "practice_completed",
        # Живой диалог: детектор пауз завершил ответ / кандидат так и не заговорил.
        "live_end_of_speech",
        "live_no_speech",
    }
)


class StartRequest(BaseModel):
    client_info: dict[str, Any] = Field(default_factory=dict)


class SnapshotQuestion(BaseModel):
    """Вопрос, как его видит кандидат: без подсказок оценщику."""

    id: str
    index: int
    kind: Literal["video", "code"]
    text: str
    prep_seconds: int
    max_answer_seconds: int
    retakes_allowed: int
    allows_followup: bool


class CodeRunResultOut(BaseModel):
    status: Literal["ok", "error", "timeout"]
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    ran_at: datetime | None = None


class CodeSubmissionOut(BaseModel):
    language: str
    source: str
    submitted_at: datetime | None
    run_result: CodeRunResultOut | None = None


class CodeSubmissionIn(BaseModel):
    """Черновик или отправка кода; размер проверяется сервисом (413 при превышении)."""

    language: str = Field(min_length=1, max_length=32)
    source: str = Field(default="", max_length=4_000_000)
    submit: bool = False


class CodeRunIn(BaseModel):
    language: str = Field(min_length=1, max_length=32)
    source: str = Field(default="", max_length=4_000_000)
    stdin: str = Field(default="", max_length=10_000)


class CodeRunnerOut(BaseModel):
    """Что умеет секция кода на этом стенде: клиент показывает кнопку «Запустить»."""

    enabled: bool
    languages: list[str]
    max_source_bytes: int


class AvatarOut(BaseModel):
    """Аватар интервьюера: enabled=false — комната показывает персону LeonIT."""

    enabled: bool = False
    clip_url: str | None = None
    duration_s: float | None = None


class AnswerOut(BaseModel):
    id: str
    question_index: int
    attempt: int
    is_final: bool
    status: AnswerStatusLiteral
    upload_offset: int
    media_size: int
    duration_ms: int | None
    recording_started_at: datetime
    recording_ended_at: datetime | None
    code_submission: CodeSubmissionOut | None = None


class InterviewState(BaseModel):
    status: str
    current_question_index: int
    total_questions: int
    # Только уже открытые вопросы (текущий включительно): будущие не выдаём.
    questions: list[SnapshotQuestion]
    answers: list[AnswerOut]
    settings: dict[str, Any]
    revealed_at: dict[int, datetime] = Field(default_factory=dict)
    # Пауза до дедлайна ссылки: клиент показывает её на вводном экране.
    expires_at: datetime
    code_runner: CodeRunnerOut


class FollowupStatus(BaseModel):
    """Состояние блока уточняющих вопросов перед финалом интервью."""

    enabled: bool
    ready: bool
    pending: int
    wait_seconds: int


class RevealOut(BaseModel):
    question: SnapshotQuestion
    revealed_at: datetime
    # Подписанная ссылка на озвучку (None — озвучка выключена или недоступна).
    audio_url: str | None
    audio_content_type: str | None
    avatar: AvatarOut = Field(default_factory=AvatarOut)


class AnswerCreate(BaseModel):
    mime_type: str = Field(default="video/webm", max_length=128)


class AnswerCreated(BaseModel):
    answer: AnswerOut
    upload_chunk_max_bytes: int


class AnswerComplete(BaseModel):
    size: int = Field(ge=0)
    client_duration_ms: int | None = Field(default=None, ge=0)
    mime_type: str | None = Field(default=None, max_length=128)


class ClientEvent(BaseModel):
    kind: str = Field(max_length=48)
    at_client_ms: int | None = Field(default=None, ge=0)
    question_index: int | None = Field(default=None, ge=0)
    answer_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EventsBatch(BaseModel):
    events: list[ClientEvent] = Field(max_length=200)


class EventsAccepted(BaseModel):
    accepted: int
    ignored: int


class AnswerDetail(AnswerOut):
    # Видео для плеера (ремукс с перемоткой, если он есть) и извлечённое аудио.
    media_url: str | None
    audio_url: str | None = None
    media_content_type: str | None
    transcript_text: str | None
    transcript_segments: list[dict[str, Any]] | None
    processing_error: str | None
    question_text: str | None
    question_id: str | None
    parent_answer_id: str | None


class InterviewEventOut(BaseModel):
    id: str
    kind: str
    source: str
    question_index: int | None
    answer_id: str | None
    at_client_ms: int | None
    at_server: datetime
    payload: dict[str, Any]
