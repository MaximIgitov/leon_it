"""Медиа-пайплайн: ffmpeg-обёртки, обработка ответа, срок хранения.

Файлы генерируются самим ffmpeg (lavfi), поэтому тесты не тянут бинарные
фикстуры в репозиторий; без ffmpeg/ffprobe в PATH модуль пропускается.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from leonit.accounts.models import Organization
from leonit.ai.providers.base import STTProvider, Transcript, TranscriptSegment
from leonit.candidates.models import Interview
from leonit.core.db import get_session_maker
from leonit.core.storage import get_storage
from leonit.core.time import utcnow
from leonit.interviews.models import Answer, AnswerStatus
from leonit.interviews.service import ANSWER_PROCESS_JOB, InterviewRoomService
from leonit.jobs.models import Job, JobStatus
from leonit.jobs.registry import JobContext, get_handler, load_all_handlers, startup_hooks
from leonit.jobs.worker import Worker
from leonit.media.service import verify_media_token
from leonit.pipeline import ffmpeg
from leonit.pipeline.ffmpeg import MediaProbe, PipelineError, audio_codec_args, parse_probe
from leonit.pipeline.jobs import process_answer_job, schedule_purge_on_start
from leonit.pipeline.service import (
    RETENTION_PURGE_JOB,
    audio_key_for,
    playback_key_for,
    process_answer,
    purge_expired_media,
    schedule_daily_purge,
    stt_prompt,
)
from tests.helpers import bearer
from tests.test_candidates import _invite, _token
from tests.test_interview_room import _consented

FFMPEG_AVAILABLE = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe не найдены в PATH")


def _generate(path: Path, *codec_args: str) -> Path:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=320x240:rate=10",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        *codec_args,
        "-shortest",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def samples(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if not FFMPEG_AVAILABLE:
        pytest.skip("ffmpeg/ffprobe не найдены в PATH")
    root = tmp_path_factory.mktemp("samples")
    return {
        "webm": _generate(root / "sample.webm", "-c:v", "libvpx", "-c:a", "libopus"),
        # Стерео AAC: проверяем, что извлечение сводит в моно.
        "mp4": _generate(root / "sample.mp4", "-ac", "2", "-c:v", "libx264", "-c:a", "aac"),
    }


# ------------------------------------------------------------ ffmpeg-обёртки


@needs_ffmpeg
async def test_probe_reports_streams_and_tags(samples: dict[str, Path]) -> None:
    webm = await ffmpeg.probe(samples["webm"])
    assert webm.is_webm and webm.has_audio and webm.has_video
    assert webm.video_codec == "vp8" and webm.audio_codec == "opus"
    assert (webm.width, webm.height) == (320, 240)
    assert webm.duration_s is not None and 1.5 <= webm.duration_s <= 2.5
    assert webm.frame_rate == 10.0 and webm.audio_channels == 1
    assert webm.tags["format.encoder"].startswith("Lavf")
    assert webm.as_dict()["format_name"] == "matroska,webm"

    mp4 = await ffmpeg.probe(samples["mp4"])
    assert not mp4.is_webm
    assert mp4.video_codec == "h264" and mp4.audio_codec == "aac" and mp4.audio_channels == 2
    assert "mp4" in (mp4.format_name or "")
    assert mp4.tags["video.handler_name"] == "VideoHandler"


def test_parse_probe_handles_partial_payloads() -> None:
    with pytest.raises(PipelineError):
        parse_probe({"format": {}, "streams": []})
    audio_only = parse_probe(
        {
            "format": {"format_name": "ogg", "duration": "NaN"},
            "streams": [{"codec_type": "audio", "codec_name": "opus", "duration": "3.5"}],
        }
    )
    assert audio_only.duration_s == 3.5 and not audio_only.has_video
    assert audio_codec_args(MediaProbe(format_name="matroska,webm", audio_codec="opus"))[1]
    args, copied = audio_codec_args(MediaProbe(format_name="mov,mp4", audio_codec="aac"))
    assert not copied and args[:4] == ["-ac", "1", "-ar", "16000"]


@needs_ffmpeg
async def test_extract_audio_copies_opus_and_transcodes_aac(
    samples: dict[str, Path], tmp_path: Path
) -> None:
    copied = await ffmpeg.extract_audio(samples["webm"], tmp_path / "copy.ogg")
    assert copied is True
    result = await ffmpeg.probe(tmp_path / "copy.ogg")
    assert result.format_name == "ogg" and result.audio_codec == "opus" and not result.has_video

    transcoded = await ffmpeg.extract_audio(samples["mp4"], tmp_path / "nested" / "tc.ogg")
    assert transcoded is False
    result = await ffmpeg.probe(tmp_path / "nested" / "tc.ogg")
    assert result.audio_codec == "opus" and result.audio_channels == 1
    assert result.duration_s is not None and 1.5 <= result.duration_s <= 2.5
    assert not list(tmp_path.rglob("*.part"))


@needs_ffmpeg
async def test_remux_keeps_streams(samples: dict[str, Path], tmp_path: Path) -> None:
    await ffmpeg.remux(samples["webm"], tmp_path / "playback.webm")
    result = await ffmpeg.probe(tmp_path / "playback.webm")
    assert result.is_webm and result.video_codec == "vp8" and result.audio_codec == "opus"
    assert result.duration_s is not None and 1.5 <= result.duration_s <= 2.5


@needs_ffmpeg
async def test_ffmpeg_errors_become_pipeline_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.webm"
    broken.write_bytes(b"\x1aE\xdf\xa3" + bytes(range(256)) * 8)
    with pytest.raises(PipelineError) as info:
        await ffmpeg.probe(broken)
    assert "ffprobe" in str(info.value) and info.value.stderr
    with pytest.raises(PipelineError):
        await ffmpeg.remux(broken, tmp_path / "out.webm")
    assert not (tmp_path / "out.webm").exists()
    with pytest.raises(PipelineError, match="таймаут"):
        await ffmpeg.run(
            "ffmpeg", ["-f", "lavfi", "-i", "anullsrc", "-f", "null", "-"], timeout_s=0.01
        )


def test_stt_prompt_and_keys() -> None:
    prompt = stt_prompt(" Python-разработчик ", ["FastAPI", "fastapi", " ", "PostgreSQL"])
    assert prompt == "Собеседование на вакансию «Python-разработчик». Термины: FastAPI, PostgreSQL."
    assert stt_prompt("", []) == ""
    assert len(stt_prompt("x", [f"skill{i}" for i in range(500)])) <= 600
    key = "interviews/abc/q00-a1-xyz.webm"
    assert audio_key_for(key) == "interviews/abc/q00-a1-xyz.ogg"
    assert playback_key_for(key) == "interviews/abc/q00-a1-xyz.playback.webm"


# --------------------------------------------------------------- обработчик


async def _upload_file(client: AsyncClient, link: str, index: int, path: Path, mime: str) -> dict:
    created = await client.post(
        f"/api/public/invitations/{link}/questions/{index}/answers", json={"mime_type": mime}
    )
    assert created.status_code == 201, created.text
    answer = created.json()["answer"]
    data = path.read_bytes()
    uploaded = await client.patch(
        f"/api/public/invitations/{link}/answers/{answer['id']}/chunks",
        content=data,
        headers={"Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"},
    )
    assert uploaded.status_code == 200, uploaded.text
    completed = await client.post(
        f"/api/public/invitations/{link}/answers/{answer['id']}/complete",
        json={"size": len(data), "client_duration_ms": 2000},
    )
    assert completed.status_code == 200, completed.text
    return completed.json()


async def _started(client: AsyncClient) -> tuple[str, dict, str, str]:
    token, interview, link, vacancy_id = await _consented(client)
    assert (await client.post(f"/api/public/invitations/{link}/start", json={})).status_code == 200
    await client.post(f"/api/public/invitations/{link}/questions/0/reveal")
    return token, interview, link, vacancy_id


def _context() -> JobContext:
    async def heartbeat() -> bool:
        return True

    return JobContext(
        job_id=uuid.uuid4(),
        kind=ANSWER_PROCESS_JOB,
        attempt=1,
        worker_id="w-pipeline",
        session_maker=get_session_maker(),
        _heartbeat=heartbeat,
    )


class _SpySTT(STTProvider):
    """Запоминает, что именно пайплайн отправил в STT: байты, тип, язык, подсказку."""

    model = "spy-stt"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        language: str = "ru",
        prompt: str | None = None,
    ) -> Transcript:
        self.calls.append(
            {"audio": audio, "content_type": content_type, "language": language, "prompt": prompt}
        )
        text = "Я писал сервисы на FastAPI."
        return Transcript(
            text=text, segments=[TranscriptSegment(0.0, 1.5, text)], language="russian"
        )


async def _answer(answer_id: str) -> Answer:
    async with get_session_maker()() as session:
        answer = await session.get(Answer, uuid.UUID(answer_id))
        assert answer is not None
        return answer


def test_answer_process_is_registered_in_pipeline() -> None:
    load_all_handlers()
    handler = get_handler(ANSWER_PROCESS_JOB)
    assert handler is not None and handler.resource == "ffmpeg"
    assert handler.func is process_answer_job
    assert get_handler(RETENTION_PURGE_JOB) is not None
    assert schedule_purge_on_start in startup_hooks()


@needs_ffmpeg
async def test_process_answer_webm_end_to_end(
    client: AsyncClient, samples: dict[str, Path]
) -> None:
    token, interview, link, _ = await _started(client)
    uploaded = await _upload_file(client, link, 0, samples["webm"], "video/webm;codecs=vp8,opus")

    result = await process_answer_job(
        {"answer_id": uploaded["id"], "interview_id": interview["id"]}, _context()
    )
    assert result is not None and result["audio_copied"] is True

    answer = await _answer(uploaded["id"])
    assert answer.status == AnswerStatus.done and answer.processed_at is not None
    assert answer.processing_error is None
    assert "фейковая транскрипция" in (answer.transcript_text or "")
    assert answer.transcript_language == "ru"
    assert answer.transcript_segments and set(answer.transcript_segments[0]) == {
        "start_s",
        "end_s",
        "text",
    }
    meta = answer.media_meta
    assert meta["video_codec"] == "vp8" and meta["audio_codec"] == "opus"
    assert 1.5 <= meta["duration_s"] <= 2.5
    assert meta["audio_copied"] is True and meta["stt_model"]
    assert answer.audio_key == audio_key_for(answer.media_key)
    assert meta["playback_key"] == playback_key_for(answer.media_key)
    storage = get_storage()
    assert await storage.exists(answer.audio_key) and await storage.exists(meta["playback_key"])

    # Повторный запуск ничего не делает: ответ уже done.
    again = await process_answer_job({"answer_id": uploaded["id"]}, _context())
    assert again is not None and again["skipped"] == "status is done"

    # Сотрудник получает ссылку на ремукс (перемотка) и на аудио.
    listed = await client.get(f"/api/interviews/{interview['id']}/answers", headers=bearer(token))
    assert listed.status_code == 200, listed.text
    detail = next(item for item in listed.json() if item["id"] == uploaded["id"])
    assert detail["status"] == "done" and detail["transcript_text"] == answer.transcript_text
    assert verify_media_token(detail["media_url"].rsplit("/", 1)[-1]).key == meta["playback_key"]
    video = await client.get(detail["media_url"], headers={"Range": "bytes=0-3"})
    assert video.status_code == 206 and video.headers["content-type"] == "video/webm"
    audio = await client.get(detail["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/ogg"


@needs_ffmpeg
async def test_process_answer_mp4_transcodes_audio_without_remux(
    client: AsyncClient, samples: dict[str, Path]
) -> None:
    token, _, link, vacancy_id = await _started(client)
    skills = await client.patch(
        f"/api/vacancies/{vacancy_id}",
        json={"skills": ["FastAPI", "PostgreSQL"]},
        headers=bearer(token),
    )
    assert skills.status_code == 200, skills.text
    uploaded = await _upload_file(client, link, 0, samples["mp4"], "video/mp4")
    spy = _SpySTT()
    async with get_session_maker()() as session:
        result = await process_answer(session, uuid.UUID(uploaded["id"]), stt=spy)
    assert result["audio_copied"] is False and result["playback_key"] is None
    answer = await _answer(uploaded["id"])
    assert answer.status == AnswerStatus.done
    assert answer.media_meta["audio_codec"] == "aac" and "playback_key" not in answer.media_meta
    assert answer.media_meta["stt_model"] == "spy-stt"
    assert answer.audio_key and answer.audio_key.endswith(".ogg")
    extracted = await ffmpeg.probe(get_storage().path_for(answer.audio_key))  # type: ignore[attr-defined]
    assert extracted.audio_codec == "opus" and extracted.audio_channels == 1

    # В STT ушло извлечённое аудио, язык вакансии и подсказка с её названием и навыками.
    (call,) = spy.calls
    assert call["audio"].startswith(b"OggS") and call["content_type"] == "audio/ogg"
    assert call["language"] == "ru"
    assert "Python-разработчик" in call["prompt"] and "FastAPI, PostgreSQL" in call["prompt"]
    assert answer.transcript_text == "Я писал сервисы на FastAPI."
    assert answer.transcript_language == "russian"
    assert answer.transcript_segments == [
        {"start_s": 0.0, "end_s": 1.5, "text": "Я писал сервисы на FastAPI."}
    ]


@needs_ffmpeg
async def test_process_answer_failure_then_retry(
    client: AsyncClient, samples: dict[str, Path], tmp_path: Path
) -> None:
    broken = tmp_path / "broken.webm"
    broken.write_bytes(b"\x1aE\xdf\xa3" + b"\x00garbage" * 300)
    _, _, link, _ = await _started(client)
    uploaded = await _upload_file(client, link, 0, broken, "video/webm")

    with pytest.raises(PipelineError):
        await process_answer_job({"answer_id": uploaded["id"]}, _context())
    failed = await _answer(uploaded["id"])
    assert failed.status == AnswerStatus.failed
    assert failed.processing_error and "PipelineError" in failed.processing_error
    assert len(failed.processing_error) <= 2000
    assert failed.audio_key is None and failed.transcript_text is None

    # Файл починили (докачали) — повтор из failed доходит до done.
    assert failed.media_key
    await get_storage().put(failed.media_key, samples["webm"].read_bytes())
    result = await process_answer_job({"answer_id": uploaded["id"]}, _context())
    assert result is not None and "skipped" not in result
    done = await _answer(uploaded["id"])
    assert done.status == AnswerStatus.done and done.processing_error is None
    assert done.transcript_text and done.audio_key


async def test_process_answer_skips_unfinished_and_missing(client: AsyncClient) -> None:
    _, _, link, _ = await _started(client)
    created = await client.post(
        f"/api/public/invitations/{link}/questions/0/answers", json={"mime_type": "video/webm"}
    )
    answer_id = created.json()["answer"]["id"]
    async with get_session_maker()() as session:
        skipped = await process_answer(session, uuid.UUID(answer_id))
        assert skipped["skipped"] == "status is recording"
        missing = await process_answer(session, uuid.uuid4())
        assert missing["skipped"] == "answer not found"
    assert (await _answer(answer_id)).status == AnswerStatus.recording


def test_media_url_prefers_playback_and_audio_url() -> None:
    answer = Answer(
        media_key="interviews/i/q00-a1-x.webm",
        media_content_type="video/webm",
        status=AnswerStatus.done,
        media_meta={"playback_key": "interviews/i/q00-a1-x.playback.webm"},
        audio_key="interviews/i/q00-a1-x.ogg",
    )
    url = InterviewRoomService.media_url(answer)
    assert (
        url and verify_media_token(url.rsplit("/", 1)[-1]).key == answer.media_meta["playback_key"]
    )
    audio = InterviewRoomService.audio_url(answer)
    assert audio and verify_media_token(audio.rsplit("/", 1)[-1]).content_type == "audio/ogg"
    answer.media_meta = {}
    plain = InterviewRoomService.media_url(answer)
    assert plain and verify_media_token(plain.rsplit("/", 1)[-1]).key == answer.media_key
    answer.audio_key = None
    assert InterviewRoomService.audio_url(answer) is None
    answer.status = AnswerStatus.recording
    assert InterviewRoomService.media_url(answer) is None


# ---------------------------------------------------------------- retention


async def _set_completed(interview_id: str, *, days_ago: int) -> None:
    async with get_session_maker()() as session:
        await session.execute(
            update(Interview)
            .where(Interview.id == uuid.UUID(interview_id))
            .values(completed_at=utcnow() - timedelta(days=days_ago))
        )
        await session.commit()


@needs_ffmpeg
async def test_retention_purge_removes_old_media_only(
    client: AsyncClient, samples: dict[str, Path]
) -> None:
    token, old_interview, old_link, vacancy_id = await _started(client)
    old = await _upload_file(client, old_link, 0, samples["webm"], "video/webm")
    fresh_interview = await _invite(client, token, vacancy_id, "fresh@example.com")
    fresh_link = _token(fresh_interview["link"])
    page = (await client.get(f"/api/public/invitations/{fresh_link}")).json()
    consent = await client.post(
        f"/api/public/invitations/{fresh_link}/consent",
        json={
            "full_name": "Свежий Кандидат",
            "email": "fresh@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
            "document_versions": {d["slug"]: d["version"] for d in page["consent_documents"]},
        },
    )
    assert consent.status_code == 200, consent.text
    await client.post(f"/api/public/invitations/{fresh_link}/start", json={})
    await client.post(f"/api/public/invitations/{fresh_link}/questions/0/reveal")
    fresh = await _upload_file(client, fresh_link, 0, samples["webm"], "video/webm")

    async with get_session_maker()() as session:
        await process_answer(session, uuid.UUID(old["id"]))
        await process_answer(session, uuid.UUID(fresh["id"]))
        organization_id = await session.scalar(
            select(Interview.organization_id).where(Interview.id == uuid.UUID(old_interview["id"]))
        )
        await session.execute(
            update(Organization).where(Organization.id == organization_id).values(retention_days=30)
        )
        await session.commit()
    await _set_completed(old_interview["id"], days_ago=31)
    await _set_completed(fresh_interview["id"], days_ago=1)

    before = await _answer(old["id"])
    old_keys = [before.media_key, before.audio_key, before.media_meta["playback_key"]]
    storage = get_storage()
    assert all([await storage.exists(key) for key in old_keys])

    async with get_session_maker()() as session:
        preview = await purge_expired_media(session, dry_run=True)
        assert preview["files"] >= 3
        assert all([await storage.exists(key) for key in old_keys])
        stats = await purge_expired_media(session)
    assert stats["answers"] >= 1 and stats["files"] >= 3

    purged = await _answer(old["id"])
    assert purged.media_key is None and purged.audio_key is None
    assert "playback_key" not in purged.media_meta and purged.media_meta["purged_at"]
    assert purged.transcript_text == before.transcript_text
    assert purged.media_meta["duration_s"] == before.media_meta["duration_s"]
    assert not any([await storage.exists(key) for key in old_keys])
    assert InterviewRoomService.media_url(purged) is None

    untouched = await _answer(fresh["id"])
    assert untouched.media_key and untouched.audio_key and "purged_at" not in untouched.media_meta
    assert await storage.exists(untouched.media_key)
    assert await storage.exists(untouched.media_meta["playback_key"])

    # Повтор — идемпотентен: нечего удалять, отметка не меняется.
    async with get_session_maker()() as session:
        again = await purge_expired_media(session)
    assert again["files"] == 0
    assert (await _answer(old["id"])).media_meta["purged_at"] == purged.media_meta["purged_at"]
    async with get_session_maker()() as session:
        assert (await process_answer(session, uuid.UUID(old["id"])))["skipped"] == "status is done"


async def test_schedule_daily_purge_is_once_per_day_and_runs_in_worker() -> None:
    day = date(2001, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    async with get_session_maker()() as session:
        first = await schedule_daily_purge(session, day=day)
        same = await schedule_daily_purge(session, day=day)
        await session.commit()
    assert first.id == same.id
    assert first.dedupe_key == f"retention:purge:{day.isoformat()}"
    assert first.payload == {"date": day.isoformat()}

    load_all_handlers()
    worker = Worker(worker_id="w-purge", kinds=[RETENTION_PURGE_JOB])
    assert await worker.run_once()
    async with get_session_maker()() as session:
        job_ = await session.get(Job, first.id)
        assert job_ is not None and job_.status == JobStatus.succeeded
        assert job_.result is not None and "files" in job_.result
        # Задача сама ставит следующую на завтра; ключ на дату существует один.
        tomorrow = utcnow().date() + timedelta(days=1)
        next_job = await session.scalar(
            select(Job).where(Job.dedupe_key == f"retention:purge:{tomorrow.isoformat()}")
        )
        assert next_job is not None and str(next_job.id) == job_.result["next_job_id"]
        # Повторный вызов на этот же день, даже после успешного выполнения, дубль не ставит.
        assert (await schedule_daily_purge(session, day=day)).id == first.id
        # Хук старта воркера ставит задачу на сегодня и не падает на повторе.
        await worker.run_startup_hooks()
        await worker.run_startup_hooks()
        today = await session.scalar(
            select(Job).where(Job.dedupe_key == f"retention:purge:{utcnow().date().isoformat()}")
        )
        assert today is not None
