from __future__ import annotations

import logging
import sys

from leonit.core.config import get_settings
from leonit.core.observability import RequestIdLogFilter


def setup_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdLogFilter())
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] [rid=%(request_id)s] %(message)s",
        handlers=[handler],
        force=True,
    )
    # uvicorn пишет свой access-лог без request-id; наш middleware уже покрывает это.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
