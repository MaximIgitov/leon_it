"""Тексты писем. Только plain text: письма читают и в почтовых клиентах без HTML."""

from __future__ import annotations

from datetime import datetime


def _date(value: datetime) -> str:
    return value.strftime("%d.%m.%Y")


def reminder_email(
    *,
    candidate_name: str,
    organization_name: str,
    vacancy_title: str,
    link: str,
    expires_at: datetime,
    estimated_minutes: int,
) -> tuple[str, str]:
    """Напоминание перед истечением ссылки. Служебное письмо, а не рассылка."""
    subject = f"Напоминание: интервью на позицию «{vacancy_title}» ждёт вас"
    body = (
        f"Здравствуйте, {candidate_name}!\n\n"
        f"Вы получили приглашение на видеоинтервью от компании {organization_name} "
        f"на позицию «{vacancy_title}», но пока не завершили его.\n\n"
        f"Ссылка действует до {_date(expires_at)} — после этого пройти интервью будет "
        f"нельзя. Это займёт около {estimated_minutes} минут; если прерваться, можно "
        f"вернуться по той же ссылке и продолжить с первого неотвеченного вопроса.\n\n"
        f"Ссылка на интервью:\n{link}\n\n"
        f"Если вы передумали участвовать, просто не открывайте ссылку: "
        f"напоминание больше не придёт.\n\n"
        f"Команда {organization_name}"
    )
    return subject, body


def evaluation_ready_email(
    *,
    recipient_name: str | None,
    candidate_name: str,
    vacancy_title: str,
    link: str,
    recommendation: str | None,
    fit_score: float | None,
    updated: bool = False,
) -> tuple[str, str]:
    """Письмо рекрутеру и нанимающему менеджеру: заключение по кандидату готово."""
    labels = {
        "fit": "подходит",
        "no_fit": "не подходит",
        "needs_check": "требуется дополнительная проверка",
    }
    what = "обновлено" if updated else "готово"
    subject = f"Заключение {what}: {candidate_name} — {vacancy_title}"
    greeting = f"Здравствуйте, {recipient_name}!" if recipient_name else "Здравствуйте!"
    verdict = labels.get(recommendation or "", "оценка не рассчитана")
    score = f", соответствие {fit_score:.0f} из 100" if fit_score is not None else ""
    body = (
        f"{greeting}\n\n"
        f"По кандидату {candidate_name} на позицию «{vacancy_title}» {what} заключение: "
        f"{verdict}{score}.\n\n"
        f"Это рекомендация системы по ответам кандидата — решение принимаете вы. "
        f"В карточке есть запись интервью, транскрипт, баллы по компетенциям и цитаты, "
        f"на которые опирается заключение.\n\n"
        f"Открыть карточку кандидата:\n{link}\n\n"
        f"LeonIT"
    )
    return subject, body


def candidate_feedback_email(
    *,
    organization_name: str,
    vacancy_title: str,
    greeting: str,
    strengths: list[str],
    suggestions: list[str],
    closing: str,
    unsubscribe_link: str,
) -> tuple[str, str]:
    """Обратная связь кандидату: без баллов, рекомендации и решения по найму."""
    subject = f"Обратная связь по интервью — {vacancy_title}"
    lines = [
        greeting.strip(),
        "",
        f"Спасибо, что прошли видеоинтервью на позицию «{vacancy_title}» "
        f"в компании {organization_name}. Вот что мы заметили в ваших ответах.",
        "",
        "Сильные стороны:",
        *(f"— {item.strip()}" for item in strengths),
        "",
        "На что обратить внимание:",
        *(f"— {item.strip()}" for item in suggestions),
        "",
        closing.strip(),
        "",
        f"Команда {organization_name}",
        "",
        "Это письмо с обратной связью по вашему интервью. "
        f"Отказаться от писем LeonIT:\n{unsubscribe_link}",
    ]
    return subject, "\n".join(lines)


def invitation_email(
    *,
    candidate_name: str,
    organization_name: str,
    vacancy_title: str,
    link: str,
    expires_at: datetime,
    question_count: int,
    estimated_minutes: int,
) -> tuple[str, str]:
    subject = f"Приглашение на видеоинтервью — {vacancy_title}"
    body = (
        f"Здравствуйте, {candidate_name}!\n\n"
        f"{organization_name} приглашает вас пройти видеоинтервью на позицию "
        f"«{vacancy_title}».\n\n"
        f"Интервью проходит онлайн в удобное для вас время: вопросы задаются по одному, "
        f"ответы записываются на камеру. Вопросов: {question_count}, это займёт около "
        f"{estimated_minutes} минут. Понадобятся камера, микрофон и тихое место.\n\n"
        f"Ссылка на интервью:\n{link}\n\n"
        f"Ссылка действует до {_date(expires_at)}. Если прерваться, можно вернуться по той же "
        f"ссылке и продолжить с первого неотвеченного вопроса.\n\n"
        f"Перед началом мы попросим подтвердить имя и e-mail и дать согласие на обработку "
        f"персональных данных.\n\n"
        f"Удачи!\nКоманда {organization_name}"
    )
    return subject, body


def interview_completed_email(
    *,
    recipient_name: str | None,
    candidate_name: str,
    vacancy_title: str,
    link: str,
) -> tuple[str, str]:
    subject = f"Интервью завершено: {candidate_name} — {vacancy_title}"
    greeting = f"Здравствуйте, {recipient_name}!" if recipient_name else "Здравствуйте!"
    body = (
        f"{greeting}\n\n"
        f"Кандидат {candidate_name} завершил(а) видеоинтервью на позицию «{vacancy_title}». "
        f"Ответы обрабатываются: транскрипт и заключение появятся в карточке через "
        f"несколько минут.\n\n"
        f"Открыть карточку кандидата:\n{link}\n\n"
        f"LeonIT"
    )
    return subject, body
