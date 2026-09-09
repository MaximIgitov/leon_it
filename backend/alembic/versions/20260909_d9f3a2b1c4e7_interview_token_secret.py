"""Зашифрованный токен ссылки интервью.

Напоминание кандидату повторяет исходную ссылку вместо выпуска новой: раньше
после напоминания ссылка из чата hh и из первого письма переставала работать.

Revision ID: d9f3a2b1c4e7
Revises: c8e2f1a4b7d9
Create Date: 2026-09-09 20:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9f3a2b1c4e7"
down_revision: str | None = "c8e2f1a4b7d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("interviews", sa.Column("token_secret", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("interviews", "token_secret")
