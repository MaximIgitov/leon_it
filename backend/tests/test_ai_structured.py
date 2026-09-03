from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import BaseModel, Field

from leonit.ai.config import RoleConfig
from leonit.ai.providers.base import (
    LLMDelta,
    LLMProvider,
    LLMResponse,
    Message,
    ProviderResponseError,
)
from leonit.ai.providers.fake import FakeLLM
from leonit.ai.structured import complete_structured, extract_json


class Score(BaseModel):
    competency: str
    score: int = Field(ge=1, le=5)
    quotes: list[str]


class ScriptedLLM(LLMProvider):
    """Отдаёт заранее заданные ответы и запоминает, что ему присылали."""

    role = "evaluator"
    model = "scripted"

    def __init__(self, *contents: str) -> None:
        self.contents = list(contents)
        self.calls: list[list[Message]] = []

    async def chat(
        self, messages, *, tools=None, response_format=None, temperature=None, max_tokens=None
    ):
        self.calls.append(messages)
        assert response_format["type"] == "json_schema"
        return LLMResponse(content=self.contents.pop(0), raw={"provider": "scripted"})

    async def stream_chat(
        self, messages, *, tools=None, temperature=None, max_tokens=None
    ) -> AsyncIterator[LLMDelta]:
        raise NotImplementedError
        yield  # pragma: no cover


async def test_valid_response_is_parsed_and_schema_goes_into_system_prompt() -> None:
    llm = ScriptedLLM('{"competency": "Python", "score": 4, "quotes": ["asyncio"]}')
    result, raw = await complete_structured(
        llm,
        [{"role": "system", "content": "Ты оценщик"}, {"role": "user", "content": "..."}],
        Score,
    )
    assert result == Score(competency="Python", score=4, quotes=["asyncio"])
    assert raw["structured_attempts"] == 1 and raw["provider"] == "scripted"
    system = llm.calls[0][0]
    assert system["role"] == "system"
    assert system["content"].startswith("Ты оценщик")
    assert '"competency"' in system["content"]
    assert len(llm.calls[0]) == 2


async def test_invalid_response_triggers_one_repair_round() -> None:
    llm = ScriptedLLM(
        '```json\n{"competency": "Python", "score": 9, "quotes": "asyncio"}\n```',
        '{"competency": "Python", "score": 5, "quotes": ["asyncio"]}',
    )
    result, raw = await complete_structured(llm, [{"role": "user", "content": "оцени"}], Score)
    assert result.score == 5
    assert raw["structured_attempts"] == 2
    repair = llm.calls[1]
    assert repair[-2]["role"] == "assistant" and '"score": 9' in repair[-2]["content"]
    assert repair[-1]["role"] == "user"
    assert "score" in repair[-1]["content"] and "quotes" in repair[-1]["content"]


async def test_gives_up_after_repairs() -> None:
    llm = ScriptedLLM("not json at all", "{}")
    with pytest.raises(ProviderResponseError, match="after 2 attempt"):
        await complete_structured(llm, [{"role": "user", "content": "оцени"}], Score)


async def test_no_repairs_when_disabled() -> None:
    llm = ScriptedLLM("{}", '{"competency": "x", "score": 1, "quotes": []}')
    with pytest.raises(ProviderResponseError, match="after 1 attempt"):
        await complete_structured(llm, [{"role": "user", "content": "оцени"}], Score, max_repairs=0)
    assert len(llm.calls) == 1


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('Вот ответ: {"a": {"b": 2}} — готово.', {"a": {"b": 2}}),
    ],
)
def test_extract_json_variants(content: str, expected: Any) -> None:
    assert extract_json(content) == expected


def test_extract_json_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        extract_json("nothing here")


async def test_structured_works_with_fake_provider() -> None:
    config = RoleConfig("evaluator", "fake", "https://fake", None, "fake", None, 1.0)
    result, raw = await complete_structured(
        FakeLLM(config), [{"role": "user", "content": "оцени"}], Score
    )
    assert result.competency == "fake competency"
    assert result.score == 3
    assert raw["provider"] == "fake"
