from __future__ import annotations

import asyncio
import os
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


async def test_concurrent_put_same_key_keeps_one_whole_variant(storage: LocalStorage) -> None:
    async def chunks(byte: bytes) -> AsyncIterator[bytes]:
        for _ in range(5):
            yield byte * 3
            await asyncio.sleep(0)  # чередуемся с конкурентом посреди записи

    sizes = await asyncio.gather(
        storage.put("race.bin", chunks(b"a")), storage.put("race.bin", chunks(b"b"))
    )
    assert sizes == [15, 15]
    # Победил один из вариантов целиком — не смесь и не пустой файл.
    assert await _collect(storage.open_range("race.bin")) in (b"a" * 15, b"b" * 15)
    assert not list(storage.root.glob("*.part"))


async def test_concurrent_append_same_offset_admits_exactly_one(storage: LocalStorage) -> None:
    # Повтор потерянного ответа пришёл одновременно с оригиналом: дописать чанк
    # должен ровно один, остальные получают конфликт с фактическим размером.
    results = await asyncio.gather(
        *(storage.append("race/chunks.webm", b"abc", 0) for _ in range(8)),
        return_exceptions=True,
    )
    successes = [result for result in results if isinstance(result, int)]
    conflicts = [result for result in results if isinstance(result, StorageOffsetConflict)]
    assert successes == [3], results
    assert len(conflicts) == 7 and all(c.current_size == 3 for c in conflicts), results
    assert await _collect(storage.open_range("race/chunks.webm")) == b"abc"
    assert len(storage._append_locks) == 0  # блокировки не копятся по ключам


async def test_append_conflict_on_missing_file_leaves_no_empty_object(
    storage: LocalStorage,
) -> None:
    with pytest.raises(StorageOffsetConflict):
        await storage.append("up/late.webm", b"x", 5)
    assert not await storage.exists("up/late.webm")


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


@pytest.mark.skipif(os.name != "nt", reason="префикс \\\\?\\ бывает только у путей Windows")
def test_path_for_tolerates_extended_length_prefix(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    # В гонке с mkdir соседней загрузки realpath оставляет у ещё не созданного
    # файла префикс \\?\ — честный ключ не должен считаться выходом за корень.
    original = Path.resolve

    def prefixed(self: Path, strict: bool = False) -> Path:
        resolved = original(self, strict=strict)
        return Path("\\\\?\\" + str(resolved)) if self.name == "chunks.webm" else resolved

    monkeypatch.setattr(Path, "resolve", prefixed)
    assert storage.path_for("race/chunks.webm") == storage.root / "race" / "chunks.webm"


def test_get_storage_uses_media_root_from_settings() -> None:
    storage = get_storage()
    assert isinstance(storage, LocalStorage)
    assert storage.root == get_settings().MEDIA_ROOT.resolve()
    assert get_storage() is storage
