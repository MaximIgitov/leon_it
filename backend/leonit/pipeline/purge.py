"""Ручной запуск чистки медиа по сроку хранения.

Обычно чистку ставит воркер (ежедневно, см. ``leonit.pipeline.jobs``); этот
модуль нужен для проверки на стенде и для запуска мимо очереди:
``python -m leonit.pipeline.purge [--dry-run]``.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from leonit.core.db import dispose_engine, get_session_maker
from leonit.core.logging import setup_logging
from leonit.models import load_all_models
from leonit.pipeline.service import purge_expired_media


async def _run(*, dry_run: bool) -> dict[str, int]:
    try:
        async with get_session_maker()() as session:
            return await purge_expired_media(session, dry_run=dry_run)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LeonIT: чистка медиа по сроку хранения")
    parser.add_argument(
        "--dry-run", action="store_true", help="только посчитать, ничего не удалять"
    )
    args = parser.parse_args(argv)
    setup_logging()
    load_all_models()
    stats = asyncio.run(_run(dry_run=args.dry_run))
    print(json.dumps({**stats, "dry_run": args.dry_run}, ensure_ascii=False))


if __name__ == "__main__":
    main()
