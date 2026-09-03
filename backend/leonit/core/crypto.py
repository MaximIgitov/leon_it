"""Шифрование секретов интеграций (OAuth-токены HH.ru, ключи Huntflow и т. п.).

Значения хранятся в БД только в зашифрованном виде: утечка дампа базы не должна
давать доступ к чужим кабинетам. Используется Fernet (AES-128-CBC + HMAC) с
поддержкой ротации: расшифровка пробует все ключи, шифрование — первый.

Ключи задаются через ``DATA_ENCRYPTION_KEY`` (основной) и
``DATA_ENCRYPTION_KEYS_SECONDARY`` (старые, через запятую). Вне production при
пустом ключе используется производный от ``JWT_SECRET`` — чтобы локальный стенд
и тесты работали без лишней настройки; в production пустой ключ — ошибка старта
(см. валидатор в ``core.config``).
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from leonit.core.config import Settings, get_settings

__all__ = ["SecretBox", "SecretBoxError", "generate_key", "get_secret_box"]


class SecretBoxError(ValueError):
    """Значение не удалось расшифровать: ключ сменился или данные повреждены."""


def generate_key() -> str:
    """Сгенерировать новый ключ Fernet (для .env: ``python -m leonit.core.crypto``)."""
    return Fernet.generate_key().decode("ascii")


def _derive_key(secret: str) -> str:
    digest = hashlib.sha256(f"leonit-data-key:{secret}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


class SecretBox:
    """Обёртка над MultiFernet с текстовым интерфейсом."""

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("SecretBox requires at least one key")
        self._fernet = MultiFernet([Fernet(key.encode("ascii")) for key in keys])

    @classmethod
    def from_settings(cls, settings: Settings) -> SecretBox:
        keys = [settings.DATA_ENCRYPTION_KEY] if settings.DATA_ENCRYPTION_KEY else []
        keys += [k.strip() for k in settings.DATA_ENCRYPTION_KEYS_SECONDARY.split(",") if k.strip()]
        if not keys:
            keys = [_derive_key(settings.JWT_SECRET)]
        return cls(keys)

    def encrypt(self, plain: str) -> str:
        return self._fernet.encrypt(plain.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise SecretBoxError("cannot decrypt stored secret") from exc

    def rotate(self, token: str) -> str:
        """Перешифровать значение первым (актуальным) ключом."""
        return self._fernet.rotate(token.encode("ascii")).decode("ascii")


@lru_cache
def get_secret_box() -> SecretBox:
    return SecretBox.from_settings(get_settings())


if __name__ == "__main__":  # pragma: no cover - утилита для .env
    print(generate_key())
