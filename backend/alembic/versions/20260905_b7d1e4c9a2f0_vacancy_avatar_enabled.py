"""ИИ-аватар интервьюера: флаг вакансии ``avatar_enabled``.

Аватар платный, поэтому включается отдельно для каждой вакансии; у всех
существующих вакансий он выключен.

Revision ID: b7d1e4c9a2f0
Revises: 9c4e2a7b1d03
Create Date: 2026-09-05 14:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d1e4c9a2f0"
down_revision: str | None = "9c4e2a7b1d03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vacancies",
        sa.Column("avatar_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("vacancies", "avatar_enabled")
