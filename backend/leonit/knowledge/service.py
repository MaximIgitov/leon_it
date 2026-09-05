"""Документы базы знаний: загрузка, нарезка, поиск и контекст для промптов."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leonit.core.authz import Actor, authorize
from leonit.core.errors import NotFoundError
from leonit.core.logging import get_logger
from leonit.core.storage import Storage, get_storage
from leonit.core.time import aware
from leonit.knowledge.models import KnowledgeChunk, KnowledgeDocument
from leonit.knowledge.parsing import (
    ParsedDocument,
    chunk_text,
    clean_text,
    extract_text,
)
from leonit.knowledge.schemas import (
    PREVIEW_CHARS,
    KnowledgeDocumentDetail,
    KnowledgeDocumentOut,
    KnowledgeHit,
    KnowledgeTextCreate,
    KnowledgeUpdate,
)
from leonit.knowledge.search import Passage, rank

log = get_logger(__name__)

# Сколько фрагментов организации участвует в одном поиске: страхует от
# случайной загрузки гигантского архива, при обычных объёмах не срабатывает.
SEARCH_CHUNK_LIMIT = 4000
CONTEXT_CHARS = 3500
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9А-Яа-яЁё._-]+")


def document_out(document: KnowledgeDocument) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut(
        id=str(document.id),
        title=document.title,
        kind=document.kind,
        source_name=document.source_name,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        tags=list(document.tags or []),
        chunk_count=document.chunk_count,
        preview=document.text[:PREVIEW_CHARS],
        created_by_label=document.created_by_label,
        created_at=aware(document.created_at),  # type: ignore[arg-type]
        updated_at=aware(document.updated_at),  # type: ignore[arg-type]
    )


def document_detail(document: KnowledgeDocument) -> KnowledgeDocumentDetail:
    return KnowledgeDocumentDetail(**document_out(document).model_dump(), text=document.text)


def safe_file_name(name: str | None) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", (name or "document").strip()).strip("._") or "document"
    return cleaned[:100]


class KnowledgeService:
    def __init__(self, session: AsyncSession, *, storage: Storage | None = None) -> None:
        self.session = session
        self.storage = storage or get_storage()

    # ------------------------------------------------------------ чтение

    async def list(self, actor: Actor) -> list[KnowledgeDocument]:
        authorize(actor, "knowledge.read")
        rows = await self.session.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.organization_id == actor.organization_id)
            .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.title)
        )
        return list(rows)

    async def count(self, actor: Actor) -> int:
        authorize(actor, "knowledge.read")
        total = await self.session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.organization_id == actor.organization_id)
        )
        return int(total or 0)

    async def get(
        self, actor: Actor, document_id: UUID, *, action: str = "knowledge.read"
    ) -> KnowledgeDocument:
        authorize(actor, action)
        # Фрагменты нужны для перенарезки и каскадного удаления; ленивая загрузка в
        # async-сессии невозможна, поэтому берём их сразу.
        document = await self.session.scalar(
            select(KnowledgeDocument)
            .options(selectinload(KnowledgeDocument.chunks))
            .where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.organization_id == actor.organization_id,
            )
        )
        if document is None:
            raise NotFoundError("Документ не найден")
        return document

    # ------------------------------------------------------------ запись

    async def create_text(self, actor: Actor, payload: KnowledgeTextCreate) -> KnowledgeDocument:
        authorize(actor, "knowledge.write")
        text = clean_text(payload.text)
        document = KnowledgeDocument(
            organization_id=actor.organization_id,
            title=payload.title.strip(),
            kind="text",
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            text=text,
            tags=payload.tags,
            created_by_user_id=actor.user.id,
            created_by_label=actor.user.full_name or actor.user.email,
        )
        self.session.add(document)
        await self._rechunk(document)
        await self.session.commit()
        log.info("knowledge.created %s", document.as_log())
        return await self.get(actor, document.id)

    async def create_file(
        self,
        actor: Actor,
        *,
        filename: str | None,
        content_type: str | None,
        data: bytes,
        title: str | None = None,
        tags: list[str] | None = None,
    ) -> KnowledgeDocument:
        authorize(actor, "knowledge.write")
        parsed: ParsedDocument = extract_text(filename, content_type, data)
        document = KnowledgeDocument(
            organization_id=actor.organization_id,
            title=(title or "").strip() or _title_from_name(filename),
            kind="file",
            source_name=(filename or "")[:255] or None,
            content_type=parsed.content_type,
            size_bytes=len(data),
            text=parsed.text,
            tags=tags or [],
            created_by_user_id=actor.user.id,
            created_by_label=actor.user.full_name or actor.user.email,
        )
        await self._rechunk(document)
        self.session.add(document)
        await self.session.flush()
        key = f"knowledge/{actor.organization_id}/{document.id}/{safe_file_name(filename)}"
        await self.storage.put(key, data)
        document.storage_key = key
        await self.session.commit()
        log.info("knowledge.uploaded %s", document.as_log())
        return await self.get(actor, document.id)

    async def update(
        self, actor: Actor, document_id: UUID, payload: KnowledgeUpdate
    ) -> KnowledgeDocument:
        document = await self.get(actor, document_id, action="knowledge.write")
        if payload.title is not None:
            document.title = payload.title.strip()
        if payload.tags is not None:
            document.tags = payload.tags
        if payload.text is not None:
            document.text = clean_text(payload.text)
            document.size_bytes = len(document.text.encode("utf-8"))
            await self._rechunk(document)
        await self.session.commit()
        return await self.get(actor, document.id)

    async def delete(self, actor: Actor, document_id: UUID) -> None:
        document = await self.get(actor, document_id, action="knowledge.write")
        key = document.storage_key
        await self.session.delete(document)
        await self.session.commit()
        if key:
            try:
                await self.storage.delete(key)
            except Exception as error:
                log.warning("knowledge.file_delete_failed key=%s error=%s", key, error)
        log.info("knowledge.deleted %s", document.as_log())

    # ------------------------------------------------------------- поиск

    async def search(self, actor: Actor, query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        authorize(actor, "knowledge.read")
        query = query.strip()
        if not query:
            return []
        rows = await self.session.execute(
            select(KnowledgeChunk, KnowledgeDocument.title)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.organization_id == actor.organization_id)
            .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeChunk.position)
            .limit(SEARCH_CHUNK_LIMIT)
        )
        chunks = rows.all()
        by_key = {str(chunk.id): (chunk, title) for chunk, title in chunks}
        hits = rank(
            query,
            (Passage(str(chunk.id), title, chunk.text) for chunk, title in chunks),
            limit=max(1, min(limit, 20)),
        )
        result: list[KnowledgeHit] = []
        for hit in hits:
            chunk, title = by_key[hit.key]
            result.append(
                KnowledgeHit(
                    document_id=str(chunk.document_id),
                    title=title,
                    position=chunk.position,
                    text=chunk.text,
                    score=hit.score,
                )
            )
        return result

    async def context_for(
        self, actor: Actor, query: str, *, limit: int = 6, max_chars: int = CONTEXT_CHARS
    ) -> str:
        """Фрагменты базы знаний для промпта: «Документ» → текст, до ``max_chars``.

        Пустая строка, если базы нет или ничего не нашлось: вызывающий тогда не
        добавляет секцию вовсе, чтобы не приучать модель к пустым блокам.
        """
        hits = await self.search(actor, query, limit=limit)
        parts: list[str] = []
        used = 0
        for hit in hits:
            piece = f"«{hit.title}»:\n{hit.text}"
            if used + len(piece) > max_chars:
                piece = piece[: max(0, max_chars - used)]
            if not piece.strip():
                break
            parts.append(piece)
            used += len(piece) + 2
            if used >= max_chars:
                break
        return "\n\n".join(parts)

    # ---------------------------------------------------------- внутреннее

    async def _rechunk(self, document: KnowledgeDocument) -> None:
        pieces = chunk_text(document.text)
        if document.chunks:
            # Старые фрагменты удаляем отдельным flush: иначе новые вставятся
            # раньше удаления и упрутся в уникальность (document_id, position).
            document.chunks.clear()
            await self.session.flush()
        document.chunks = [
            KnowledgeChunk(organization_id=document.organization_id, position=position, text=piece)
            for position, piece in enumerate(pieces)
        ]
        document.chunk_count = len(pieces)


def _title_from_name(filename: str | None) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", (filename or "").strip()).replace("_", " ")
    return (stem or "Документ")[:255]
