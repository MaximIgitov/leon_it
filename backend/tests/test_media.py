from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from jose import jwt

from leonit.core.config import get_settings
from leonit.core.errors import PermissionDeniedError
from leonit.core.storage import get_storage
from leonit.core.time import utcnow
from leonit.media.router import ByteRange, RangeNotSatisfiable, parse_range
from leonit.media.service import (
    guess_content_type,
    is_inline_safe,
    sign_media_url,
    verify_media_token,
)

BODY = b"0123456789abcdef"


@pytest.fixture
async def key() -> str:
    key = "answers/42/video.webm"
    await get_storage().put(key, BODY)
    return key


def test_sign_and_verify_roundtrip(key: str) -> None:
    url = sign_media_url(key, ttl_s=60, content_type="video/webm", filename="ответ.webm")
    assert url.startswith("/api/media/")
    claims = verify_media_token(url.rsplit("/", 1)[-1])
    assert claims.key == key
    assert claims.content_type == "video/webm"
    assert claims.filename == "ответ.webm"


def test_expired_and_forged_tokens_are_rejected(key: str) -> None:
    settings = get_settings()
    expired = jwt.encode(
        {"typ": "media", "key": key, "exp": utcnow() - timedelta(seconds=1)},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(PermissionDeniedError, match="expired"):
        verify_media_token(expired)

    token = sign_media_url(key).rsplit("/", 1)[-1]
    with pytest.raises(PermissionDeniedError):
        verify_media_token(token[:-3] + "xyz")

    # Access-токен сотрудника на том же секрете не должен открывать файлы.
    access = jwt.encode(
        {"sub": "user", "key": key, "exp": utcnow() + timedelta(minutes=5)},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(PermissionDeniedError):
        verify_media_token(access)


async def test_get_full_file(client: AsyncClient, key: str) -> None:
    response = await client.get(sign_media_url(key, content_type="video/webm"))
    assert response.status_code == 200
    assert response.content == BODY
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(BODY))
    assert response.headers["content-type"] == "video/webm"
    assert response.headers["cache-control"].startswith("private, max-age=")
    assert response.headers["content-disposition"] == "inline"


async def test_content_type_guessed_from_key(client: AsyncClient, key: str) -> None:
    response = await client.get(sign_media_url(key))
    assert response.headers["content-type"] == "video/webm"
    assert guess_content_type("x/y.mp3") == "audio/mpeg"
    assert guess_content_type("x/y.unknownext") == "application/octet-stream"


@pytest.mark.parametrize(
    ("header", "status", "expected", "content_range"),
    [
        ("bytes=2-5", 206, BODY[2:6], "bytes 2-5/16"),
        ("bytes=10-", 206, BODY[10:], "bytes 10-15/16"),
        ("bytes=-4", 206, BODY[-4:], "bytes 12-15/16"),
        ("bytes=0-100", 206, BODY, "bytes 0-15/16"),
        ("bytes=0-15", 206, BODY, "bytes 0-15/16"),
    ],
)
async def test_range_requests(
    client: AsyncClient, key: str, header: str, status: int, expected: bytes, content_range: str
) -> None:
    response = await client.get(sign_media_url(key), headers={"Range": header})
    assert response.status_code == status
    assert response.content == expected
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(expected))


async def test_unsatisfiable_range_returns_416(client: AsyncClient, key: str) -> None:
    response = await client.get(sign_media_url(key), headers={"Range": "bytes=16-20"})
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */16"
    assert response.content == b""


async def test_malformed_range_falls_back_to_full_body(client: AsyncClient, key: str) -> None:
    response = await client.get(sign_media_url(key), headers={"Range": "items=1-2"})
    assert response.status_code == 200 and response.content == BODY


async def test_inverted_range_is_ignored(client: AsyncClient, key: str) -> None:
    # Конец раньше начала — по RFC 9110 диапазон недействителен и игнорируется:
    # 200 с целым файлом, а не отрицательный Content-Length и падение отдачи.
    response = await client.get(sign_media_url(key), headers={"Range": "bytes=5-2"})
    assert response.status_code == 200
    assert response.content == BODY
    assert response.headers["content-length"] == str(len(BODY))
    assert "content-range" not in response.headers


async def test_head_with_unsatisfiable_range_returns_416(client: AsyncClient, key: str) -> None:
    response = await client.head(sign_media_url(key), headers={"Range": "bytes=16-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */16"
    assert response.content == b""


async def test_non_media_content_type_is_served_as_attachment(
    client: AsyncClient, key: str
) -> None:
    # «Резюме» с text/html, отрисованное inline на нашем origin, — stored-XSS.
    response = await client.get(
        sign_media_url(key, content_type="text/html", filename="resume.html")
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html"
    assert response.headers["content-disposition"].startswith('attachment; filename="resume.html"')
    assert response.headers["content-security-policy"] == "sandbox"

    inline = await client.get(sign_media_url(key, content_type="video/webm"))
    assert inline.headers["content-disposition"] == "inline"
    assert inline.headers["content-security-policy"] == "sandbox"

    unsatisfiable = await client.get(sign_media_url(key), headers={"Range": "bytes=99-"})
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["content-security-policy"] == "sandbox"


@pytest.mark.parametrize(
    ("content_type", "inline"),
    [
        ("video/webm", True),
        ("audio/mpeg; codecs=mp3", True),
        ("image/png", True),
        ("application/pdf", True),
        ("Application/PDF", True),
        ("image/svg+xml", False),
        ("text/html", False),
        ("text/html; charset=utf-8", False),
        ("application/json", False),
        ("application/octet-stream", False),
    ],
)
def test_is_inline_safe(content_type: str, inline: bool) -> None:
    assert is_inline_safe(content_type) is inline


async def test_token_without_exp_is_rejected(client: AsyncClient, key: str) -> None:
    settings = get_settings()
    eternal = jwt.encode(
        {"typ": "media", "key": key}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    with pytest.raises(PermissionDeniedError, match="invalid media link"):
        verify_media_token(eternal)
    assert (await client.get(f"/api/media/{eternal}")).status_code == 403


async def test_head_returns_headers_without_body(client: AsyncClient, key: str) -> None:
    response = await client.head(sign_media_url(key, filename="answer.webm"))
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == "16"
    assert response.headers["accept-ranges"] == "bytes"
    assert 'filename="answer.webm"' in response.headers["content-disposition"]

    partial = await client.head(sign_media_url(key), headers={"Range": "bytes=0-1"})
    assert partial.status_code == 206
    assert partial.headers["content-range"] == "bytes 0-1/16"
    assert partial.content == b""


async def test_expired_forged_and_missing_over_http(client: AsyncClient, key: str) -> None:
    settings = get_settings()
    expired = jwt.encode(
        {"typ": "media", "key": key, "exp": utcnow() - timedelta(seconds=1)},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert (await client.get(f"/api/media/{expired}")).status_code == 403
    assert (await client.get("/api/media/not-a-token")).status_code == 403
    missing = sign_media_url("answers/0/nothing.webm")
    assert (await client.get(missing)).status_code == 404


def test_parse_range_edge_cases() -> None:
    assert parse_range(None, 10) is None
    assert parse_range("bytes=0-0", 10) == ByteRange(0, 0)
    assert parse_range("bytes=-100", 10) == ByteRange(0, 9)
    assert parse_range("bytes=1-2,4-5", 10) is None
    assert parse_range("bytes=abc", 10) is None
    assert parse_range("bytes=5-2", 10) is None
    assert parse_range("bytes=20-16", 10) is None
    assert parse_range("bytes=9-9", 10) == ByteRange(9, 9)
    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=10-", 10)
    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=0-", 0)
    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=-1", 0)
