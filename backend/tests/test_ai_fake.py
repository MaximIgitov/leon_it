from __future__ import annotations

import io
import json
import wave
from enum import StrEnum

from pydantic import BaseModel, Field

from leonit.ai.config import RoleConfig
from leonit.ai.gateway import get_llm, get_stt, get_tts
from leonit.ai.providers.base import StreamAccumulator
from leonit.ai.providers.fake import FakeLLM, FakeSTT, FakeTTS, fake_value_for_schema


def _config(role: str) -> RoleConfig:
    return RoleConfig(
        role=role,
        provider="fake",
        base_url="https://fake.local/v1",
        api_key=None,
        model=f"fake-{role}",
        proxy_url=None,
        timeout_s=1.0,
    )


class Verdict(StrEnum):
    hire = "hire"
    no_hire = "no_hire"
    review = "review"


class CompetencyScore(BaseModel):
    name: str
    score: int = Field(ge=1, le=5)
    evidence: list[str] = Field(min_length=1)


class Conclusion(BaseModel):
    verdict: Verdict
    summary: str
    confidence: float = Field(ge=0, le=1)
    competencies: list[CompetencyScore]
    risks: list[str] | None = None
    needs_review: bool


async def test_fake_llm_returns_json_matching_schema() -> None:
    llm = FakeLLM(_config("evaluator"))
    response = await llm.chat(
        [{"role": "user", "content": "Оцени кандидата"}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "Conclusion", "schema": Conclusion.model_json_schema()},
        },
    )
    assert response.content
    conclusion = Conclusion.model_validate_json(response.content)
    assert conclusion.verdict == Verdict.hire  # первый вариант enum
    assert conclusion.summary == "fake summary"
    assert conclusion.confidence == 0.5  # середина диапазона 0..1
    assert conclusion.needs_review is True
    assert len(conclusion.competencies) == 2
    assert conclusion.competencies[0].score == 3
    assert conclusion.competencies[0].evidence == ["fake evidence 1", "fake evidence 2"]
    assert response.usage is not None and response.usage.total_tokens > 0


def test_fake_value_handles_refs_formats_and_bounds() -> None:
    schema = {
        "$defs": {
            "Inner": {
                "type": "object",
                "properties": {"when": {"type": "string", "format": "date-time"}},
            }
        },
        "type": "object",
        "properties": {
            "inner": {"$ref": "#/$defs/Inner"},
            "count": {"type": "integer", "minimum": 10},
            "ratio": {"type": "number", "maximum": 1},
            "tag": {"anyOf": [{"type": "null"}, {"type": "string"}]},
            "code": {"const": "X"},
            "items": {"type": "array", "items": {"type": "string"}, "maxItems": 1},
        },
    }
    value = fake_value_for_schema(schema)
    assert value["inner"]["when"] == "2026-01-01T12:00:00Z"
    assert value["count"] == 10
    assert value["ratio"] == 1
    assert value["tag"] == "fake tag"
    assert value["code"] == "X"
    assert value["items"] == ["fake items 1"]


async def test_fake_llm_echoes_last_user_message() -> None:
    llm = FakeLLM(_config("assistant"))
    response = await llm.chat(
        [
            {"role": "system", "content": "Ты ассистент"},
            {"role": "user", "content": "Привет"},
            {"role": "assistant", "content": "Здравствуйте"},
            {"role": "user", "content": "Создай вакансию"},
        ]
    )
    assert response.content == "[fake assistant] Создай вакансию"
    assert response.tool_calls == []
    assert response.finish_reason == "stop"


async def test_fake_llm_returns_tool_call_from_marker() -> None:
    llm = FakeLLM(_config("assistant"))
    tools = [{"type": "function", "function": {"name": "create_vacancy", "parameters": {}}}]
    response = await llm.chat(
        [{"role": "user", "content": 'Сделай: [[call:create_vacancy {"title": "Python dev"}]]'}],
        tools=tools,
    )
    assert response.content is None
    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "create_vacancy"
    assert call.arguments_json() == {"title": "Python dev"}

    # Без tools маркер — просто текст.
    plain = await llm.chat([{"role": "user", "content": "[[call:create_vacancy]]"}])
    assert plain.tool_calls == [] and plain.content


async def test_fake_llm_streams_in_three_deltas() -> None:
    llm = FakeLLM(_config("interviewer"))
    messages = [{"role": "user", "content": "Расскажите о себе, пожалуйста"}]
    deltas = [delta async for delta in llm.stream_chat(messages)]
    assert len(deltas) == 3
    assert deltas[-1].finish_reason == "stop"
    full = await llm.chat(messages)
    assert "".join(delta.content or "" for delta in deltas) == full.content


async def test_fake_llm_streams_tool_call_by_index() -> None:
    llm = FakeLLM(_config("assistant"))
    tools = [{"type": "function", "function": {"name": "rank", "parameters": {}}}]
    accumulator = StreamAccumulator()
    async for delta in llm.stream_chat(
        [{"role": "user", "content": '[[call:rank {"vacancy_id": 7, "top": 3}]]'}], tools=tools
    ):
        accumulator.add(delta)
    response = accumulator.response()
    assert response.finish_reason == "tool_calls"
    assert [call.name for call in response.tool_calls] == ["rank"]
    assert response.tool_calls[0].arguments_json() == {"vacancy_id": 7, "top": 3}


async def test_fake_stt_text_sidecar_and_binary() -> None:
    stt = FakeSTT(_config("stt"))
    as_text = await stt.transcribe("Я работал с FastAPI".encode(), content_type="text/plain")
    assert as_text.text == "Я работал с FastAPI"
    assert len(as_text.segments) == 1 and as_text.segments[0].end_s > 0

    sidecar = await stt.transcribe(b"\x00" * 10, content_type="audio/webm", prompt="sidecar:Ответ")
    assert sidecar.text == "Ответ"

    binary = await stt.transcribe(b"\x00" * 1234, content_type="audio/webm", prompt="skills")
    assert binary.text == "(фейковая транскрипция 1234 байт)"
    assert binary.language == "ru"
    assert binary.segments[0].start_s == 0.0


async def test_fake_tts_returns_one_second_of_wav_silence() -> None:
    tts = FakeTTS(_config("tts"))
    result = await tts.synthesize("Расскажите о себе", audio_format="mp3")
    assert result.content_type == "audio/wav"
    assert tts.resolve_format("mp3") == "wav"
    with wave.open(io.BytesIO(result.data)) as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() / handle.getframerate() == 1.0


async def test_gateway_returns_fake_providers_and_caches_them() -> None:
    llm = get_llm("evaluator")
    assert isinstance(llm, FakeLLM)
    assert get_llm("evaluator") is llm
    assert isinstance(get_stt(), FakeSTT)
    assert isinstance(get_tts(), FakeTTS)
    payload = json.loads(
        (
            await llm.chat(
                [{"role": "user", "content": "x"}], response_format={"type": "json_object"}
            )
        ).content
    )
    assert payload == {"content": "[fake evaluator] x"}
