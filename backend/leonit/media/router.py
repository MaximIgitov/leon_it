"""Отдача файлов по подписанной ссылке с поддержкой Range.

Диапазоны нужны видеоплееру: перемотка к цитате в отчёте — это запрос
``Range: bytes=N-``. Потоковая отдача реализована поверх ``Storage.open_range``,
а не ``FileResponse``, чтобы роутер не зависел от локальной файловой системы и
одинаково работал с любым хранилищем.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from leonit.core.errors import NotFoundError
from leonit.core.storage import get_storage
from leonit.media.service import guess_content_type, verify_media_token

router = APIRouter(tags=["media"])

_MAX_CACHE_S = 3600


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int  # включительно, как в HTTP

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class RangeNotSatisfiable(Exception):
    pass


def parse_range(header: str | None, size: int) -> ByteRange | None:
    """Разобрать один диапазон ``bytes=a-b`` / ``bytes=a-`` / ``bytes=-n``.

    Несколько диапазонов (multipart/byteranges) браузеры для видео не
    запрашивают; такой заголовок игнорируем и отдаём файл целиком, как
    разрешает RFC 9110.
    """
    if not header:
        return None
    unit, _, spec = header.strip().partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first, dash, last = spec.strip().partition("-")
    if not dash:
        return None
    try:
        if first == "":
            if last == "":
                return None
            suffix = int(last)
            if suffix <= 0 or size == 0:
                raise RangeNotSatisfiable
            return ByteRange(max(size - suffix, 0), size - 1)
        start = int(first)
        end = int(last) if last != "" else size - 1
    except ValueError:
        return None
    if start >= size or start < 0:
        raise RangeNotSatisfiable
    return ByteRange(start, min(end, size - 1))


def _content_disposition(filename: str | None) -> str:
    if not filename:
        return "inline"
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "")
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.api_route("/media/{token}", methods=["GET", "HEAD"])
async def get_media(token: str, request: Request) -> Response:
    claims = verify_media_token(token)
    storage = get_storage()
    if not await storage.exists(claims.key):
        raise NotFoundError("file not found")
    size = await storage.size(claims.key)

    # Ссылка и так живёт недолго; кэш в пределах её срока ускоряет перемотку.
    max_age = max(min(claims.expires_at - int(time.time()), _MAX_CACHE_S), 0)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": claims.content_type or guess_content_type(claims.key),
        "Content-Disposition": _content_disposition(claims.filename),
        "Cache-Control": f"private, max-age={max_age}",
    }
    try:
        byte_range = parse_range(request.headers.get("range"), size)
    except RangeNotSatisfiable:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        )

    if byte_range is None:
        status_code, start, end_exclusive = 200, 0, size
        headers["Content-Length"] = str(size)
    else:
        status_code, start, end_exclusive = 206, byte_range.start, byte_range.end + 1
        headers["Content-Length"] = str(byte_range.length)
        headers["Content-Range"] = f"bytes {byte_range.start}-{byte_range.end}/{size}"

    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers)
    return StreamingResponse(
        storage.open_range(claims.key, start, end_exclusive),
        status_code=status_code,
        headers=headers,
    )
