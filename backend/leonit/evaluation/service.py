"""Оценка интервью: сбор контекста, вызовы модели, расчёт рекомендации, запись.

Ядро — чистая ``evaluate_payload``: она не знает про базу и получает вакансию,
вопросы и транскрипты как данные. Её же гоняет eval-скрипт по датасету, поэтому
согласие с экспертом измеряется ровно на том коде, который работает в проде.
``evaluate_interview`` лишь собирает эти данные из базы и сохраняет результат.

Цитаты (``evidence``) проверяются по тем же текстам, которые видела модель
(с плейсхолдерами вместо ПДн): найденные дословно помечаются ``verified``,
остальные остаются в заключении с пометкой, а счётчик найдено/всего
сохраняется в строке заключения и виден в отчёте.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leonit.ai.gateway import get_llm
from leonit.ai.providers.base import LLMProvider
from leonit.ai.structured import complete_structured
from leonit.candidates.models import Interview, InterviewStatus
from leonit.candidates.service import InterviewService, transition
from leonit.core.authz import Actor, authorize
from leonit.core.config import Settings, get_settings
from leonit.core.errors import ConflictError, NotFoundError
from leonit.core.logging import get_logger
from leonit.core.time import aware, utcnow
from leonit.evaluation.models import Evaluation, EvaluationStatus
from leonit.evaluation.prompts import (
    PROMPT_VERSION,
    build_evaluation_messages,
    build_feedback_messages,
)
from leonit.evaluation.redaction import Redactor
from leonit.evaluation.schemas import (
    CandidateFeedback,
    EvaluationOutput,
    Evidence,
    QuestionContext,
    RankingItem,
    Recommendation,
    TranscriptContext,
    TranscriptSegmentContext,
    VacancyContext,
    output_to_dict,
)
from leonit.evaluation.scoring import ScoringResult, Thresholds, score_output
from leonit.interviews.models import Answer, AnswerStatus
from leonit.notifications.outreach import (
    notify_evaluation_ready,
    schedule_candidate_feedback,
)
from leonit.vacancies.models import CandidateFeedbackMode, Vacancy

log = get_logger(__name__)

_MAX_ERROR_CHARS = 8000
# Статусы ответа, при которых транскрипт ещё может появиться.
PENDING_ANSWER_STATUSES: frozenset[AnswerStatus] = frozenset(
    {AnswerStatus.uploaded, AnswerStatus.processing, AnswerStatus.recording}
)
# Какой из зачётных ответов на вопрос брать, если их несколько: готовый
# транскрипт важнее незавершённой обработки, та — важнее ошибки.
_STATUS_RANK = {
    AnswerStatus.done: 3,
    AnswerStatus.processing: 2,
    AnswerStatus.uploaded: 2,
    AnswerStatus.failed: 1,
    AnswerStatus.recording: 0,
    AnswerStatus.abandoned: 0,
}


@dataclass(slots=True)
class EvaluationResult:
    output: EvaluationOutput
    fit_score: float | None
    recommendation: Recommendation
    scoring: ScoringResult
    raw_response: dict[str, Any]
    usage: dict[str, Any] | None
    model: str
    # Сколько фрагментов ПДн заменено плейсхолдерами перед отправкой.
    redactions: int = 0
    # Проверка цитат: найдено дословно / всего.
    quotes_found: int = 0
    quotes_total: int = 0


def thresholds_from_settings(settings: Settings | None = None) -> Thresholds:
    settings = settings or get_settings()
    return Thresholds(fit=settings.EVAL_FIT_THRESHOLD, no_fit=settings.EVAL_NO_FIT_THRESHOLD)


# ------------------------------------------------------------ нормализация


def vacancy_context(vacancy: VacancyContext | Vacancy | Mapping[str, Any]) -> VacancyContext:
    if isinstance(vacancy, VacancyContext):
        return vacancy
    if isinstance(vacancy, Vacancy):
        return VacancyContext(
            title=vacancy.title,
            description=vacancy.description or "",
            requirements=vacancy.requirements or "",
            skills=list(vacancy.skills or []),
            level=vacancy.level,
            rubric=list(vacancy.rubric or []),  # type: ignore[arg-type]
        )
    return VacancyContext.model_validate(dict(vacancy))


def questions_context(
    questions: Sequence[QuestionContext | Mapping[str, Any]],
) -> list[QuestionContext]:
    result = []
    for position, item in enumerate(questions):
        if isinstance(item, QuestionContext):
            result.append(item)
            continue
        data = dict(item)
        data.setdefault("index", position)
        result.append(QuestionContext.model_validate(data))
    return sorted(result, key=lambda q: q.index)


def transcripts_context(
    transcripts: Sequence[TranscriptContext | Mapping[str, Any]],
) -> list[TranscriptContext]:
    result = []
    for item in transcripts:
        if isinstance(item, TranscriptContext):
            result.append(item)
            continue
        data = dict(item)
        if "text" not in data and "transcript_text" in data:
            data["text"] = data.pop("transcript_text")
        result.append(TranscriptContext.model_validate(data))
    return result


def questions_from_snapshot(snapshot: list[dict[str, Any]] | None) -> list[QuestionContext]:
    return questions_context(
        [
            {
                "index": item.get("index", position),
                "id": item.get("id"),
                "text": item.get("text", ""),
                "expected_points": item.get("expected_points") or [],
                "competency_ids": item.get("competency_ids") or [],
            }
            for position, item in enumerate(snapshot or [])
        ]
    )


def pick_final_answers(answers: Sequence[Answer]) -> dict[int, Answer]:
    """Зачётный ответ на каждый вопрос среди помеченных ``is_final``."""
    chosen: dict[int, Answer] = {}
    for answer in answers:
        if not answer.is_final:
            continue
        current = chosen.get(answer.question_index)
        key = (_STATUS_RANK.get(answer.status, 0), answer.attempt)
        if current is None or key > (_STATUS_RANK.get(current.status, 0), current.attempt):
            chosen[answer.question_index] = answer
    return chosen


def transcripts_from_answers(
    questions: Sequence[QuestionContext], answers: Sequence[Answer]
) -> list[TranscriptContext]:
    finals = pick_final_answers(answers)
    result = []
    for question in questions:
        answer = finals.get(question.index)
        if answer is None:
            result.append(TranscriptContext(question_index=question.index, status="missing"))
            continue
        segments = [
            TranscriptSegmentContext(
                start_s=float(segment.get("start_s", 0) or 0),
                end_s=float(segment.get("end_s", 0) or 0),
                text=str(segment.get("text", "")),
            )
            for segment in answer.transcript_segments or []
            if isinstance(segment, Mapping)
        ]
        result.append(
            TranscriptContext(
                question_index=question.index,
                answer_id=str(answer.id),
                status=answer.status.value,
                text=answer.transcript_text if answer.status == AnswerStatus.done else None,
                segments=segments if answer.status == AnswerStatus.done else [],
                duration_s=(answer.duration_ms or 0) / 1000 or None,
            )
        )
    return result


def _redact_transcripts(
    transcripts: Sequence[TranscriptContext], redactor: Redactor
) -> list[TranscriptContext]:
    result = []
    for transcript in transcripts:
        result.append(
            transcript.model_copy(
                update={
                    "text": redactor.redact(transcript.text)
                    if transcript.text
                    else transcript.text,
                    "segments": [
                        segment.model_copy(update={"text": redactor.redact(segment.text)})
                        for segment in transcript.segments
                    ],
                }
            )
        )
    return result


def _evidence_of(output: EvaluationOutput) -> list[Evidence]:
    items: list[Evidence] = []
    for score in output.competency_scores:
        items.extend(score.evidence)
    for assessment in output.question_assessments:
        items.extend(assessment.evidence)
    for skill in output.skills:
        items.extend(skill.evidence)
    return items


def normalize_output(
    output: EvaluationOutput, transcripts: Sequence[TranscriptContext]
) -> EvaluationOutput:
    """Привести ссылки на ответы к известным answer_id и упорядочить вопросы.

    Модели ошибаются в длинных идентификаторах; question_index они копируют
    надёжно, поэтому answer_id восстанавливаем по нему.
    """
    known = {t.question_index: t.answer_id for t in transcripts if t.answer_id}
    for evidence in _evidence_of(output):
        expected = known.get(evidence.question_index)
        if expected and evidence.answer_id != expected:
            evidence.answer_id = expected
        evidence.quote = evidence.quote.strip()
    for assessment in output.question_assessments:
        expected = known.get(assessment.question_index)
        if expected and assessment.answer_id != expected:
            assessment.answer_id = expected
    output.question_assessments.sort(key=lambda item: item.question_index)
    return output


_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalized(text: str) -> str:
    return _WS_RE.sub(" ", _PUNCT_RE.sub("", text)).strip().lower()


def _transcript_texts(transcripts: Sequence[TranscriptContext]) -> dict[int, str]:
    return {
        t.question_index: _normalized(t.text or " ".join(segment.text for segment in t.segments))
        for t in transcripts
        if t.available or t.segments
    }


def _time_bounds(transcript: TranscriptContext | None) -> float | None:
    """Верхняя граница таймкодов ответа: конец последнего сегмента или длительность."""
    if transcript is None:
        return None
    if transcript.segments:
        return max(segment.end_s for segment in transcript.segments)
    return transcript.duration_s


def verify_quotes(
    output: EvaluationOutput, transcripts: Sequence[TranscriptContext]
) -> tuple[int, int]:
    """Проверить цитаты по транскриптам (с точностью до пунктуации и регистра).

    Проверять нужно по тем текстам, которые видела модель — после замены ПДн
    плейсхолдерами, иначе любая цитата с «[КАНДИДАТ]» считалась бы выдуманной.
    Каждая цитата получает ``verified``, таймкоды прижимаются к границам ответа.
    Возвращает (найдено, всего).
    """
    texts = _transcript_texts(transcripts)
    by_index = {t.question_index: t for t in transcripts}
    found = total = 0
    for evidence in _evidence_of(output):
        total += 1
        haystack = texts.get(evidence.question_index, "")
        needle = _normalized(evidence.quote.rstrip("…"))
        evidence.verified = bool(needle) and needle in haystack
        found += int(evidence.verified)
        limit = _time_bounds(by_index.get(evidence.question_index))
        if limit is not None:
            if evidence.start_s is not None:
                evidence.start_s = min(max(evidence.start_s, 0.0), limit)
            if evidence.end_s is not None:
                evidence.end_s = min(max(evidence.end_s, 0.0), limit)
        if (
            evidence.start_s is not None
            and evidence.end_s is not None
            and evidence.end_s < evidence.start_s
        ):
            evidence.start_s, evidence.end_s = evidence.end_s, evidence.start_s
    return found, total


# ---------------------------------------------------------------- оценка


async def evaluate_payload(
    vacancy: VacancyContext | Vacancy | Mapping[str, Any],
    questions: Sequence[QuestionContext | Mapping[str, Any]],
    transcripts: Sequence[TranscriptContext | Mapping[str, Any]],
    *,
    llm: LLMProvider | None = None,
    redactor: Redactor | None = None,
    settings: Settings | None = None,
) -> EvaluationResult:
    """Заключение и рекомендация без базы: вакансия, вопросы, транскрипты → результат."""
    vacancy_ctx = vacancy_context(vacancy)
    questions_ctx = questions_context(questions)
    transcripts_ctx = transcripts_context(transcripts)
    redactor = redactor or Redactor()
    safe_transcripts = _redact_transcripts(transcripts_ctx, redactor)
    messages = build_evaluation_messages(vacancy_ctx, questions_ctx, safe_transcripts)
    llm = llm or get_llm("evaluator", settings=settings)
    output, raw = await complete_structured(llm, messages, EvaluationOutput, temperature=0)
    output = normalize_output(output, transcripts_ctx)
    quotes_found, quotes_total = verify_quotes(output, safe_transcripts)
    rubric = [item.model_dump() for item in vacancy_ctx.rubric]
    scoring = score_output(output, rubric, thresholds=thresholds_from_settings(settings))
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else None
    return EvaluationResult(
        output=output,
        fit_score=scoring.fit_score,
        recommendation=scoring.recommendation,
        scoring=scoring,
        raw_response=raw,
        usage=usage,
        model=getattr(llm, "model", ""),
        redactions=len(redactor.replacements),
        quotes_found=quotes_found,
        quotes_total=quotes_total,
    )


async def generate_candidate_feedback(
    vacancy: VacancyContext | Vacancy | Mapping[str, Any],
    output: EvaluationOutput,
    *,
    llm: LLMProvider | None = None,
    settings: Settings | None = None,
) -> tuple[CandidateFeedback, dict[str, Any]]:
    llm = llm or get_llm("evaluator", settings=settings)
    messages = build_feedback_messages(vacancy_context(vacancy), output)
    return await complete_structured(llm, messages, CandidateFeedback, temperature=0.3)


async def _get_or_create(session: AsyncSession, interview_id: UUID) -> Evaluation:
    evaluation = await session.scalar(
        select(Evaluation).where(Evaluation.interview_id == interview_id)
    )
    if evaluation is not None:
        return evaluation
    evaluation = Evaluation(interview_id=interview_id, prompt_version=PROMPT_VERSION)
    session.add(evaluation)
    try:
        await session.flush()
    except IntegrityError:
        # Параллельная задача успела создать строку: берём её, а не падаем.
        await session.rollback()
        existing = await session.scalar(
            select(Evaluation).where(Evaluation.interview_id == interview_id)
        )
        if existing is None:
            raise
        return existing
    return evaluation


async def _load_interview(session: AsyncSession, interview_id: UUID) -> Interview:
    interview = await session.scalar(
        select(Interview)
        .where(Interview.id == interview_id)
        .options(selectinload(Interview.candidate))
        .execution_options(populate_existing=True)
    )
    if interview is None:
        raise NotFoundError("Интервью не найдено")
    return interview


async def final_answers(session: AsyncSession, interview_id: UUID) -> list[Answer]:
    rows = await session.scalars(
        select(Answer)
        .where(Answer.interview_id == interview_id, Answer.is_final.is_(True))
        .order_by(Answer.question_index, Answer.attempt)
    )
    return list(rows)


async def evaluate_interview(
    session: AsyncSession, interview_id: UUID, *, llm: LLMProvider | None = None
) -> Evaluation:
    """Оценить интервью в статусе ``processing`` и перевести его в ``evaluated``.

    Ошибка модели фиксируется в строке заключения (``failed`` + текст) и
    пробрасывается наружу: очередь повторит задачу с паузой.
    """
    interview = await _load_interview(session, interview_id)
    if interview.status != InterviewStatus.processing:
        raise ConflictError(
            f"Оценивать можно интервью в статусе processing, сейчас {interview.status.value}"
        )
    vacancy = await session.get(Vacancy, interview.vacancy_id)
    if vacancy is None:
        raise NotFoundError("Вакансия интервью не найдена")
    questions = questions_from_snapshot(interview.question_snapshot)
    transcripts = transcripts_from_answers(questions, await final_answers(session, interview_id))
    candidate = interview.candidate
    redactor = Redactor(
        full_name=interview.consent_full_name or candidate.full_name,
        email=interview.consent_email or candidate.email,
        phone=candidate.phone,
        extra_names=[candidate.full_name] if interview.consent_full_name else (),
    )
    llm = llm or get_llm("evaluator")

    evaluation = await _get_or_create(session, interview_id)
    interview = await _load_interview(session, interview_id)
    evaluation.status = EvaluationStatus.pending
    evaluation.model = llm.model
    evaluation.prompt_version = PROMPT_VERSION
    evaluation.error = None
    await session.commit()

    try:
        result = await evaluate_payload(vacancy, questions, transcripts, llm=llm, redactor=redactor)
    except Exception as error:
        evaluation.status = EvaluationStatus.failed
        evaluation.error = f"{type(error).__name__}: {error}"[:_MAX_ERROR_CHARS]
        await session.commit()
        raise

    if result.quotes_total and result.quotes_found < result.quotes_total:
        log.warning(
            "evaluation.quotes interview=%s verbatim=%s/%s",
            interview_id,
            result.quotes_found,
            result.quotes_total,
        )

    feedback: CandidateFeedback | None = None
    if vacancy.candidate_feedback_mode != CandidateFeedbackMode.off:
        try:
            feedback, _ = await generate_candidate_feedback(vacancy, result.output, llm=llm)
        except Exception as error:
            # Обратная связь вторична: заключение готово, письмо кандидату
            # подождёт переобработки — не тратим повтор всей оценки ни на
            # ошибку провайдера, ни на невалидный ответ.
            log.warning("evaluation.feedback interview=%s error=%s", interview_id, error)

    evaluation.status = EvaluationStatus.done
    evaluation.fit_score = result.fit_score
    evaluation.recommendation = result.recommendation
    evaluation.output = output_to_dict(result.output)
    evaluation.candidate_feedback = feedback.model_dump(mode="json") if feedback else None
    evaluation.raw_response = result.raw_response
    evaluation.usage = result.usage
    evaluation.error = None
    evaluation.quotes_found = result.quotes_found
    evaluation.quotes_total = result.quotes_total
    evaluation.evaluated_at = utcnow()
    transition(interview, InterviewStatus.evaluated)
    await session.commit()

    # Письма — после коммита заключения: сбой рассылки не должен отменять оценку.
    try:
        await notify_evaluation_ready(
            session,
            interview,
            fit_score=result.fit_score,
            recommendation=result.recommendation,
        )
        await schedule_candidate_feedback(
            session, interview, decided=interview.decision is not None
        )
        await session.commit()
    except Exception:
        await session.rollback()
        log.exception("evaluation.notify interview=%s failed", interview_id)
    log.info(
        "evaluation.done interview=%s fit=%s recommendation=%s reasons=%s "
        "redactions=%s quotes=%s/%s",
        interview_id,
        result.fit_score,
        result.recommendation,
        "; ".join(result.scoring.reasons),
        result.redactions,
        result.quotes_found,
        result.quotes_total,
    )
    return evaluation


# ---------------------------------------------------------------- чтение


async def get_evaluation(
    session: AsyncSession, actor: Actor, interview_id: UUID
) -> tuple[Interview, Evaluation | None]:
    interview = await InterviewService(session).get(actor, interview_id)
    authorize(actor, "interview.read", vacancy_id=interview.vacancy_id)
    evaluation = await session.scalar(
        select(Evaluation)
        .where(Evaluation.interview_id == interview.id)
        .execution_options(populate_existing=True)
    )
    return interview, evaluation


def ranking_sort_key(item: RankingItem) -> tuple[int, float, str]:
    """«Нужна проверка» закреплены сверху, дальше по fit_score, неоценённые — в конце."""
    if item.recommendation == "needs_check":
        group = 0
    elif item.fit_score is not None:
        group = 1
    else:
        group = 2
    return (group, -(item.fit_score or 0.0), item.candidate_name.lower())


async def ranking(session: AsyncSession, actor: Actor, vacancy_id: UUID) -> list[RankingItem]:
    vacancy = await session.scalar(
        select(Vacancy).where(
            Vacancy.id == vacancy_id, Vacancy.organization_id == actor.organization_id
        )
    )
    if vacancy is None:
        raise NotFoundError("Вакансия не найдена")
    # authorize сверяет vacancy_id со scope нанимающего менеджера (visible_vacancy_ids).
    authorize(actor, "report.read", vacancy_id=vacancy.id)
    rows = await session.execute(
        select(Interview, Evaluation)
        .outerjoin(Evaluation, Evaluation.interview_id == Interview.id)
        .where(
            Interview.vacancy_id == vacancy.id,
            Interview.status.notin_([InterviewStatus.cancelled, InterviewStatus.expired]),
        )
        .options(selectinload(Interview.candidate))
        .execution_options(populate_existing=True)
    )
    items = []
    for interview, evaluation in rows.all():
        done = evaluation is not None and evaluation.status == EvaluationStatus.done
        items.append(
            RankingItem(
                interview_id=str(interview.id),
                candidate_id=str(interview.candidate_id),
                candidate_name=interview.candidate.full_name,
                candidate_email=interview.candidate.email,
                status=interview.status.value,
                fit_score=evaluation.fit_score if done else None,
                recommendation=evaluation.recommendation if done else None,  # type: ignore[arg-type]
                evaluated_at=aware(evaluation.evaluated_at) if done else None,
                decision=interview.decision,
                completed_at=aware(interview.completed_at),
            )
        )
    return sorted(items, key=ranking_sort_key)
