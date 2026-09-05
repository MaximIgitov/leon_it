from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from leonit.knowledge.parsing import MAX_FILE_BYTES, MAX_TEXT_CHARS, SUPPORTED_EXTENSIONS

PREVIEW_CHARS = 280


def normalize_tags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for tag in tags:
        cleaned = tag.strip().lower()[:40]
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen[:20]


class KnowledgeTextCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return normalize_tags(value)


class KnowledgeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT_CHARS)
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_tags(value)


class KnowledgeDocumentOut(BaseModel):
    id: str
    title: str
    kind: str
    source_name: str | None
    content_type: str
    size_bytes: int
    tags: list[str]
    chunk_count: int
    preview: str
    created_by_label: str
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentDetail(KnowledgeDocumentOut):
    text: str


class KnowledgeHit(BaseModel):
    document_id: str
    title: str
    position: int
    text: str
    score: float


class KnowledgeSearchOut(BaseModel):
    query: str
    hits: list[KnowledgeHit]
    documents_total: int


class KnowledgeFormatsOut(BaseModel):
    extensions: list[str] = Field(default_factory=lambda: list(SUPPORTED_EXTENSIONS))
    max_file_mb: int = MAX_FILE_BYTES // (1024 * 1024)
    max_text_chars: int = MAX_TEXT_CHARS
