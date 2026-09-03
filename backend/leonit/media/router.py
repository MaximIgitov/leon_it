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
from leonit.media.service import guess_content_type, is_inline_safe, verify_media_token

router = APIRouter(tags=["media"])

_MAX_CACHE_S = 3600
# Медиа-ответ — чужой файл на нашем origin: sandbox лишает его скриптов, форм и
# доступа к origin, даже если браузер решит отрисовать его как документ.
_MEDIA_CSP = "sandbox"


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
    разрешает RFC 9110. Синтаксически неверный диапазон (``bytes=5-2``, конец
    раньше начала) по тому же RFC не ошибка, а отсутствие заголовка — тоже 200.
    ``RangeNotSatisfiable`` — только для корректного диапазона за концом файла.
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
    # Явный конец раньше начала — синтаксически неверный диапазон (игнорируем);
    # отсутствующий конец значит «до конца файла» и за начало не отвечает.
    if start < 0 or (last != "" and end < start):
        return None
    if start >= size:
        raise RangeNotSatisfiable
    byte_range = ByteRange(start, min(end, size - 1))
    # Длина проверяется до того, как из диапазона соберут заголовки: отрицательный
    # Content-Length уходит клиенту раньше, чем упадёт отдача тела.
    if byte_range.length <= 0:
        raise RangeNotSatisfiable
    return byte_range


def _content_disposition(filename: str | None, content_type: str) -> str:
    disposition = "inline" if is_inline_safe(content_type) else "attachment"
    if not filename:
        return disposition
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


# HEAD обслуживается тем же обработчиком, но в схему не попадает: FastAPI дал бы
# обеим операциям один operation_id и предупреждал о дубле, а плееру HEAD нужен
# только для размера файла.
@router.api_route("/media/{token}", methods=["HEAD"], include_in_schema=False)
@router.get("/media/{token}")
async def get_media(token: str, request: Request) -> Response:
    claims = verify_media_token(token)
    storage = get_storage()
    if not await storage.exists(claims.key):
        raise NotFoundError("file not found")
    size = await storage.size(claims.key)

    # Ссылка и так живёт недолго; кэш в пределах её срока ускоряет перемотку.
    max_age = max(min(claims.expires_at - int(time.time()), _MAX_CACHE_S), 0)
    content_type = claims.content_type or guess_content_type(claims.key)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
        "Content-Disposition": _content_disposition(claims.filename, content_type),
        "Content-Security-Policy": _MEDIA_CSP,
        "Cache-Control": f"private, max-age={max_age}",
    }
    try:
        byte_range = parse_range(request.headers.get("range"), size)
    except RangeNotSatisfiable:
        return Response(
            status_code=416,
            headers={
                "Content-Range": f"bytes */{size}",
                "Accept-Ranges": "bytes",
                "Content-Security-Policy": _MEDIA_CSP,
            },
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
