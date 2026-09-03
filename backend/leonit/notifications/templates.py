"""Тексты писем. Только plain text: письма читают и в почтовых клиентах без HTML."""

from __future__ import annotations

from datetime import datetime


def _date(value: datetime) -> str:
    return value.strftime("%d.%m.%Y")


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
