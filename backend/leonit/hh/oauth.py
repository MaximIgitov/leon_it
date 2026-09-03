"""OAuth-состояние и PKCE.

``state`` — подписанный короткоживущий JWT с организацией, инициатором и
nonce, а verifier PKCE лежит внутри него в зашифрованном виде: ничего не нужно
хранить до callback, подделать или переиспользовать после истечения нельзя,
а прочитать verifier из адресной строки — тоже.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from jose import JWTError, jwt

from leonit.core.config import Settings
from leonit.core.crypto import SecretBox, SecretBoxError
from leonit.core.time import utcnow

STATE_TTL = timedelta(minutes=10)
_TYP = "hh_oauth"


@dataclass(frozen=True, slots=True)
class OAuthState:
    organization_id: UUID
    user_id: UUID
    code_verifier: str
    nonce: str


def make_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge) по RFC 7636, метод S256."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def make_state(
    settings: Settings,
    box: SecretBox,
    *,
    organization_id: UUID,
    user_id: UUID,
    code_verifier: str,
) -> str:
    payload = {
        "typ": _TYP,
        "org": str(organization_id),
        "sub": str(user_id),
        "cv": box.encrypt(code_verifier),
        "nonce": secrets.token_urlsafe(16),
        "exp": utcnow() + STATE_TTL,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def parse_state(settings: Settings, box: SecretBox, state: str) -> OAuthState | None:
    """Вернуть содержимое state или None, если подпись/срок/формат не годятся."""
    try:
        payload = jwt.decode(state, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("typ") != _TYP:
        return None
    try:
        return OAuthState(
            organization_id=UUID(str(payload["org"])),
            user_id=UUID(str(payload["sub"])),
            code_verifier=box.decrypt(str(payload["cv"])),
            nonce=str(payload.get("nonce") or ""),
        )
    except (KeyError, ValueError, TypeError, SecretBoxError):
        return None
