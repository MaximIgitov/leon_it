"""Формат интервью у вакансии: живой диалог или кнопки записи.

Живой диалог становится форматом по умолчанию; у существующих вакансий он
тоже включается — формат влияет только на комнату кандидата, записи и оценка
не меняются.

Revision ID: c8e2f1a4b7d9
Revises: b7d1e4c9a2f0
Create Date: 2026-09-05 19:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e2f1a4b7d9"
down_revision: str | None = "b7d1e4c9a2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vacancies",
        sa.Column("interview_mode", sa.String(length=16), nullable=False, server_default="live"),
    )


def downgrade() -> None:
    op.drop_column("vacancies", "interview_mode")
