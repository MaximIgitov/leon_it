"""Хранилище файлов: видео и аудио ответов, снимки, резюме, кэш озвучки.

Абстракция ``Storage`` нужна, чтобы код предметных областей не знал про
файловую систему: сегодня это локальный том, завтра — S3-совместимое хранилище.
Наружу файлы не публикуются как статика — только через подписанные ссылки
(``leonit.media``), поэтому ключ хранилища никогда не совпадает с URL.

Ключ — путь в POSIX-стиле относительно корня (``answers/<id>/video.webm``).
Любая попытка выйти за корень (``..``, абсолютный путь, диск Windows) —
ошибка валидации, а не тихая нормализация: такие ключи не возникают в
корректной работе и почти наверняка означают атаку или баг.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import posixpath
import shutil
import uuid
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from leonit.core.config import get_settings
from leonit.core.errors import ConflictError, NotFoundError, ValidationFailedError

DEFAULT_CHUNK_SIZE = 64 * 1024


class StorageOffsetConflict(ConflictError):
    """Докачка пришла не с того смещения: клиент должен продолжить с ``current_size``.

    Это штатная ситуация при обрыве связи (ответ на предыдущий append потерялся),
    поэтому фактический размер отдаётся отдельным полем — клиент повторяет с него.
    """

    def __init__(self, key: str, *, expected_offset: int, current_size: int) -> None:
        super().__init__(
            f"offset mismatch for {key!r}: expected {expected_offset}, current size {current_size}"
        )
        self.key = key
        self.expected_offset = expected_offset
        self.current_size = current_size


class KeyLocks:
    """Блокировки по ключу в пределах процесса.

    Нужны там, где операция над одним объектом состоит из проверки и записи
    (докачка чанка, синтез с кэшированием): два конкурентных вызова с одним
    ключом иначе оба проходят проверку. Блокировка живёт, пока ключ кому-то
    нужен, и удаляется последним владельцем — иначе словарь рос бы на каждый
    когда-либо тронутый ключ, а ``asyncio.Lock`` привязывался к первому event
    loop и ломал тесты с новым loop.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._holders: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._locks)

    @contextlib.asynccontextmanager
    async def __call__(self, key: str) -> AsyncIterator[None]:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        self._holders[key] = self._holders.get(key, 0) + 1
        try:
            async with lock:
                yield
        finally:
            self._holders[key] -= 1
            if self._holders[key] == 0:
                del self._holders[key]
                del self._locks[key]


def normalize_key(key: str) -> str:
    """Привести ключ к каноническому виду и отвергнуть выход за корень."""
    if not isinstance(key, str) or not key.strip():
        raise ValidationFailedError("storage key must be a non-empty string")
    if "\x00" in key:
        raise ValidationFailedError("storage key must not contain NUL")
    candidate = key.replace("\\", "/")
    if candidate.startswith("/") or PurePosixPath(candidate).is_absolute() or ":" in candidate:
        raise ValidationFailedError("storage key must be relative")
    parts = [part for part in candidate.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValidationFailedError("storage key must not leave the storage root")
    return posixpath.join(*parts)


@runtime_checkable
class Storage(Protocol):
    async def put(self, key: str, data: bytes | AsyncIterator[bytes]) -> int:
        """Записать объект целиком (заменяя существующий); вернуть размер."""

    async def append(self, key: str, data: bytes, offset: int) -> int:
        """Дописать байты, если текущий размер равен ``offset``; вернуть новый размер."""

    async def size(self, key: str) -> int: ...

    async def exists(self, key: str) -> bool: ...

    def open_range(self, key: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]:
        """Прочитать байты ``[start, end)``; ``end=None`` — до конца файла."""
        ...

    async def delete(self, key: str) -> None:
        """Удалить объект; отсутствие объекта — не ошибка (идемпотентность)."""


class LocalStorage:
    """Файлы на локальном томе под ``root``.

    Блокирующий ввод-вывод уходит в поток, чтобы загрузка видеочанков не
    останавливала event loop. ``put`` пишет во временный файл и переименовывает
    атомарно: читатели никогда не увидят наполовину записанный объект.
    ``append`` держит блокировку по ключу: проверка смещения и дозапись должны
    быть одним шагом, иначе два повтора одного чанка оба пройдут проверку.
    """

    def __init__(self, root: Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
        self.root = _resolved(Path(root))
        self.chunk_size = chunk_size
        self._append_locks = KeyLocks()

    def path_for(self, key: str) -> Path:
        path = _resolved(self.root / normalize_key(key))
        # Двойная проверка после resolve(): защищает и от симлинков внутри тома.
        if self.root != path and self.root not in path.parents:
            raise ValidationFailedError("storage key must not leave the storage root")
        return path

    async def put(self, key: str, data: bytes | AsyncIterator[bytes]) -> int:
        path = self.path_for(key)
        # Имя временного файла уникально на вызов, а не на процесс: два
        # конкурентных put одного ключа (повтор запроса, гонка на кэше озвучки)
        # иначе пишут в один .part и второй os.replace падает на пустоте.
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        size = 0
        try:
            if isinstance(data, bytes | bytearray | memoryview):
                size = await asyncio.to_thread(_write_bytes, temp, bytes(data))
            else:
                with await asyncio.to_thread(open, temp, "wb") as handle:
                    async for chunk in data:
                        await asyncio.to_thread(handle.write, chunk)
                        size += len(chunk)
            await asyncio.to_thread(os.replace, temp, path)
        except BaseException:
            await asyncio.to_thread(_unlink_quietly, temp)
            raise
        return size

    async def append(self, key: str, data: bytes, offset: int) -> int:
        path = self.path_for(key)
        async with self._append_locks(normalize_key(key)):
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            return await asyncio.to_thread(_append_at, path, bytes(data), offset, key)

    async def size(self, key: str) -> int:
        path = self.path_for(key)
        try:
            return await asyncio.to_thread(lambda: path.stat().st_size)
        except FileNotFoundError as error:
            raise NotFoundError(f"object {key!r} not found") from error

    async def exists(self, key: str) -> bool:
        path = self.path_for(key)
        return await asyncio.to_thread(path.is_file)

    async def open_range(
        self, key: str, start: int = 0, end: int | None = None
    ) -> AsyncIterator[bytes]:
        path = self.path_for(key)
        if start < 0 or (end is not None and end < start):
            raise ValidationFailedError("invalid byte range")
        try:
            handle = await asyncio.to_thread(open, path, "rb")
        except FileNotFoundError as error:
            raise NotFoundError(f"object {key!r} not found") from error
        try:
            await asyncio.to_thread(handle.seek, start)
            remaining = None if end is None else end - start
            while remaining is None or remaining > 0:
                want = self.chunk_size if remaining is None else min(self.chunk_size, remaining)
                chunk = await asyncio.to_thread(handle.read, want)
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def delete(self, key: str) -> None:
        path = self.path_for(key)
        await asyncio.to_thread(_unlink_quietly, path)

    async def delete_prefix(self, prefix: str) -> None:
        """Удалить каталог целиком (данные кандидата по истечении срока хранения)."""
        path = self.path_for(prefix)
        if path == self.root:
            raise ValidationFailedError("refusing to delete the storage root")
        await asyncio.to_thread(shutil.rmtree, path, True)


_WIN_EXTENDED_PREFIX = "\\\\?\\"
_WIN_EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"


def _resolved(path: Path) -> Path:
    """``resolve()`` с одинаковым видом пути независимо от того, существует ли он.

    На Windows ``realpath`` ещё не существующего пути, чей каталог в этот момент
    создаёт другой поток (``mkdir`` соседней загрузки), может вернуть путь с
    префиксом ``\\\\?\\``: префикс снимается только при совпадении кода ошибки
    «до» и «после». Сравнение с корнем тогда ложно срабатывало бы как выход за
    пределы тома, и клиент получал бы 422 на честный ключ.
    """
    resolved = path.resolve()
    text = str(resolved)
    if text.startswith(_WIN_EXTENDED_UNC_PREFIX):
        return Path("\\\\" + text[len(_WIN_EXTENDED_UNC_PREFIX) :])
    if text.startswith(_WIN_EXTENDED_PREFIX):
        return Path(text[len(_WIN_EXTENDED_PREFIX) :])
    return resolved


def _write_bytes(path: Path, data: bytes) -> int:
    with open(path, "wb") as handle:
        handle.write(data)
    return len(data)


def _append_at(path: Path, data: bytes, offset: int, key: str) -> int:
    # Первый чанк с ненулевым смещением — конфликт без побочных эффектов: файл
    # не создаём, чтобы неудачный повтор не оставлял пустой объект.
    if offset != 0 and not path.exists():
        raise StorageOffsetConflict(key, expected_offset=offset, current_size=0)
    with open(path, "ab") as handle:
        # Смещение сверяется по уже открытому дескриптору в режиме append, а не
        # по отдельному stat(): между ними никто не успеет дописать.
        handle.seek(0, os.SEEK_END)
        current = handle.tell()
        if current != offset:
            raise StorageOffsetConflict(key, expected_offset=offset, current_size=current)
        handle.write(data)
    return current + len(data)


def _unlink_quietly(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


@lru_cache
def get_storage() -> Storage:
    return LocalStorage(get_settings().MEDIA_ROOT)


def reset_storage() -> None:
    """Сбросить кэш (тесты меняют MEDIA_ROOT между прогонами)."""
    get_storage.cache_clear()
