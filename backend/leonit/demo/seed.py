"""Сид демо-данных: организация со всеми ролями, вакансии, воронка кандидатов, заключения.

    python -m leonit.demo.seed --password <пароль> [--email demo@leonit.ru]
                               [--organization "Napoleon IT"]
                               [--recruiter-email …] [--manager-email …]
                               [--evaluate dataset|real|none] [--json]

Идемпотентен: владелец ищется по e-mail, вакансии — по названию, кандидаты — по
e-mail; повторный запуск ничего не дублирует. Источник контента — eval-датасет
(``backend/evals/dataset``): вакансии с рубрикой и вопросами, транскрипты ответов
и метки эксперта. Режимы заключений:

* ``dataset`` (по умолчанию) — заключение собирается из метки и обоснования
  эксперта без вызова модели (``model = demo-dataset``), стенд без ключей
  показывает осмысленные отчёты сразу;
* ``real`` — ставится задача ``interview.process``, воркер оценивает реальной
  моделью (нужны ключи);
* ``none`` — интервью завершены, заключений нет.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from leonit.accounts.models import User
from leonit.accounts.schemas import InviteCreate, RegisterRequest
from leonit.accounts.service import AccountsService
from leonit.candidates.models import Candidate, Interview, InterviewStatus
from leonit.candidates.schemas import CandidateCreate, InviteRequest
from leonit.candidates.service import InterviewService, transition
from leonit.core.authz import Actor
from leonit.core.db import dispose_engine, get_session_maker
from leonit.core.logging import get_logger, setup_logging
from leonit.core.time import utcnow
from leonit.evaluation.models import Evaluation, EvaluationStatus
from leonit.evaluation.prompts import PROMPT_VERSION
from leonit.evaluation.schemas import (
    CompetencyScore,
    EvaluationOutput,
    Evidence,
    QuestionAssessment,
    SkillDetected,
    output_to_dict,
)
from leonit.evaluation.scoring import score_output
from leonit.evaluation.service import (
    questions_from_snapshot,
    transcripts_from_answers,
    verify_quotes,
)
from leonit.interviews.models import Answer, AnswerStatus
from leonit.interviews.service import INTERVIEW_PROCESS_JOB, build_question_snapshot
from leonit.jobs import service as jobs
from leonit.knowledge.models import KnowledgeDocument
from leonit.knowledge.schemas import KnowledgeTextCreate
from leonit.knowledge.service import KnowledgeService
from leonit.models import load_all_models
from leonit.reports.schemas import DecisionIn, NoteIn
from leonit.reports.service import ReportService
from leonit.vacancies.models import Vacancy
from leonit.vacancies.schemas import (
    InterviewSettings,
    QuestionIn,
    RubricCompetency,
    VacancyCreate,
    VacancyUpdate,
)
from leonit.vacancies.service import VacancyService, settings_of

log = get_logger(__name__)

DATASET_DIR = Path(__file__).resolve().parents[2] / "evals" / "dataset"

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
# Теги по номеру файла: подсказывают поиску тему документа.
KNOWLEDGE_TAGS: dict[str, list[str]] = {
    "01": ["контакты", "офисы", "руководство"],
    "02": ["продукты", "решения"],
    "03": ["клиенты", "кейсы"],
    "04": ["история"],
    "05": ["ценности", "культура", "hr"],
    "06": ["стек", "технологии"],
    "07": ["найм", "стажировки"],
    "08": ["награды", "рейтинги"],
    "09": ["услуги", "консалтинг"],
    # Система грейдов и компетенций (Competency Framework, 09.2026) и материалы кейса.
    "10": ["компетенции", "ценности", "soft skills", "грейды"],
    "11": ["компетенции", "грейды", "разработчик", "software engineer"],
    "12": ["компетенции", "грейды", "qa", "тестирование"],
    "13": ["компетенции", "грейды", "devops", "платформа"],
    "14": ["компетенции", "грейды", "data engineer", "данные"],
    "15": ["компетенции", "грейды", "ml", "llm", "ai"],
    "16": ["компетенции", "грейды", "архитектор"],
    "17": ["компетенции", "грейды", "аналитик"],
    "18": ["компетенции", "грейды", "project manager", "product manager"],
    "19": ["компетенции", "лидерство", "tech lead", "team lead"],
    "20": ["найм", "процесс", "техническое интервью", "кастдев"],
    "21": ["вакансия", "вопросы", "заключение", "python"],
}
DEFAULT_EMAIL = "demo@leonit.ru"
ORGANIZATION_NAME = "Napoleon IT · демо"
# Имена сотрудников подставляются в аккаунты; e-mail задаются параметрами.
OWNER_NAME = "Владелец"
RECRUITER_NAME = "Рекрутер"
MANAGER_NAME = "Нанимающий менеджер"
DEMO_MODEL = "demo-dataset"
# Кейсы с инъекциями (07–09) в демо не нужны: они для eval-контура.
CASE_FILES = ("01", "02", "03", "04", "05", "06")

# Персоны кандидатов по кейсам датасета: имя, e-mail, телефон.
PERSONAS: dict[str, tuple[str, str, str]] = {
    "01": ("Алексей Смирнов", "alexey.smirnov@example.com", "+7 916 123-45-67"),
    "02": ("Мария Кузнецова", "maria.kuznetsova@example.com", "+7 903 555-10-20"),
    "03": ("Дмитрий Орлов", "dmitry.orlov@example.com", "+7 926 700-80-90"),
    "04": ("Екатерина Волкова", "ekaterina.volkova@example.com", "+7 985 321-00-11"),
    "05": ("Игорь Павлов", "igor.pavlov@example.com", "+7 977 444-55-66"),
    "06": ("Анна Лебедева", "anna.lebedeva@example.com", "+7 999 808-07-06"),
}
# Кандидаты на ранних шагах воронки: (имя, e-mail, статус).
FUNNEL_EXTRAS: tuple[tuple[str, str, InterviewStatus], ...] = (
    ("Сергей Морозов", "sergey.morozov@example.com", InterviewStatus.invited),
    ("Ольга Новикова", "olga.novikova@example.com", InterviewStatus.opened),
    ("Никита Фёдоров", "nikita.fedorov@example.com", InterviewStatus.in_progress),
)
# Решения ревьюеров по кейсам: (решение, заметка).
DECISIONS: dict[str, tuple[str, str]] = {
    "01": ("advance", "Сильные ответы по Python и БД, зовём на техническое собеседование."),
    "05": ("reject", "Уверенные, но неверные ответы по базовым темам; расходится с резюме."),
}
_SCORE_PATTERNS: dict[str, tuple[int, ...]] = {
    "fit": (4, 3, 4, 4),
    "needs_check": (3, 2, 3, 2),
    "no_fit": (1, 2, 1, 2),
}
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(slots=True)
class SeedReport:
    organization: str
    owner_email: str
    recruiter_email: str
    manager_email: str
    password: str
    vacancies: list[str] = field(default_factory=list)
    interviews: int = 0
    evaluated: int = 0
    queued_for_evaluation: int = 0
    created: bool = False
    knowledge_documents: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "organization": self.organization,
            "owner_email": self.owner_email,
            "recruiter_email": self.recruiter_email,
            "manager_email": self.manager_email,
            "password": self.password,
            "vacancies": self.vacancies,
            "interviews": self.interviews,
            "evaluated": self.evaluated,
            "queued_for_evaluation": self.queued_for_evaluation,
            "created": self.created,
            "knowledge_documents": self.knowledge_documents,
        }


# ------------------------------------------------------------------ датасет


def load_cases(dataset_dir: Path = DATASET_DIR) -> tuple[dict[str, dict[str, Any]], list[dict]]:
    vacancies = json.loads((dataset_dir / "_vacancies.json").read_text(encoding="utf-8"))
    cases = []
    for file in sorted(dataset_dir.glob("*.json")):
        if file.name.startswith("_") or file.name[:2] not in CASE_FILES:
            continue
        raw = json.loads(file.read_text(encoding="utf-8"))
        raw["_code"] = file.name[:2]
        cases.append(raw)
    return vacancies, cases


def _sentences(text: str, limit: int = 2) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_RE.split(text.strip()) if part.strip()]
    return parts[:limit]


def _first_quote(text: str | None, max_chars: int = 180) -> str:
    if not text:
        return ""
    sentence = _sentences(text, 1)
    quote = sentence[0] if sentence else text.strip()
    return quote[:max_chars].strip()


def _segments(text: str, duration_s: float) -> list[dict[str, Any]]:
    sentences = [part for part in _SENTENCE_RE.split(text.strip()) if part.strip()]
    if not sentences:
        return []
    step = duration_s / len(sentences)
    return [
        {
            "start_s": round(index * step, 3),
            "end_s": round((index + 1) * step, 3),
            "text": sentence.strip(),
        }
        for index, sentence in enumerate(sentences)
    ]


def _duration_s(text: str) -> float:
    # ~2.3 слова в секунду — темп спокойной речи.
    return max(15.0, round(len(text.split()) / 2.3, 1))


# ---------------------------------------------------------- заключение


def synthesize_output(
    case: dict[str, Any],
    vacancy: Vacancy,
    snapshot: list[dict[str, Any]],
    answers: Sequence[Answer],
) -> EvaluationOutput:
    """Заключение «как у эксперта»: баллы по метке, цитаты — из транскриптов."""
    label = case["expert"]["label"]
    rationale = case["expert"]["rationale"]
    pattern = _SCORE_PATTERNS[label]
    by_index = {answer.question_index: answer for answer in answers}
    questions = questions_from_snapshot(snapshot)

    def evidence_for(question_ids: Sequence[int]) -> list[Evidence]:
        items = []
        for question_index in question_ids:
            answer = by_index.get(question_index)
            quote = _first_quote(answer.transcript_text if answer else None)
            if answer is None or not quote:
                continue
            first = (answer.transcript_segments or [{}])[0]
            items.append(
                Evidence(
                    answer_id=str(answer.id),
                    question_index=question_index,
                    quote=quote,
                    start_s=first.get("start_s"),
                    end_s=first.get("end_s"),
                )
            )
        return items[:2]

    competency_scores = []
    for position, item in enumerate(vacancy.rubric or []):
        linked = [q.index for q in questions if item["id"] in (q.competency_ids or [])]
        score = pattern[position % len(pattern)]
        competency_scores.append(
            CompetencyScore(
                competency_id=item["id"],
                name=item["name"],
                score=score,
                rationale=(item.get("levels") or {}).get(str(score))
                or f"Уровень {score} по якорям рубрики.",
                evidence=evidence_for(linked or [q.index for q in questions][:1]),
            )
        )

    assessments = []
    for question in questions:
        answer = by_index.get(question.index)
        available = answer is not None and answer.status == AnswerStatus.done
        score = pattern[question.index % len(pattern)] if available else 1
        expected = list(question.expected_points)
        covered = expected[: max(1, score - 1)] if available else []
        assessments.append(
            QuestionAssessment(
                question_index=question.index,
                answer_id=str(answer.id) if answer else "нет",
                score=score,
                comment=("Ответ раскрывает тему по существу." if score >= 3 else "Ответ неполный.")
                if available
                else "Транскрипт недоступен: ответ не записан.",
                covered_points=covered,
                missed_points=[point for point in expected if point not in covered],
                evidence=evidence_for([question.index]) if available else [],
            )
        )

    missing = [a for a in assessments if a.answer_id == "нет"]
    strengths = {
        "fit": ["Уверенно объясняет внутреннее устройство инструментов", "Опирается на практику"],
        "needs_check": ["Знает базовые понятия", "Честно признаёт границы своего опыта"],
        "no_fit": ["Коммуникация ясная, отвечает по вопросу"],
    }[label]
    growth = {
        "fit": ["Больше говорить о компромиссах и ограничениях решений"],
        "needs_check": ["Разобрать план запроса и индексы на практике", "Глубже изучить asyncio"],
        "no_fit": ["Пересмотреть базовые темы: GIL, транзакции, идемпотентность"],
    }[label]
    return EvaluationOutput(
        summary=rationale,
        competency_scores=competency_scores,
        question_assessments=assessments,
        strengths=strengths,
        growth_areas=growth,
        risks=["Ответы противоречат заявленному опыту"] if label == "no_fit" else [],
        skills=[
            SkillDetected(
                name=skill,
                level={"fit": "уверенно", "needs_check": "применял", "no_fit": "упоминает"}[label],
                evidence=[],
            )
            for skill in list(vacancy.skills or [])[:3]
        ],
        follow_up_checks=_sentences(rationale, 1) if label == "needs_check" else [],
        red_flags=[],
        confidence=0.45 if missing else 0.85,
        transcript_quality_note=(
            f"Недоступно ответов: {len(missing)} — кандидат не записал ответ." if missing else None
        ),
    )


# --------------------------------------------------------------- сид


class DemoSeeder:
    def __init__(
        self,
        session: AsyncSession,
        *,
        email: str,
        password: str,
        evaluate: str,
        organization: str = ORGANIZATION_NAME,
        recruiter_email: str | None = None,
        manager_email: str | None = None,
        dataset_dir: Path = DATASET_DIR,
    ) -> None:
        self.session = session
        self.email = email.lower()
        self.password = password
        self.evaluate = evaluate
        self.organization = organization
        # По умолчанию адреса сотрудников выводятся из адреса владельца
        # плюс-адресацией: demo@… → demo+recruiter@…
        self.recruiter_email = (recruiter_email or email.replace("@", "+recruiter@", 1)).lower()
        self.manager_email = (manager_email or email.replace("@", "+manager@", 1)).lower()
        self.dataset_dir = dataset_dir
        self.accounts = AccountsService(session)
        self.now = utcnow()

    # --- организация и роли ------------------------------------------------

    async def ensure_owner(self) -> tuple[Actor, bool]:
        user = await self.accounts.get_user_by_email(self.email)
        created = user is None
        if user is None:
            user = await self.accounts.register(
                RegisterRequest(
                    email=self.email,
                    password=self.password,
                    full_name=f"{OWNER_NAME} · {self.organization}",
                    organization_name=self.organization,
                )
            )
        actor = await self.accounts.get_actor(user)
        assert actor is not None
        return actor, created

    async def ensure_member(
        self,
        actor: Actor,
        *,
        email: str,
        full_name: str,
        role: str,
        vacancy_scope: list[str] | None,
    ) -> User:
        existing = await self.accounts.get_user_by_email(email)
        if existing is not None:
            return existing
        _, token = await self.accounts.create_invite(
            actor,
            InviteCreate(role=role, email=email, vacancy_scope=vacancy_scope),  # type: ignore[arg-type]
        )
        return await self.accounts.register(
            RegisterRequest(
                email=email, password=self.password, full_name=full_name, invite_token=token
            )
        )

    # --- вакансии ----------------------------------------------------------

    async def ensure_vacancy(self, actor: Actor, raw: dict[str, Any]) -> Vacancy:
        service = VacancyService(self.session)
        existing = await self.session.scalar(
            select(Vacancy).where(
                Vacancy.organization_id == actor.organization.id, Vacancy.title == raw["title"]
            )
        )
        if existing is not None:
            return await service.get(actor, existing.id)
        vacancy = await service.create(
            actor,
            VacancyCreate(
                title=raw["title"],
                description=raw.get("description", ""),
                requirements=raw.get("requirements", ""),
                skills=list(raw.get("skills") or []),
                level=raw.get("level"),
            ),
        )
        vacancy = await service.update(
            actor,
            vacancy.id,
            VacancyUpdate(
                rubric=[RubricCompetency(**item) for item in raw.get("rubric") or []],
                settings=InterviewSettings(
                    intro_text=(
                        "Спасибо, что откликнулись. Ответьте на несколько вопросов на камеру "
                        "в удобном темпе — как на живом собеседовании."
                    ),
                    prep_seconds=20,
                    max_answer_seconds=180,
                    retakes_allowed=1,
                    invitation_days=14,
                    candidate_feedback_mode="after_decision",
                ),
            ),
        )
        await service.replace_questions(
            actor,
            vacancy.id,
            [
                QuestionIn(
                    text=item["text"],
                    expected_points=list(item.get("expected_points") or []),
                    competency_ids=list(item.get("competency_ids") or []),
                )
                for item in raw.get("questions") or []
            ],
        )
        vacancy = await service.publish(actor, vacancy.id)
        return await service.get(actor, vacancy.id)

    # --- кандидаты и интервью ----------------------------------------------

    async def _interview_for(
        self, actor: Actor, vacancy: Vacancy, *, full_name: str, email: str, phone: str | None
    ) -> Interview | None:
        candidate = await self.session.scalar(
            select(Candidate).where(
                Candidate.organization_id == actor.organization.id, Candidate.email == email
            )
        )
        if candidate is not None:
            existing = await self.session.scalar(
                select(Interview).where(
                    Interview.candidate_id == candidate.id, Interview.vacancy_id == vacancy.id
                )
            )
            if existing is not None:
                return None
        interviews = InterviewService(self.session)
        if candidate is None:
            from leonit.candidates.service import CandidateService

            candidate = await CandidateService(self.session).create(
                actor, CandidateCreate(full_name=full_name, email=email, phone=phone)
            )
        interview, _ = await interviews.invite(
            actor,
            InviteRequest(vacancy_id=vacancy.id, candidate_id=candidate.id, send_email=False),
        )
        return interview

    def _stamp(self, interview: Interview, invited_at: datetime, vacancy: Vacancy) -> None:
        interview.invited_at = invited_at
        interview.expires_at = invited_at + timedelta(days=settings_of(vacancy).invitation_days)

    async def seed_funnel_extras(self, actor: Actor, vacancy: Vacancy) -> int:
        count = 0
        for offset, (full_name, email, status) in enumerate(FUNNEL_EXTRAS):
            interview = await self._interview_for(
                actor, vacancy, full_name=full_name, email=email, phone=None
            )
            if interview is None:
                continue
            invited_at = self.now - timedelta(days=2 + offset, hours=3)
            self._stamp(interview, invited_at, vacancy)
            if status in (InterviewStatus.opened, InterviewStatus.in_progress):
                transition(interview, InterviewStatus.opened)
                interview.opened_at = invited_at + timedelta(hours=5)
            if status == InterviewStatus.in_progress:
                transition(interview, InterviewStatus.consented)
                interview.consented_at = invited_at + timedelta(hours=5, minutes=3)
                interview.consent_full_name = full_name
                interview.consent_email = email
                interview.question_snapshot = build_question_snapshot(vacancy)
                interview.settings_snapshot = settings_of(vacancy).model_dump()
                transition(interview, InterviewStatus.in_progress)
                interview.started_at = invited_at + timedelta(hours=5, minutes=6)
                interview.current_question_index = 1
                self.session.add(
                    self._answer(
                        interview,
                        0,
                        "Меня зовут Никита, я три года пишу на Python.",
                        started_at=interview.started_at + timedelta(minutes=2),
                    )
                )
            count += 1
        await self.session.commit()
        return count

    def _answer(
        self, interview: Interview, index: int, text: str, *, started_at: datetime
    ) -> Answer:
        snapshot = interview.question_snapshot or []
        duration = _duration_s(text)
        ended = started_at + timedelta(seconds=duration)
        return Answer(
            interview_id=interview.id,
            question_index=index,
            question_id=snapshot[index]["id"] if index < len(snapshot) else None,
            attempt=1,
            is_final=True,
            status=AnswerStatus.done,
            media_key=None,
            media_content_type=None,
            media_size=0,
            upload_offset=0,
            recording_started_at=started_at,
            first_chunk_at=started_at,
            last_chunk_at=ended,
            recording_ended_at=ended,
            duration_ms=int(duration * 1000),
            client_duration_ms=int(duration * 1000),
            chunk_count=1,
            transcript_text=text,
            transcript_segments=_segments(text, duration),
            transcript_language="ru",
            media_meta={"demo": True, "duration_s": duration, "video_codec": None},
            processing_error=None,
            processed_at=ended + timedelta(minutes=2),
        )

    async def seed_case(
        self, actor: Actor, vacancy: Vacancy, case: dict[str, Any], *, offset: int
    ) -> Interview | None:
        full_name, email, phone = PERSONAS[case["_code"]]
        interview = await self._interview_for(
            actor, vacancy, full_name=full_name, email=email, phone=phone
        )
        if interview is None:
            return None
        invited_at = self.now - timedelta(days=19 - 3 * offset, hours=4)
        self._stamp(interview, invited_at, vacancy)
        transition(interview, InterviewStatus.opened)
        transition(interview, InterviewStatus.consented)
        interview.opened_at = invited_at + timedelta(days=1)
        interview.consented_at = interview.opened_at + timedelta(minutes=4)
        interview.consent_full_name = full_name
        interview.consent_email = email
        interview.consent_ip = "demo"
        interview.consent_user_agent = "demo-seed"
        interview.question_snapshot = build_question_snapshot(vacancy)
        interview.settings_snapshot = settings_of(vacancy).model_dump()
        transition(interview, InterviewStatus.in_progress)
        interview.started_at = interview.consented_at + timedelta(minutes=2)
        cursor = interview.started_at + timedelta(minutes=1)
        answers: list[Answer] = []
        for transcript in case["transcripts"]:
            if transcript.get("status") != "done" or not transcript.get("text"):
                continue
            answer = self._answer(
                interview, int(transcript["question_index"]), transcript["text"], started_at=cursor
            )
            answers.append(answer)
            self.session.add(answer)
            cursor = answer.recording_ended_at + timedelta(minutes=1)  # type: ignore[operator]
        interview.current_question_index = len(interview.question_snapshot or []) - 1
        transition(interview, InterviewStatus.completed)
        interview.completed_at = cursor
        await self.session.flush()

        if self.evaluate == "dataset":
            await self._evaluate_from_dataset(interview, vacancy, case, answers)
        elif self.evaluate == "real":
            transition(interview, InterviewStatus.processing)
            interview.processed_at = cursor
            await jobs.enqueue(
                self.session,
                INTERVIEW_PROCESS_JOB,
                {"interview_id": str(interview.id)},
                dedupe_key=f"interview:{interview.id}",
            )
        await self.session.commit()

        decision = DECISIONS.get(case["_code"])
        if decision and self.evaluate == "dataset":
            reports = ReportService(self.session)
            await reports.add_note(
                actor,
                interview.id,
                NoteIn(text="Смотрел вместе с тимлидом, мнения совпали.", answer_id=None),
            )
            await reports.decide(
                actor, interview.id, DecisionIn(decision=decision[0], note=decision[1])
            )  # type: ignore[arg-type]
            interview.decided_at = interview.completed_at + timedelta(days=1)
            await self.session.commit()
        return interview

    async def _evaluate_from_dataset(
        self, interview: Interview, vacancy: Vacancy, case: dict[str, Any], answers: list[Answer]
    ) -> None:
        snapshot = interview.question_snapshot or []
        output = synthesize_output(case, vacancy, snapshot, answers)
        questions = questions_from_snapshot(snapshot)
        transcripts = transcripts_from_answers(questions, answers)
        found, total = verify_quotes(output, transcripts)
        scoring = score_output(output, list(vacancy.rubric or []))
        transition(interview, InterviewStatus.processing)
        interview.processed_at = interview.completed_at + timedelta(minutes=3)  # type: ignore[operator]
        self.session.add(
            Evaluation(
                interview_id=interview.id,
                status=EvaluationStatus.done,
                fit_score=scoring.fit_score,
                recommendation=scoring.recommendation,
                output=output_to_dict(output),
                candidate_feedback=None,
                model=DEMO_MODEL,
                prompt_version=PROMPT_VERSION,
                raw_response={"provider": "demo", "case": case["id"], "reasons": scoring.reasons},
                usage=None,
                error=None,
                quotes_found=found,
                quotes_total=total,
                evaluated_at=interview.processed_at + timedelta(minutes=4),
            )
        )
        transition(interview, InterviewStatus.evaluated)
        interview.evaluated_at = interview.processed_at + timedelta(minutes=4)

    # --- всё вместе --------------------------------------------------------

    async def run(self) -> SeedReport:
        vacancies_raw, cases = load_cases(self.dataset_dir)
        actor, created = await self.ensure_owner()
        report = SeedReport(
            organization=actor.organization.name,
            owner_email=self.email,
            recruiter_email=self.recruiter_email,
            manager_email=self.manager_email,
            password=self.password,
            created=created,
        )
        vacancies: dict[str, Vacancy] = {}
        for key, raw in vacancies_raw.items():
            vacancy = await self.ensure_vacancy(actor, raw)
            vacancies[key] = vacancy
            report.vacancies.append(vacancy.title)
        first = next(iter(vacancies.values()))
        await self.ensure_member(
            actor,
            email=report.recruiter_email,
            full_name=f"{RECRUITER_NAME} · {actor.organization.name}",
            role="recruiter",
            vacancy_scope=None,
        )
        await self.ensure_member(
            actor,
            email=report.manager_email,
            full_name=f"{MANAGER_NAME} · {actor.organization.name}",
            role="hiring_manager",
            vacancy_scope=[str(first.id)],
        )
        for offset, case in enumerate(cases):
            vacancy = vacancies.get(case["vacancy"]) if isinstance(case["vacancy"], str) else None
            if vacancy is None:
                vacancy = first
            interview = await self.seed_case(actor, vacancy, case, offset=offset)
            if interview is None:
                continue
            report.interviews += 1
            if self.evaluate == "dataset":
                report.evaluated += 1
            elif self.evaluate == "real":
                report.queued_for_evaluation += 1
        report.interviews += await self.seed_funnel_extras(actor, first)
        report.knowledge_documents = await self.ensure_knowledge(actor)
        return report

    async def ensure_knowledge(self, actor: Actor) -> int:
        """База знаний компании из ``demo/knowledge/*.md``: документ на файл, по названию.

        Заголовок первого уровня становится названием документа; повторный запуск
        ничего не дублирует и не перезаписывает правки, сделанные в кабинете.
        """
        added = 0
        existing = set(
            await self.session.scalars(
                select(KnowledgeDocument.title).where(
                    KnowledgeDocument.organization_id == actor.organization_id
                )
            )
        )
        service = KnowledgeService(self.session)
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            first_line = text.splitlines()[0] if text else ""
            title = first_line.lstrip("# ").strip() or path.stem
            if title in existing:
                continue
            tags = KNOWLEDGE_TAGS.get(path.stem.split("-", 1)[0], [])
            await service.create_text(
                actor, KnowledgeTextCreate(title=title, text=text, tags=["о компании", *tags])
            )
            existing.add(title)
            added += 1
        return added


async def seed(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    password: str,
    email: str = DEFAULT_EMAIL,
    evaluate: str = "dataset",
    organization: str = ORGANIZATION_NAME,
    recruiter_email: str | None = None,
    manager_email: str | None = None,
    dataset_dir: Path = DATASET_DIR,
) -> SeedReport:
    async with session_maker() as session:
        seeder = DemoSeeder(
            session,
            email=email,
            password=password,
            evaluate=evaluate,
            organization=organization,
            recruiter_email=recruiter_email,
            manager_email=manager_email,
            dataset_dir=dataset_dir,
        )
        return await seeder.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LeonIT: демо-данные для стенда")
    parser.add_argument("--password", required=True, help="пароль владельца, рекрутера и менеджера")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="e-mail владельца организации")
    parser.add_argument("--organization", default=ORGANIZATION_NAME, help="название организации")
    parser.add_argument(
        "--recruiter-email", default=None, help="e-mail рекрутера (по умолчанию — +recruiter)"
    )
    parser.add_argument(
        "--manager-email", default=None, help="e-mail менеджера (по умолчанию — +manager)"
    )
    parser.add_argument(
        "--evaluate",
        choices=("dataset", "real", "none"),
        default="dataset",
        help="откуда заключения: dataset (без модели), real (через воркер), none",
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR)
    parser.add_argument("--json", action="store_true", help="печатать отчёт в JSON")
    args = parser.parse_args(argv)
    if len(args.password) < 8:
        parser.error("пароль не короче 8 символов")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    setup_logging()
    load_all_models()

    async def _run() -> SeedReport:
        try:
            return await seed(
                get_session_maker(),
                password=args.password,
                email=args.email,
                evaluate=args.evaluate,
                organization=args.organization,
                recruiter_email=args.recruiter_email,
                manager_email=args.manager_email,
                dataset_dir=args.dataset,
            )
        finally:
            await dispose_engine()

    report = asyncio.run(_run())
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Организация: {report.organization} ({'создана' if report.created else 'уже была'})")
        print(f"Владелец:    {report.owner_email}")
        print(f"Рекрутер:    {report.recruiter_email}")
        print(f"Менеджер:    {report.manager_email} (доступ к «{report.vacancies[0]}»)")
        print(f"Пароль:      {report.password}")
        print(f"Вакансии:    {', '.join(report.vacancies)}")
        print(
            f"Интервью:    добавлено {report.interviews}, с заключением {report.evaluated}, "
            f"в очереди на оценку {report.queued_for_evaluation}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
