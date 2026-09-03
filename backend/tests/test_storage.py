from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from leonit.core.config import get_settings
from leonit.core.errors import ConflictError, NotFoundError, ValidationFailedError
from leonit.core.storage import (
    LocalStorage,
    StorageOffsetConflict,
    get_storage,
    normalize_key,
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "media", chunk_size=4)


async def _collect(chunks: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in chunks])


async def test_put_size_exists_and_range(storage: LocalStorage) -> None:
    assert not await storage.exists("a/b/video.webm")
    assert await storage.put("a/b/video.webm", b"0123456789") == 10
    assert await storage.exists("a/b/video.webm")
    assert await storage.size("a/b/video.webm") == 10
    assert await _collect(storage.open_range("a/b/video.webm")) == b"0123456789"
    assert await _collect(storage.open_range("a/b/video.webm", 2, 7)) == b"23456"
    assert await _collect(storage.open_range("a/b/video.webm", 8)) == b"89"
    assert await _collect(storage.open_range("a/b/video.webm", 10)) == b""


async def test_put_from_async_iterator_and_overwrite(storage: LocalStorage) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"abc"
        yield b"def"

    assert await storage.put("x.bin", chunks()) == 6
    assert await _collect(storage.open_range("x.bin")) == b"abcdef"
    await storage.put("x.bin", b"z")
    assert await storage.size("x.bin") == 1
    assert not list((storage.root).glob("*.part"))


async def test_append_is_sequential_and_reports_offset_conflict(storage: LocalStorage) -> None:
    assert await storage.append("up/chunks.webm", b"aaa", 0) == 3
    assert await storage.append("up/chunks.webm", b"bb", 3) == 5
    with pytest.raises(StorageOffsetConflict) as info:
        await storage.append("up/chunks.webm", b"bb", 3)  # повтор потерянного ответа
    assert info.value.current_size == 5 and info.value.expected_offset == 3
    assert isinstance(info.value, ConflictError)
    assert await _collect(storage.open_range("up/chunks.webm")) == b"aaabb"
    with pytest.raises(StorageOffsetConflict) as gap:
        await storage.append("up/other.webm", b"x", 1)
    assert gap.value.current_size == 0


async def test_delete_is_idempotent_and_missing_size_raises(storage: LocalStorage) -> None:
    await storage.put("d.txt", b"1")
    await storage.delete("d.txt")
    await storage.delete("d.txt")
    assert not await storage.exists("d.txt")
    with pytest.raises(NotFoundError):
        await storage.size("d.txt")
    with pytest.raises(NotFoundError):
        await _collect(storage.open_range("d.txt"))


@pytest.mark.parametrize(
    "key",
    [
        "../etc/passwd",
        "/etc/passwd",
        "a/../../b",
        "C:/windows",
        "..",
        "",
        "a/\x00b",
        "\\\\server\\share",
    ],
)
def test_path_traversal_is_rejected(storage: LocalStorage, key: str) -> None:
    with pytest.raises(ValidationFailedError):
        storage.path_for(key)


def test_keys_are_normalized(storage: LocalStorage) -> None:
    assert normalize_key("a//b/./c.webm") == "a/b/c.webm"
    assert normalize_key("a\\b\\c.webm") == "a/b/c.webm"
    assert storage.path_for("a/b/c.webm") == (storage.root / "a" / "b" / "c.webm")


def test_get_storage_uses_media_root_from_settings() -> None:
    storage = get_storage()
    assert isinstance(storage, LocalStorage)
    assert storage.root == get_settings().MEDIA_ROOT.resolve()
    assert get_storage() is storage
