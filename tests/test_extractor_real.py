from __future__ import annotations

from typing import Any

from cs_mvp.agents import extractor
from cs_mvp.models import SourceRecord


VALID_QUOTE = (
    "Cursor provides AI coding assistance with code completion, chat, and "
    "project-aware editing inside the developer workspace."
)


class FakeStructuredLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses

    def invoke(self, prompt: str) -> Any:
        if not self.responses:
            return {"items": []}
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeLLM:
    model = "claude-haiku-4-5"

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses

    def with_structured_output(self, schema: Any, **kwargs: Any) -> FakeStructuredLLM:
        return FakeStructuredLLM(self.responses)


def _source(raw_text: str, source_id: str = "S-1") -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        run_id="RUN-abcdef",
        competitor_name="Cursor",
        url="https://cursor.com",
        source_type="official_site",
        raw_text=raw_text,
        fetch_status="fetched",
        raw_text_length=len(raw_text),
    )


def _valid_item(quote: str = VALID_QUOTE, fact: str = "Cursor provides AI coding assistance") -> dict:
    return {
        "competitor_name": "Cursor",
        "claim_type": "feature",
        "quote": quote,
        "normalized_fact": fact,
        "confidence": 0.82,
    }


def test_real_extract_accepts_bare_list_output(monkeypatch) -> None:
    # DashScope / qwen 在 json_object 模式下常返回裸数组,
    # extractor 应自动包成 {"items": [...]}
    responses = [[_valid_item()]]
    monkeypatch.setattr(extractor, "get_extractor_llm", lambda: FakeLLM(responses))

    evidence, failures, stats = extractor.real_extract(
        "RUN-abcdef",
        [_source(f"Intro. {VALID_QUOTE} Outro.")],
    )

    assert len(evidence) == 1
    assert failures == []
    assert stats["schema_pass_rate"] == 1.0


def test_real_extract_accepts_single_object_output(monkeypatch) -> None:
    # 偶尔模型只返回一个 evidence dict 而不是数组
    responses = [_valid_item()]
    monkeypatch.setattr(extractor, "get_extractor_llm", lambda: FakeLLM(responses))

    evidence, failures, _stats = extractor.real_extract(
        "RUN-abcdef",
        [_source(f"Intro. {VALID_QUOTE} Outro.")],
    )

    assert len(evidence) == 1
    assert failures == []


def test_real_extract_handles_schema_failure_with_retry(monkeypatch) -> None:
    responses = [
        {"items": [{"claim_type": "bad"}]},
        {"items": [_valid_item()]},
    ]
    monkeypatch.setattr(extractor, "get_extractor_llm", lambda: FakeLLM(responses))

    evidence, failures, stats = extractor.real_extract(
        "RUN-abcdef",
        [_source(f"Intro. {VALID_QUOTE} Outro.")],
    )

    assert len(evidence) == 1
    assert failures == []
    assert stats["schema_pass_rate"] == 1.0


def test_real_extract_quote_not_in_raw_text_is_dropped(monkeypatch) -> None:
    responses = [{"items": [_valid_item("This quote is long enough for validation but absent from source text.")]}]
    monkeypatch.setattr(extractor, "get_extractor_llm", lambda: FakeLLM(responses))

    evidence, failures, stats = extractor.real_extract(
        "RUN-abcdef",
        [_source("Cursor source text without the generated quote.")],
    )

    assert evidence == []
    assert failures[0]["stage"] == "quote_match"
    assert stats["quote_match_rate"] == 0.0


def test_real_extract_deduplicates_by_normalized_fact(monkeypatch) -> None:
    responses = [
        {"items": [_valid_item()]},
        {"items": [_valid_item()]},
    ]
    monkeypatch.setattr(extractor, "get_extractor_llm", lambda: FakeLLM(responses))
    raw_text = f"{VALID_QUOTE}\n\n" + ("padding text " * 700)

    evidence, failures, stats = extractor.real_extract(
        "RUN-abcdef",
        [_source(raw_text)],
    )

    assert len(evidence) == 1
    assert failures == []
    assert stats["duplicate_rate"] == 0.5


def test_real_extract_stops_when_budget_exhausted(monkeypatch) -> None:
    responses = [{"items": []} for _ in range(4)]
    monkeypatch.setattr(extractor, "get_extractor_llm", lambda: FakeLLM(responses))

    evidence, failures, stats = extractor.real_extract(
        "RUN-abcdef",
        [_source("high token text " * 5000)],
        max_cost_usd=0.001,
    )

    assert evidence == []
    assert failures == []
    assert stats["budget_exhausted"] is True


def test_real_extract_quote_length_validation(monkeypatch) -> None:
    short_quote = "This quote has more than twenty chars"
    responses = [{"items": [_valid_item(short_quote)]}]
    monkeypatch.setattr(extractor, "get_extractor_llm", lambda: FakeLLM(responses))

    evidence, failures, _stats = extractor.real_extract(
        "RUN-abcdef",
        [_source(f"{short_quote} plus raw text.")],
    )

    assert evidence == []
    assert failures[0]["stage"] == "quote_length"
