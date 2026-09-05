from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from leonit.accounts.deps import CurrentActor
from leonit.core.deps import DbSession
from leonit.knowledge.schemas import (
    KnowledgeDocumentDetail,
    KnowledgeDocumentOut,
    KnowledgeFormatsOut,
    KnowledgeSearchOut,
    KnowledgeTextCreate,
    KnowledgeUpdate,
    normalize_tags,
)
from leonit.knowledge.service import KnowledgeService, document_detail, document_out

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeDocumentOut])
async def list_documents(actor: CurrentActor, session: DbSession) -> list[KnowledgeDocumentOut]:
    return [document_out(item) for item in await KnowledgeService(session).list(actor)]


@router.get("/formats", response_model=KnowledgeFormatsOut)
async def formats() -> KnowledgeFormatsOut:
    return KnowledgeFormatsOut()


@router.get("/search", response_model=KnowledgeSearchOut)
async def search_documents(
    actor: CurrentActor,
    session: DbSession,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> KnowledgeSearchOut:
    service = KnowledgeService(session)
    hits = await service.search(actor, q, limit=limit)
    return KnowledgeSearchOut(query=q, hits=hits, documents_total=await service.count(actor))


@router.post("", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED)
async def create_text_document(
    payload: KnowledgeTextCreate, actor: CurrentActor, session: DbSession
) -> KnowledgeDocumentOut:
    return document_out(await KnowledgeService(session).create_text(actor, payload))


@router.post("/upload", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    actor: CurrentActor,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
    tags: Annotated[str | None, Form(max_length=1000)] = None,
) -> KnowledgeDocumentOut:
    data = await file.read()
    document = await KnowledgeService(session).create_file(
        actor,
        filename=file.filename,
        content_type=file.content_type,
        data=data,
        title=title,
        tags=normalize_tags([tag for tag in (tags or "").split(",") if tag.strip()]),
    )
    return document_out(document)


@router.get("/{document_id}", response_model=KnowledgeDocumentDetail)
async def get_document(
    document_id: UUID, actor: CurrentActor, session: DbSession
) -> KnowledgeDocumentDetail:
    return document_detail(await KnowledgeService(session).get(actor, document_id))


@router.patch("/{document_id}", response_model=KnowledgeDocumentDetail)
async def update_document(
    document_id: UUID, payload: KnowledgeUpdate, actor: CurrentActor, session: DbSession
) -> KnowledgeDocumentDetail:
    return document_detail(await KnowledgeService(session).update(actor, document_id, payload))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, actor: CurrentActor, session: DbSession) -> Response:
    await KnowledgeService(session).delete(actor, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
