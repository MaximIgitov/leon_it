"""Замена персональных данных плейсхолдерами перед отправкой в модель.

Модель оценивает ответы, а не личность: имя, e-mail и телефон кандидата ей не
нужны, зато они уходят стороннему провайдеру. Поэтому известные значения из
интервью (ФИО с формами склонения, e-mail, телефон) и всё, что похоже на
контакты или ссылку на hh.ru, заменяются плейсхолдерами. Словарь замен нужен,
чтобы при показе цитат восстановить исходный текст; в модель он не передаётся.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

PLACEHOLDER_NAME = "[КАНДИДАТ]"
PLACEHOLDER_EMAIL = "[EMAIL]"
PLACEHOLDER_PHONE = "[ТЕЛЕФОН]"
PLACEHOLDER_LINK = "[ССЫЛКА]"

# Части ФИО короче трёх символов (инициалы, «Ли») слишком часто встречаются
# в обычных словах — их не трогаем.
MIN_NAME_PART = 3

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Российские номера: +7 / 8, затем десять цифр с любыми разделителями.
_PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")
# Международные: «+» и 10–14 цифр с разделителями.
_INTL_PHONE_RE = re.compile(r"(?<![\w+])\+\d[\d\s\-()]{8,16}\d(?!\d)")
# Путь не может заканчиваться знаком препинания: точка или запятая после ссылки
# принадлежат предложению, а не адресу.
_HH_LINK_RE = re.compile(
    r"(?:https?://)?(?:[a-z0-9\-]+\.)*hh\.ru(?:/(?:[^\s<>\"']*[^\s<>\"'.,;:!?)])?)?",
    re.IGNORECASE,
)
_CYRILLIC_ENDING = "[а-яё]{0,2}"


def _name_fragment(part: str) -> str:
    """Фрагмент регулярки для одной части ФИО с учётом склонения.

    Русские имена склоняются: «Иван» → «Ивана», «Мария» → «Марии». Отрезаем
    окончание у длинных частей и разрешаем до двух букв после основы.
    """
    stem = part
    if len(part) >= 4 and part[-1].lower() in "аяй":
        stem = part[:-1]
    if len(stem) < MIN_NAME_PART:
        stem = part
    return re.escape(stem) + _CYRILLIC_ENDING


def _name_patterns(full_name: str | None) -> list[re.Pattern[str]]:
    if not full_name:
        return []
    parts = [p for p in re.split(r"[\s\-]+", full_name.strip()) if len(p) >= MIN_NAME_PART]
    patterns: list[re.Pattern[str]] = []
    if len(parts) > 1:
        # Полное ФИО целиком — раньше отдельных частей, чтобы заменить одним плейсхолдером.
        whole = r"\s+".join(_name_fragment(p) for p in parts)
        patterns.append(re.compile(rf"(?<!\w){whole}(?!\w)", re.IGNORECASE))
    patterns.extend(
        re.compile(rf"(?<!\w){_name_fragment(part)}(?!\w)", re.IGNORECASE) for part in parts
    )
    return patterns


def _phone_pattern(phone: str | None) -> re.Pattern[str] | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 7:
        return None
    # Ведущие 7/8 у российских номеров взаимозаменяемы: ищем по последним десяти цифрам.
    tail = digits[-10:] if len(digits) >= 10 else digits
    body = r"[\s\-()]*".join(re.escape(d) for d in tail)
    return re.compile(rf"(?<!\d)(?:\+?7|8)?[\s\-(]*{body}(?!\d)")


class Redactor:
    """Замена ПДн в нескольких текстах одного интервью с общим словарём замен."""

    def __init__(
        self,
        *,
        full_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        extra_names: Iterable[str] = (),
    ) -> None:
        self._rules: list[tuple[re.Pattern[str], str]] = []
        for name in (full_name, *extra_names):
            self._rules.extend((pattern, PLACEHOLDER_NAME) for pattern in _name_patterns(name))
        if email and email.strip():
            self._rules.append(
                (re.compile(re.escape(email.strip()), re.IGNORECASE), PLACEHOLDER_EMAIL)
            )
        known_phone = _phone_pattern(phone)
        if known_phone is not None:
            self._rules.append((known_phone, PLACEHOLDER_PHONE))
        # Общие правила — после известных значений, чтобы словарь замен помнил
        # именно то, что встретилось в тексте.
        self._rules.extend(
            [
                (_EMAIL_RE, PLACEHOLDER_EMAIL),
                (_PHONE_RE, PLACEHOLDER_PHONE),
                (_INTL_PHONE_RE, PLACEHOLDER_PHONE),
                (_HH_LINK_RE, PLACEHOLDER_LINK),
            ]
        )
        self.replacements: dict[str, str] = {}

    def redact(self, text: str | None) -> str:
        if not text:
            return text or ""
        result = text
        for pattern, placeholder in self._rules:

            def _sub(match: re.Match[str], placeholder: str = placeholder) -> str:
                original = match.group(0)
                if original != placeholder:
                    self.replacements[original] = placeholder
                return placeholder

            result = pattern.sub(_sub, result)
        return result


def redact_text(
    text: str,
    *,
    full_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Одноразовая замена: вернуть текст и словарь «исходное → плейсхолдер»."""
    redactor = Redactor(full_name=full_name, email=email, phone=phone)
    return redactor.redact(text), dict(redactor.replacements)
