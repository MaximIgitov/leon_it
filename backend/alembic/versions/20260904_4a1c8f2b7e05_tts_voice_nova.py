"""Дефолтный голос озвучки: alloy -> nova.

Голос в интерфейсе не выбирается, поэтому `alloy` во всех строках — это старый
дефолт, а не осознанный выбор рекрутёра. Переводим такие вакансии на новый
дефолт; вакансии с любым другим голосом не трогаем.

Revision ID: 4a1c8f2b7e05
Revises: 121fcfc40621
Create Date: 2026-09-04 10:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a1c8f2b7e05"
down_revision: str | None = "121fcfc40621"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_VOICE = "alloy"
NEW_VOICE = "nova"


def _move_voice(source: str, target: str) -> None:
    op.execute(
        sa.text("UPDATE vacancies SET voice = :target WHERE voice = :source").bindparams(
            target=target, source=source
        )
    )


def upgrade() -> None:
    _move_voice(OLD_VOICE, NEW_VOICE)


def downgrade() -> None:
    _move_voice(NEW_VOICE, OLD_VOICE)
