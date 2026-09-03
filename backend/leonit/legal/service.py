"""Юридические тексты кандидатского флоу.

Тексты лежат в пакете как Markdown с YAML-frontmatter (см. docs/legal/README.md):
так они попадают в образ бэкенда и версионируются вместе с кодом. Хеш считается
по файлу с плейсхолдерами — он не зависит от стенда, и именно он пишется в
журнал согласий.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from leonit.core.errors import NotFoundError

DOCUMENTS_DIR = Path(__file__).parent / "documents"
CONSENT_SLUGS: tuple[str, ...] = ("personal-data-consent", "privacy-policy", "newsletter-consent")
ALL_SLUGS: tuple[str, ...] = (*CONSENT_SLUGS, "processors")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


@dataclass(frozen=True, slots=True)
class LegalDocument:
    slug: str
    title: str
    version: str
    effective_date: str
    operator: str
    required: bool
    checkbox_label: str | None
    body: str
    hash: str

    @property
    def short_hash(self) -> str:
        return self.hash[:12]


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER.match(raw)
    if not match:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key.strip()] = value
    return meta, raw[match.end() :]


@lru_cache
def load_document(slug: str) -> LegalDocument:
    if slug not in ALL_SLUGS:
        raise NotFoundError("Документ не найден")
    path = DOCUMENTS_DIR / f"{slug}.md"
    if not path.exists():
        raise NotFoundError("Документ не найден")
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    meta, body = _parse_frontmatter(raw)
    return LegalDocument(
        slug=slug,
        title=meta.get("title", slug),
        version=meta.get("version", "unknown"),
        effective_date=meta.get("effective_date", ""),
        operator=meta.get("operator", ""),
        required=meta.get("required", "false").lower() == "true",
        checkbox_label=meta.get("checkbox_label") or None,
        body=body.strip("\n"),
        hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def all_documents() -> list[LegalDocument]:
    return [load_document(slug) for slug in ALL_SLUGS]


def consent_documents() -> list[LegalDocument]:
    return [load_document(slug) for slug in CONSENT_SLUGS]


def render(
    document: LegalDocument, *, site_url: str, support_email: str, retention_days: int
) -> str:
    """Подставить плейсхолдеры стенда; хеш при этом не меняется."""
    return (
        document.body.replace("{{SITE_URL}}", site_url)
        .replace("{{SUPPORT_EMAIL}}", support_email)
        .replace("{{RETENTION_DAYS}}", str(retention_days))
    )
