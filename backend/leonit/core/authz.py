"""Единая точка проверки прав.

Роутеры, инструменты ассистента, публичный API и агрегаты дашборда обязаны
проверять доступ здесь, а не сравнивать роли на месте: так у нанимающего
менеджера один и тот же периметр во всех входах в систему.

Действия именуются как ``<область>.<глагол>``. Ресурс — id вакансии: для
владельца и рекрутера любой, для нанимающего менеджера — только из его
``vacancy_scope``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from leonit.core.errors import PermissionDeniedError

if TYPE_CHECKING:
    from leonit.accounts.models import Membership, MembershipRole, Organization, User


@dataclass(frozen=True)
class Actor:
    user: User
    membership: Membership
    organization: Organization
    # Публичный API: у токена нет роли — набор действий выводится из его областей
    # (``leonit.api_tokens.scopes``) и целиком подменяет матрицу роли. Так токен с
    # областью «только вакансии» не получает чтение кандидатов «в нагрузку», как
    # получил бы при маппинге областей на ближайшую роль.
    actions: frozenset[str] | None = None

    @property
    def role(self) -> MembershipRole:
        return self.membership.role

    @property
    def organization_id(self) -> UUID:
        return self.organization.id

    @property
    def is_api(self) -> bool:
        return self.actions is not None


# Что разрешено каждой роли. Владелец умеет всё, что рекрутер, плюс управление.
_RECRUITER_ACTIONS = frozenset(
    {
        "vacancy.read",
        "vacancy.write",
        "candidate.read",
        "candidate.write",
        "interview.read",
        "report.read",
        "report.decide",
        "report.share",
        "dashboard.read",
        "assistant.use",
        "integrations.read",
        # Синхронизация, импорт вакансий и настройка диалогов интеграций (HH).
        "integrations.operate",
        # База знаний компании: читают все роли, пополняют рекрутёр и владелец.
        "knowledge.read",
        "knowledge.write",
    }
)
_OWNER_ACTIONS = _RECRUITER_ACTIONS | frozenset(
    {
        "org.read",
        "org.write",
        "org.members",
        "org.invites",
        "org.audit",
        "integrations.manage",
        "api_tokens.manage",
        "models.manage",
        "data.delete",
    }
)
_HIRING_MANAGER_ACTIONS = frozenset(
    {
        "vacancy.read",
        "candidate.read",
        "interview.read",
        "report.read",
        "report.decide",
        "dashboard.read",
        "assistant.use",
        "knowledge.read",
    }
)

_ROLE_ACTIONS = {
    "owner": _OWNER_ACTIONS,
    "recruiter": _RECRUITER_ACTIONS,
    "hiring_manager": _HIRING_MANAGER_ACTIONS,
}


def can(actor: Actor, action: str, *, vacancy_id: UUID | str | None = None) -> bool:
    allowed = (
        actor.actions
        if actor.actions is not None
        else _ROLE_ACTIONS.get(actor.role.value, frozenset())
    )
    if action not in allowed:
        return False
    scope = actor.membership.vacancy_scope
    return not (vacancy_id is not None and scope is not None and str(vacancy_id) not in scope)


def authorize(actor: Actor, action: str, *, vacancy_id: UUID | str | None = None) -> None:
    if not can(actor, action, vacancy_id=vacancy_id):
        raise PermissionDeniedError("Недостаточно прав для этого действия")


def visible_vacancy_ids(actor: Actor) -> list[str] | None:
    """None — видны все вакансии организации; иначе — явный список."""
    if actor.membership.vacancy_scope is None:
        return None
    return list(actor.membership.vacancy_scope)
