from __future__ import annotations

import pytest

from leonit.core.config import Settings
from leonit.core.crypto import SecretBox, SecretBoxError, generate_key


def test_roundtrip_and_ciphertext_differs() -> None:
    box = SecretBox([generate_key()])
    token = box.encrypt("access-token-секрет")
    assert token != "access-token-секрет"
    assert box.decrypt(token) == "access-token-секрет"


def test_secondary_key_decrypts_and_rotate_reencrypts() -> None:
    old_key, new_key = generate_key(), generate_key()
    old_box = SecretBox([old_key])
    token = old_box.encrypt("value")
    box = SecretBox([new_key, old_key])
    assert box.decrypt(token) == "value"
    rotated = box.rotate(token)
    assert SecretBox([new_key]).decrypt(rotated) == "value"
    with pytest.raises(SecretBoxError):
        SecretBox([new_key]).decrypt(token)


def test_wrong_key_or_garbage_raises_domain_error() -> None:
    box = SecretBox([generate_key()])
    with pytest.raises(SecretBoxError):
        box.decrypt("not-a-token")


def test_from_settings_derives_key_outside_production() -> None:
    a = SecretBox.from_settings(Settings(JWT_SECRET="secret-a"))
    b = SecretBox.from_settings(Settings(JWT_SECRET="secret-a"))
    other = SecretBox.from_settings(Settings(JWT_SECRET="secret-b"))
    token = a.encrypt("x")
    assert b.decrypt(token) == "x"
    with pytest.raises(SecretBoxError):
        other.decrypt(token)


def test_from_settings_uses_explicit_keys() -> None:
    key, secondary = generate_key(), generate_key()
    settings = Settings(DATA_ENCRYPTION_KEY=key, DATA_ENCRYPTION_KEYS_SECONDARY=f" {secondary} ,")
    box = SecretBox.from_settings(settings)
    assert box.decrypt(SecretBox([secondary]).encrypt("legacy")) == "legacy"
    assert SecretBox([key]).decrypt(box.encrypt("fresh")) == "fresh"


def test_production_requires_encryption_key() -> None:
    with pytest.raises(ValueError, match="DATA_ENCRYPTION_KEY"):
        Settings(ENVIRONMENT="production", JWT_SECRET="x" * 40, CORS_ORIGINS=["https://e.com"])
    Settings(
        ENVIRONMENT="production",
        JWT_SECRET="x" * 40,
        CORS_ORIGINS=["https://e.com"],
        DATA_ENCRYPTION_KEY=generate_key(),
        MODEL_ALLOW_FAKE_IN_PRODUCTION=True,
    )


def test_empty_key_list_rejected() -> None:
    with pytest.raises(ValueError):
        SecretBox([])
