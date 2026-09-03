"""Секция кода: черновик и отправка, валидация, запуск, видео-пояснение, отчёт."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leonit.code_runner import NullCodeRunner, RunResult, get_code_runner
from leonit.core.config import Settings
from leonit.core.db import get_session_maker
from leonit.interviews import answer_text_for_evaluation
from leonit.interviews import service as room_service
from leonit.interviews.models import Answer, InterviewEvent
from leonit.jobs.models import Job
from tests.helpers import bearer, register
from tests.test_candidates import _invite, _token
from tests.test_interview_room import CHUNK, _upload_answer

CODE_QUESTION = "Напишите функцию, которая возвращает n-е число Фибоначчи"
SOURCE = "def fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\n"


class StubRunner:
    name = "stub"
    enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, float]] = []

    async def run(
        self, language: str, source: str, stdin: str = "", timeout_s: float = 10.0
    ) -> RunResult:
        self.calls.append((language, source, stdin, timeout_s))
        return RunResult(status="ok", stdout="55\n", stderr="", exit_code=0, duration_ms=12)


def _room(link: str) -> str:
    return f"/api/public/invitations/{link}"


async def _code_vacancy(client: AsyncClient, token: str) -> dict:
    response = await client.post(
        "/api/vacancies",
        json={"title": "Python-разработчик", "description": "Бэкенд"},
        headers=bearer(token),
    )
    vacancy = response.json()
    await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={
            "questions": [
                {"text": CODE_QUESTION, "kind": "code"},
                {"text": "Расскажите о себе"},
            ]
        },
        headers=bearer(token),
    )
    published = await client.post(f"/api/vacancies/{vacancy['id']}/publish", headers=bearer(token))
    assert published.status_code == 200, published.text
    return published.json()


async def _started(client: AsyncClient) -> tuple[str, dict, str, dict]:
    """Вакансия с вопросом kind=code первым: (токен рекрутера, интервью, ссылка, state)."""
    _, token = await register(client, organization_name="Napoleon IT")
    vacancy = await _code_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "cand@example.com")
    link = _token(interview["link"])
    page = (await client.get(_room(link))).json()
    consent = await client.post(
        f"{_room(link)}/consent",
        json={
            "full_name": "Иван Кандидат",
            "email": "cand@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
            "document_versions": {d["slug"]: d["version"] for d in page["consent_documents"]},
        },
    )
    assert consent.status_code == 200, consent.text
    started = await client.post(f"{_room(link)}/start", json={})
    assert started.status_code == 200, started.text
    reveal = await client.post(f"{_room(link)}/questions/0/reveal")
    assert reveal.status_code == 200, reveal.text
    return token, interview, link, started.json()


def test_default_runner_is_null() -> None:
    runner = get_code_runner(Settings())
    assert isinstance(runner, NullCodeRunner) and runner.enabled is False


async def test_code_question_flow(client: AsyncClient) -> None:
    token, interview, link, state = await _started(client)
    assert state["code_runner"] == {
        "enabled": False,
        "languages": ["python", "javascript", "typescript", "go", "java", "sql"],
        "max_source_bytes": 65536,
    }
    question = state["questions"][0]
    assert question["kind"] == "code"
    code_url = f"{_room(link)}/answers/{question['id']}/code"

    # Без отправленного кода дальше нельзя — ни без черновика, ни с ним.
    assert (await client.post(f"{_room(link)}/next")).status_code == 409
    draft = await client.put(code_url, json={"language": "Python", "source": "def fib(n):"})
    assert draft.status_code == 200, draft.text
    body = draft.json()
    assert body["status"] == "recording"
    assert body["code_submission"] == {
        "language": "python",
        "source": "def fib(n):",
        "submitted_at": None,
        "run_result": None,
    }
    assert (await client.post(f"{_room(link)}/next")).status_code == 409

    submitted = await client.put(
        code_url, json={"language": "python", "source": SOURCE, "submit": True}
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["id"] == draft.json()["id"] and body["attempt"] == 1
    assert body["status"] == "done" and body["is_final"] is True
    assert body["duration_ms"] is not None and body["recording_ended_at"] is not None
    assert body["code_submission"]["submitted_at"] is not None
    assert body["code_submission"]["source"] == SOURCE

    # После перезагрузки страницы редактор восстанавливается из state.
    state = (await client.get(f"{_room(link)}/state")).json()
    assert state["answers"][0]["code_submission"]["source"] == SOURCE

    moved = await client.post(f"{_room(link)}/next")
    assert moved.status_code == 200 and moved.json()["current_question_index"] == 1
    await client.post(f"{_room(link)}/questions/1/reveal")
    await _upload_answer(client, link, 1, chunks=1)
    finished = await client.post(f"{_room(link)}/next")
    assert finished.status_code == 200 and finished.json()["status"] == "completed"

    # Сотрудник видит код в деталях ответа; видео у такого ответа нет, а текст ответа — код.
    answers = (
        await client.get(f"/api/interviews/{interview['id']}/answers", headers=bearer(token))
    ).json()
    code_answer, video_answer = answers
    assert code_answer["question_text"] == CODE_QUESTION
    assert code_answer["media_url"] is None and code_answer["audio_url"] is None
    assert code_answer["code_submission"]["language"] == "python"
    assert code_answer["transcript_text"].startswith("```python\ndef fib(n):")
    assert video_answer["code_submission"] is None and video_answer["transcript_text"] is None

    # В отчёте по ссылке — тоже.
    share = await client.post(
        f"/api/interviews/{interview['id']}/shares",
        json={"label": "Тимлид"},
        headers=bearer(token),
    )
    share_token = share.json()["url"].rsplit("/r/", 1)[1]
    report = (await client.get(f"/api/public/reports/{share_token}")).json()
    assert report["answers"][0]["code_submission"]["source"] == SOURCE
    assert report["answers"][0]["media_url"] is None
    assert report["answers"][1]["code_submission"] is None

    async with get_session_maker()() as session:
        interview_id = uuid.UUID(interview["id"])
        kinds = (
            await session.scalars(
                select(InterviewEvent.kind).where(InterviewEvent.interview_id == interview_id)
            )
        ).all()
        assert "code_submitted" in kinds
        # Медиа-пайплайн ставится только на видео: у кода обрабатывать нечего.
        jobs = (
            await session.scalars(
                select(Job.kind).where(Job.payload["interview_id"].as_string() == interview["id"])
            )
        ).all()
        assert jobs.count("answer.process") == 1


async def test_code_validation(client: AsyncClient) -> None:
    _, _, link, state = await _started(client)
    question_id = state["questions"][0]["id"]
    code_url = f"{_room(link)}/answers/{question_id}/code"

    unknown = await client.put(code_url, json={"language": "brainfuck", "source": "+"})
    assert unknown.status_code == 422 and "brainfuck" in unknown.json()["detail"]

    too_big = await client.put(code_url, json={"language": "python", "source": "x" * 70_000})
    assert too_big.status_code == 413, too_big.text

    empty = await client.put(code_url, json={"language": "python", "source": " \n", "submit": True})
    assert empty.status_code == 422

    missing = await client.put(
        f"{_room(link)}/answers/{uuid.uuid4()}/code", json={"language": "python", "source": "x"}
    )
    assert missing.status_code == 404

    ok = await client.put(code_url, json={"language": "python", "source": SOURCE, "submit": True})
    assert ok.status_code == 200
    assert (await client.post(f"{_room(link)}/next")).status_code == 200

    # На видео-вопрос код не принимается, на уже пройденный — тоже.
    video_id = (await client.get(f"{_room(link)}/state")).json()["questions"][1]["id"]
    wrong_kind = await client.put(
        f"{_room(link)}/answers/{video_id}/code", json={"language": "python", "source": "x"}
    )
    assert wrong_kind.status_code == 409 and "секци" in wrong_kind.json()["detail"]
    stale = await client.put(code_url, json={"language": "python", "source": "x"})
    assert stale.status_code == 409


async def test_run_requires_runner(client: AsyncClient) -> None:
    _, _, link, state = await _started(client)
    assert state["code_runner"]["enabled"] is False
    run_url = f"{_room(link)}/answers/{state['questions'][0]['id']}/code/run"
    response = await client.post(run_url, json={"language": "python", "source": SOURCE})
    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": "Запуск кода пока недоступен: раннер не настроен",
        "code": "runner_disabled",
    }
    # Валидация — до проверки раннера: кривой язык остаётся 422.
    invalid = await client.post(run_url, json={"language": "cobol", "source": "x"})
    assert invalid.status_code == 422


async def test_stub_runner_result_is_saved(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubRunner()
    monkeypatch.setattr(room_service, "get_code_runner", lambda settings=None: stub)
    _, interview, link, state = await _started(client)
    assert state["code_runner"]["enabled"] is True
    question_id = state["questions"][0]["id"]
    source = SOURCE + "print(fib(10))\n"

    ran = await client.post(
        f"{_room(link)}/answers/{question_id}/code/run",
        json={"language": "python", "source": source, "stdin": "10"},
    )
    assert ran.status_code == 200, ran.text
    submission = ran.json()["code_submission"]
    assert submission["submitted_at"] is None and submission["source"] == source
    result = submission["run_result"]
    assert result["status"] == "ok" and result["stdout"] == "55\n"
    assert result["exit_code"] == 0 and result["duration_ms"] == 12 and result["ran_at"]
    assert stub.calls == [("python", source, "10", 10.0)]

    # Отправка того же текста сохраняет результат запуска, изменённого — сбрасывает.
    same = await client.put(
        f"{_room(link)}/answers/{question_id}/code",
        json={"language": "python", "source": source, "submit": True},
    )
    assert same.json()["code_submission"]["run_result"]["stdout"] == "55\n"
    changed = await client.put(
        f"{_room(link)}/answers/{question_id}/code",
        json={"language": "python", "source": SOURCE, "submit": True},
    )
    assert changed.json()["code_submission"]["run_result"] is None

    async with get_session_maker()() as session:
        kinds = (
            await session.scalars(
                select(InterviewEvent.kind).where(
                    InterviewEvent.interview_id == uuid.UUID(interview["id"])
                )
            )
        ).all()
        assert "code_run" in kinds


async def test_explanation_video_attaches_to_code_attempt(client: AsyncClient) -> None:
    token, interview, link, state = await _started(client)
    question_id = state["questions"][0]["id"]
    submitted = await client.put(
        f"{_room(link)}/answers/{question_id}/code",
        json={"language": "python", "source": SOURCE, "submit": True},
    )
    answer_id = submitted.json()["id"]

    # Пояснение на камеру пишется в ту же попытку, где лежит код.
    created = await client.post(
        f"{_room(link)}/questions/0/answers", json={"mime_type": "video/webm"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["answer"]["id"] == answer_id
    assert created.json()["answer"]["attempt"] == 1
    assert created.json()["answer"]["status"] == "recording"
    uploaded = await client.patch(
        f"{_room(link)}/answers/{answer_id}/chunks",
        content=CHUNK,
        headers={"Upload-Offset": "0"},
    )
    assert uploaded.status_code == 200
    completed = await client.post(
        f"{_room(link)}/answers/{answer_id}/complete", json={"size": len(CHUNK)}
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "uploaded"
    assert completed.json()["code_submission"]["source"] == SOURCE

    # Перезапись пояснения — новая попытка, код переезжает вместе с ней.
    retake = await _upload_answer(client, link, 0, chunks=1)
    assert retake["attempt"] == 2 and retake["is_final"] is True
    assert retake["code_submission"]["submitted_at"] is not None
    assert retake["code_submission"]["source"] == SOURCE
    state = (await client.get(f"{_room(link)}/state")).json()
    finals = {a["attempt"]: a["is_final"] for a in state["answers"]}
    assert finals == {1: False, 2: True}
    assert (await client.post(f"{_room(link)}/next")).status_code == 200

    answers = (
        await client.get(f"/api/interviews/{interview['id']}/answers", headers=bearer(token))
    ).json()
    final = next(a for a in answers if a["is_final"])
    assert final["media_url"].startswith("/api/media/")
    assert final["code_submission"]["language"] == "python"
    # Транскрипт видео ещё не готов — код в transcript_text не подмешивается.
    assert final["transcript_text"] is None


def test_answer_text_for_evaluation_combines_transcript_and_code() -> None:
    submitted = {
        "language": "python",
        "source": SOURCE,
        "submitted_at": "2026-09-03T12:00:00+00:00",
        "run_result": {
            "status": "error",
            "stdout": "",
            "stderr": "NameError: name 'fib' is not defined",
            "exit_code": 1,
            "duration_ms": 5,
        },
    }
    answer = Answer(
        interview_id=uuid.uuid4(),
        question_index=0,
        transcript_text="Я использовал рекурсию.",
        code_submission=submitted,
    )
    text = answer_text_for_evaluation(answer)
    assert text is not None
    assert text.startswith("Я использовал рекурсию.\n\n```python\ndef fib(n):")
    assert "Результат запуска: error (код выхода 1)" in text
    assert "NameError" in text

    code_only = Answer(interview_id=uuid.uuid4(), question_index=0, code_submission=submitted)
    assert answer_text_for_evaluation(code_only).startswith("```python\n")  # type: ignore[union-attr]

    draft = Answer(
        interview_id=uuid.uuid4(),
        question_index=0,
        code_submission={**submitted, "submitted_at": None},
    )
    assert answer_text_for_evaluation(draft) is None

    speech = Answer(interview_id=uuid.uuid4(), question_index=0, transcript_text="Только речь")
    assert answer_text_for_evaluation(speech) == "Только речь"
    assert answer_text_for_evaluation(Answer(interview_id=uuid.uuid4(), question_index=0)) is None
