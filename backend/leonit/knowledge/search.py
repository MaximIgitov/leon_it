"""Лексический поиск по фрагментам: BM25 с лёгким стеммингом для русского.

Без эмбеддингов намеренно: база знаний организации — десятки документов, а
запросы ассистента конкретные («ДМС», «стек бэкенда», «этапы найма»). BM25 на
таких объёмах даёт точные попадания, работает без сети и ключей и одинаково
на SQLite и PostgreSQL. Функции чистые — их гоняют тесты на граничных случаях.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+(?:[-+.][a-zа-яё0-9]+)*")
# Короткие служебные слова, которые совпадают в любом тексте.
_STOPWORDS_TEXT = (
    "и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только "
    "её мне было вот от меня ещё нет о из ему теперь когда даже ну вдруг ли если уже или ни "
    "быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут "
    "где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под "
    "будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем "
    "чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть "
    "после над больше тот через эти нас про всего них какая много разве три эту моя впрочем "
    "хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю "
    "между это который которые которая также либо the a an of to in on for and or is are was "
    "were be with by as at from that this it its our your we you they наш наша наше ваш "
)
_STOPWORDS = frozenset(_STOPWORDS_TEXT.split())
_RU_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ого",
    "его",
    "ому",
    "ему",
    "ыми",
    "ими",
    "ует",
    "ать",
    "ять",
    "ить",
    "еть",
    "ах",
    "ях",
    "ов",
    "ев",
    "ей",
    "ой",
    "ый",
    "ий",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ом",
    "ем",
    "ую",
    "юю",
    "ть",
    "ла",
    "ло",
    "ли",
    "ет",
    "ют",
    "ит",
    "ат",
    "ят",
    "ся",
    "а",
    "я",
    "ы",
    "и",
    "о",
    "е",
    "у",
    "ю",
    "ь",
)
_EN_SUFFIXES = ("ing", "ed", "es", "s")

BM25_K1 = 1.5
BM25_B = 0.75


def stem(token: str) -> str:
    """Отрезать одно окончание, если корень остаётся не короче трёх букв."""
    token = token.replace("ё", "е")
    if len(token) <= 4:
        return token
    suffixes = _RU_SUFFIXES if re.search(r"[а-я]", token) else _EN_SUFFIXES
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower().replace("ё", "е"))
    return [stem(token) for token in tokens if token not in _STOPWORDS]


@dataclass(frozen=True, slots=True)
class Passage:
    """Фрагмент, участвующий в поиске: ключ вызывающего и текст с заголовком документа."""

    key: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class Hit:
    key: str
    score: float


def rank(query: str, passages: Iterable[Passage], *, limit: int = 5) -> list[Hit]:
    """BM25 по фрагментам; заголовок документа входит в текст фрагмента с малым весом."""
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    items = list(passages)
    if not items:
        return []
    documents: list[Counter[str]] = []
    lengths: list[int] = []
    for passage in items:
        tokens = tokenize(passage.text)
        # Заголовок подсказывает тему («Найм» найдёт документ про этапы отбора).
        tokens.extend(tokenize(passage.title))
        documents.append(Counter(tokens))
        lengths.append(len(tokens))
    total = len(documents)
    average_length = sum(lengths) / total if total else 0.0
    unique_query = list(dict.fromkeys(query_tokens))
    frequencies = {
        token: sum(1 for document in documents if token in document) for token in unique_query
    }
    hits: list[Hit] = []
    for index, document in enumerate(documents):
        score = 0.0
        for token in unique_query:
            tf = document.get(token, 0)
            if not tf:
                continue
            df = frequencies[token]
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            norm = BM25_K1 * (1 - BM25_B + BM25_B * lengths[index] / (average_length or 1))
            score += idf * (tf * (BM25_K1 + 1)) / (tf + norm)
        if score > 0:
            hits.append(Hit(items[index].key, round(score, 4)))
    hits.sort(key=lambda hit: (-hit.score, hit.key))
    return hits[:limit]
