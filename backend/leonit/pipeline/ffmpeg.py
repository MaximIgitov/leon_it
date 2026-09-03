"""Async-обёртки над ffmpeg и ffprobe.

Видео на сервере не перекодируется: оригинал ответа остаётся как есть, а
ffmpeg нужен для трёх дешёвых операций — прочитать метаданные, вытащить
аудиодорожку для STT и переупаковать WebM, чтобы в отчёте работала перемотка.
Каждый вызов — отдельный процесс с таймаутом, одним потоком и пониженным
приоритетом: воркер живёт на одной машине с API, и один тяжёлый ffmpeg не
должен отнимать CPU у запросов кабинета.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from leonit.core.config import get_settings

_STDERR_TAIL_CHARS = 2000
_NICE_LEVEL = "10"
# Общие флаги: без баннера и предупреждений (в stderr остаются только ошибки),
# один поток — параллелизм ограничивает семафор воркера, а не сам ffmpeg.
_COMMON_FLAGS: tuple[str, ...] = ("-hide_banner", "-loglevel", "error", "-threads", "1")
# ffprobe показывает Matroska и WebM одним демультиплексором: «matroska,webm».
_WEBM_FORMATS: tuple[str, ...] = ("webm", "matroska")
# Теги, по которым видно, чем записан файл: MediaRecorder Chrome/Firefox пишет
# «Chrome»/«Firefox» в WritingApp, Safari — handler «Core Media», Lavf/OBS/HandBrake
# оставляют свои подписи. Для integrity это «истина» о происхождении записи.
_TAG_KEYS: frozenset[str] = frozenset(
    {
        "encoder",
        "handler_name",
        "muxing_app",
        "writing_app",
        "major_brand",
        "compatible_brands",
        "creation_time",
        "title",
        "comment",
    }
)


class PipelineError(Exception):
    """ffmpeg/ffprobe не справился; в сообщении — хвост stderr (обрезанный)."""

    def __init__(self, detail: str, *, stderr: str = "") -> None:
        super().__init__(detail)
        self.detail = detail
        self.stderr = stderr


@dataclass(slots=True)
class MediaProbe:
    """Сводка ffprobe: то, что нужно отчёту, integrity и выбору стратегии извлечения."""

    duration_s: float | None = None
    format_name: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    size_bytes: int | None = None
    bit_rate: int | None = None
    # «format.encoder», «video.handler_name», «audio.encoder» и т. п.
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def is_webm(self) -> bool:
        names = (self.format_name or "").lower().split(",")
        return any(name.strip() in _WEBM_FORMATS for name in names)

    @property
    def has_audio(self) -> bool:
        return self.audio_codec is not None

    @property
    def has_video(self) -> bool:
        return self.video_codec is not None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def available() -> bool:
    """Есть ли ffmpeg и ffprobe в PATH (или по путям из настроек)."""
    settings = get_settings()
    return bool(shutil.which(settings.FFMPEG_BIN) and shutil.which(settings.FFPROBE_BIN))


def _timeout_s() -> float:
    return float(get_settings().FFMPEG_TIMEOUT_S)


def _command(binary: str, args: Sequence[str]) -> list[str]:
    command = [binary, *_COMMON_FLAGS, *args]
    # На POSIX понижаем приоритет: API на той же машине важнее фоновой обработки.
    if os.name == "posix" and shutil.which("nice"):
        command = ["nice", "-n", _NICE_LEVEL, *command]
    return command


def _tail(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace").strip()
    return text[-_STDERR_TAIL_CHARS:]


async def run(binary: str, args: Sequence[str], *, timeout_s: float | None = None) -> bytes:
    """Запустить ``binary`` с общими флагами; вернуть stdout, при ошибке — PipelineError."""
    command = _command(binary, args)
    timeout = timeout_s if timeout_s is not None else _timeout_s()
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise PipelineError(f"{binary}: исполняемый файл не найден") from error
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        # Зависший процесс не должен пережить обработчик.
        await _kill(process)
        raise PipelineError(f"{binary}: превышен таймаут {int(timeout)} с") from None
    except asyncio.CancelledError:
        # Отмена (остановка воркера, потеря аренды) — не ошибка ffmpeg: процесс
        # убиваем, а отмену пробрасываем, чтобы воркер вернул задачу в очередь.
        await _kill(process)
        raise
    if process.returncode != 0:
        tail = _tail(stderr)
        raise PipelineError(
            f"{binary} завершился с кодом {process.returncode}: {tail or 'без сообщения'}",
            stderr=tail,
        )
    return stdout


async def _run_to_file(args: Sequence[str], dst: Path, *, container: str) -> None:
    """Выполнить ffmpeg с выводом во временный файл и атомарно переименовать.

    Так читатели (плеер отчёта, STT) никогда не увидят недописанный файл, а
    повтор задачи после сбоя начинает с чистого листа. Контейнер задаётся явно,
    потому что по суффиксу «.part» ffmpeg его не угадает.
    """
    temp = dst.with_name(f"{dst.name}.{os.getpid()}.part")
    await asyncio.to_thread(dst.parent.mkdir, parents=True, exist_ok=True)
    try:
        await run(get_settings().FFMPEG_BIN, [*args, "-f", container, "-y", str(temp)])
        await asyncio.to_thread(os.replace, temp, dst)
    finally:
        await asyncio.to_thread(_unlink_quietly, temp)


async def _kill(process: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    await process.wait()


def _unlink_quietly(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


# ------------------------------------------------------------------- probe


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # NaN → None


def _int(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _rate(value: Any) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return _float(value)
    numerator, _, denominator = value.partition("/")
    top, bottom = _float(numerator), _float(denominator)
    if top is None or not bottom:
        return None
    return round(top / bottom, 3)


def parse_probe(payload: dict[str, Any]) -> MediaProbe:
    """Собрать ``MediaProbe`` из JSON ffprobe (``-show_format -show_streams``)."""
    fmt = payload.get("format") or {}
    streams = [s for s in payload.get("streams") or [] if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise PipelineError("ffprobe: в файле нет ни видео, ни аудио")
    duration = _float(fmt.get("duration"))
    for stream in (video, audio):
        if duration is None and stream is not None:
            duration = _float(stream.get("duration"))
    tags: dict[str, str] = {}
    for scope, node in (("format", fmt), ("video", video), ("audio", audio)):
        for key, value in ((node or {}).get("tags") or {}).items():
            name = str(key).lower()
            if name in _TAG_KEYS:
                tags[f"{scope}.{name}"] = str(value)[:200]
    return MediaProbe(
        duration_s=round(duration, 3) if duration is not None else None,
        format_name=fmt.get("format_name"),
        video_codec=(video or {}).get("codec_name"),
        audio_codec=(audio or {}).get("codec_name"),
        width=_int((video or {}).get("width")),
        height=_int((video or {}).get("height")),
        frame_rate=_rate((video or {}).get("avg_frame_rate")),
        audio_sample_rate=_int((audio or {}).get("sample_rate")),
        audio_channels=_int((audio or {}).get("channels")),
        size_bytes=_int(fmt.get("size")),
        bit_rate=_int(fmt.get("bit_rate")),
        tags=tags,
    )


async def probe(path: Path | str) -> MediaProbe:
    stdout = await run(
        get_settings().FFPROBE_BIN,
        ["-print_format", "json", "-show_format", "-show_streams", str(path)],
    )
    try:
        payload = json.loads(stdout or b"{}")
    except ValueError as error:
        raise PipelineError("ffprobe: ответ не JSON") from error
    if not isinstance(payload, dict):
        raise PipelineError("ffprobe: неожиданный формат ответа")
    return parse_probe(payload)


# -------------------------------------------------------------- extraction


def audio_codec_args(source: MediaProbe) -> tuple[list[str], bool]:
    """Аргументы кодека для извлечения аудио и признак «дорожка скопирована как есть».

    Opus из WebM (MediaRecorder в Chrome/Firefox) кладём в Ogg без перекодирования:
    это бесплатно и без потерь. Всё остальное (AAC из Safari/iOS, PCM) сводим в
    моно 16 кГц Opus 32 кбит/с — этого достаточно для распознавания речи, а
    файл получается в разы меньше лимита STT-провайдера.
    """
    if source.audio_codec == "opus" and source.is_webm:
        return ["-c:a", "copy"], True
    return ["-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k"], False


async def extract_audio(
    src: Path | str, dst: Path | str, *, source: MediaProbe | None = None
) -> bool:
    """Извлечь аудио в Ogg/Opus по пути ``dst``; вернуть, была ли дорожка скопирована."""
    source = source if source is not None else await probe(src)
    if not source.has_audio:
        raise PipelineError("в записи нет аудиодорожки")
    codec_args, copied = audio_codec_args(source)
    await _run_to_file(
        ["-nostdin", "-i", str(src), "-vn", "-map", "0:a:0", *codec_args],
        Path(dst),
        container="ogg",
    )
    return copied


async def remux(src: Path | str, dst: Path | str) -> None:
    """Переупаковать WebM без перекодирования.

    MediaRecorder пишет поток «вживую»: в заголовке нет длительности и cues,
    поэтому браузер не может перемотать к цитате. ``-c copy`` переписывает
    контейнер с индексом, а кадры остаются байт в байт теми же.
    """
    await _run_to_file(
        ["-nostdin", "-i", str(src), "-map", "0", "-c", "copy"], Path(dst), container="webm"
    )
