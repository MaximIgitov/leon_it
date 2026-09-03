"""Подписанные ссылки на файлы хранилища.

Медиа отдаётся только по короткоживущему токену: ключ хранилища никогда не
попадает в URL, а срок жизни ограничивает ущерб от утёкшей ссылки (отчёт
переслали, ссылка попала в логи прокси). Токен — JWT на том же секрете, что и
сессии сотрудников, поэтому в нём обязателен ``typ=media``: иначе access-токен
пользователя можно было бы подставить вместо ссылки на файл и наоборот.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePosixPath

from jose import ExpiredSignatureError, JWTError, jwt

from leonit.core.config import Settings, get_settings
from leonit.core.errors import PermissionDeniedError
from leonit.core.storage import normalize_key
from leonit.core.time import utcnow

DEFAULT_TTL_S = 900
_TOKEN_TYPE = "media"

# mimetypes на разных ОС знает разное; наши форматы фиксируем явно.
_CONTENT_TYPES: dict[str, str] = {
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


# Что браузеру можно показывать прямо в окне. Всё остальное отдаётся как
# attachment: Content-Type в токене задаёт тот, кто подписывает ссылку, а файл
# загрузил кандидат — «резюме» в виде text/html, открытое inline на нашем
# origin, было бы stored-XSS. SVG исключён из image/*: это документ со скриптами.
_INLINE_TYPE_PREFIXES = ("audio/", "video/", "image/")
_INLINE_TYPES = frozenset({"application/pdf"})
_INLINE_DENIED = frozenset({"image/svg+xml"})


@dataclass(frozen=True, slots=True)
class MediaClaims:
    key: str
    content_type: str | None
    filename: str | None
    expires_at: int


def is_inline_safe(content_type: str) -> bool:
    """Можно ли отдавать файл этого типа с ``Content-Disposition: inline``."""
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type in _INLINE_DENIED:
        return False
    return media_type in _INLINE_TYPES or media_type.startswith(_INLINE_TYPE_PREFIXES)


def guess_content_type(key: str) -> str:
    suffix = PurePosixPath(key).suffix.lower()
    if suffix in _CONTENT_TYPES:
        return _CONTENT_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(key)
    return guessed or "application/octet-stream"


def sign_media_url(
    key: str,
    *,
    ttl_s: int = DEFAULT_TTL_S,
    content_type: str | None = None,
    filename: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Вернуть путь ``/api/media/{token}`` для ключа хранилища."""
    settings = settings or get_settings()
    if ttl_s <= 0:
        raise ValueError("ttl_s must be positive")
    claims: dict[str, object] = {
        "typ": _TOKEN_TYPE,
        "key": normalize_key(key),
        "exp": utcnow() + timedelta(seconds=ttl_s),
    }
    if content_type:
        claims["ct"] = content_type
    if filename:
        claims["fn"] = filename
    token = jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return f"{settings.API_PREFIX}/media/{token}"


def verify_media_token(token: str, *, settings: Settings | None = None) -> MediaClaims:
    settings = settings or get_settings()
    try:
        # Без exp ссылка жила бы вечно, а бессрочный доступ к файлу кандидата —
        # ровно то, от чего подписанные ссылки защищают.
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require_exp": True},
        )
    except ExpiredSignatureError as error:
        raise PermissionDeniedError("media link has expired") from error
    except JWTError as error:
        raise PermissionDeniedError("invalid media link") from error
    if payload.get("typ") != _TOKEN_TYPE or not isinstance(payload.get("key"), str):
        raise PermissionDeniedError("invalid media link")
    try:
        key = normalize_key(payload["key"])
    except Exception as error:
        raise PermissionDeniedError("invalid media link") from error
    return MediaClaims(
        key=key,
        content_type=payload.get("ct"),
        filename=payload.get("fn"),
        expires_at=int(payload["exp"]),
    )
