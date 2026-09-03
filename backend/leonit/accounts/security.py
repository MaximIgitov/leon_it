"""Пароли, JWT и токены ссылок."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from uuid import UUID

from jose import JWTError, jwt

from leonit.core.config import Settings
from leonit.core.time import utcnow

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 390_000

# Корректно устроенный хеш случайного пароля: проверяется для несуществующих
# аккаунтов, чтобы время ответа не выдавало, зарегистрирован ли e-mail.
DUMMY_PASSWORD_HASH = (
    f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}"
    "$timing-equalizer$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)


def hash_password(password: str) -> str:
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_HASH_ITERATIONS
    )
    encoded = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}${salt}${encoded}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != PASSWORD_HASH_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        )
        encoded = base64.urlsafe_b64encode(digest).decode("ascii")
        return hmac.compare_digest(encoded, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(settings: Settings, *, user_id: UUID, token_version: int) -> str:
    expires_at = utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "tv": token_version, "exp": expires_at, "typ": "access"}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> tuple[UUID, int] | None:
    """Вернуть (user_id, token_version) или None, если токен не годится."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("typ") != "access":
        return None
    try:
        return UUID(str(payload.get("sub"))), int(payload.get("tv", 0))
    except (ValueError, TypeError):
        return None


def generate_link_token() -> str:
    """Токен для ссылок (приглашения, отчёты): 256 бит, только URL-безопасные символы."""
    return secrets.token_urlsafe(32)


def hash_link_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
