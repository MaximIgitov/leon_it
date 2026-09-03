from __future__ import annotations

import hashlib

from httpx import AsyncClient

from leonit.legal.service import (
    ALL_SLUGS,
    DOCUMENTS_DIR,
    consent_documents,
    load_document,
    render,
)


def test_documents_have_frontmatter_and_stable_hash() -> None:
    for slug in ALL_SLUGS:
        document = load_document(slug)
        assert document.title and document.version and document.effective_date
        raw = (DOCUMENTS_DIR / f"{slug}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert document.hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_consent_documents_flags() -> None:
    docs = {doc.slug: doc for doc in consent_documents()}
    assert docs["personal-data-consent"].required is True
    assert docs["privacy-policy"].required is True
    assert docs["newsletter-consent"].required is False
    assert docs["personal-data-consent"].checkbox_label


def test_render_substitutes_placeholders_without_changing_hash() -> None:
    document = load_document("privacy-policy")
    rendered = render(
        document,
        site_url="https://leonit.test",
        support_email="help@leonit.test",
        retention_days=90,
    )
    assert "{{SITE_URL}}" not in rendered
    assert "https://leonit.test" in rendered
    assert "{{RETENTION_DAYS}}" not in rendered
    assert load_document("privacy-policy").hash == document.hash


async def test_legal_api(client: AsyncClient) -> None:
    listing = await client.get("/api/legal")
    assert listing.status_code == 200
    assert [doc["slug"] for doc in listing.json()] == list(ALL_SLUGS)
    response = await client.get("/api/legal/personal-data-consent")
    assert response.status_code == 200
    body = response.json()
    assert body["operator"].startswith("ООО")
    assert "{{" not in body["markdown"]
    assert len(body["hash"]) == 64
    assert (await client.get("/api/legal/unknown")).status_code == 404
