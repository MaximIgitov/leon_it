"""Ссылка отписки от писем LeonIT.

Токен подписанный и без состояния: в нём id кандидата и тип, срок — год.
Отдельной таблицы не нужно, а подделать ссылку нельзя — подпись на
``JWT_SECRET``. Отписка снимает ``newsletter_opt_in`` у кандидата и пишет запись
в журнал согласий, поэтому отказ виден рекрутеру там же, где само согласие.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from jose import JWTError, jwt

from leonit.core.config import Settings, get_settings
from leonit.core.time import utcnow

TOKEN_TYPE = "unsubscribe"
TOKEN_TTL = timedelta(days=365)


def sign_unsubscribe_token(candidate_id: UUID, *, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    payload = {
        "sub": str(candidate_id),
        "typ": TOKEN_TYPE,
        "exp": utcnow() + TOKEN_TTL,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_unsubscribe_token(token: str, *, settings: Settings | None = None) -> UUID | None:
    """Вернуть id кандидата или None, если подпись, тип или срок не годятся."""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("typ") != TOKEN_TYPE:
        return None
    try:
        return UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        return None


def unsubscribe_link(candidate_id: UUID, *, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    token = sign_unsubscribe_token(candidate_id, settings=settings)
    return f"{settings.PUBLIC_URL}/unsubscribe/{token}"
