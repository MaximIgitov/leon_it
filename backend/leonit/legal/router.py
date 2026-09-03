from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from leonit.core.deps import SettingsDep
from leonit.legal.service import LegalDocument, all_documents, load_document, render

router = APIRouter(prefix="/legal", tags=["legal"])


class LegalDocumentSummary(BaseModel):
    slug: str
    title: str
    version: str
    effective_date: str
    operator: str
    required: bool
    checkbox_label: str | None
    hash: str


class LegalDocumentOut(LegalDocumentSummary):
    markdown: str


def summary(document: LegalDocument) -> LegalDocumentSummary:
    return LegalDocumentSummary(
        slug=document.slug,
        title=document.title,
        version=document.version,
        effective_date=document.effective_date,
        operator=document.operator,
        required=document.required,
        checkbox_label=document.checkbox_label,
        hash=document.hash,
    )


@router.get("", response_model=list[LegalDocumentSummary])
async def list_documents() -> list[LegalDocumentSummary]:
    return [summary(document) for document in all_documents()]


@router.get("/{slug}", response_model=LegalDocumentOut)
async def get_document(slug: str, settings: SettingsDep) -> LegalDocumentOut:
    document = load_document(slug)
    return LegalDocumentOut(
        **summary(document).model_dump(),
        markdown=render(
            document,
            site_url=settings.PUBLIC_URL,
            support_email=settings.SUPPORT_EMAIL,
            retention_days=settings.DEFAULT_RETENTION_DAYS,
        ),
    )
