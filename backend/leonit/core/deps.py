"""Общие зависимости FastAPI."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.core.config import Settings, get_settings
from leonit.core.db import get_session

DbSession = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
