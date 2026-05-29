from __future__ import annotations

import pytest

from cs_mvp.tools import llm


def test_estimate_cost_known_anthropic_model() -> None:
    cost = llm.estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(6.00)


def test_estimate_cost_known_openai_compatible_models() -> None:
    assert llm.estimate_cost("deepseek-chat", 1_000_000, 0) == pytest.approx(0.27)
    assert llm.estimate_cost("gpt-4o-mini", 0, 1_000_000) == pytest.approx(0.60)
    assert llm.estimate_cost("doubao-lite-32k", 1_000_000, 1_000_000) == pytest.approx(
        0.15
    )


def test_estimate_cost_unknown_model_uses_fallback(caplog) -> None:
    llm._warned_models.discard("totally-unknown-model")
    with caplog.at_level("WARNING"):
        cost = llm.estimate_cost("totally-unknown-model", 1_000_000, 1_000_000)
    assert cost == pytest.approx(4.00)
    assert any("totally-unknown-model" in record.message for record in caplog.records)


def test_get_extractor_llm_anthropic_missing_key_raises(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.get_extractor_llm()


def test_get_extractor_llm_openai_missing_key_raises(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.get_extractor_llm()


def test_get_extractor_llm_openai_with_base_url(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("EXTRACTOR_MODEL", "deepseek-chat")

    client = llm.get_extractor_llm()
    assert client.model_name == "deepseek-chat"
    # ChatOpenAI 把 base_url 存在 openai_api_base
    assert str(client.openai_api_base) == "https://api.deepseek.com/v1"


def test_get_extractor_llm_openai_thinking_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("EXTRACTOR_ENABLE_THINKING", raising=False)

    client = llm.get_extractor_llm()
    assert client.extra_body == {"enable_thinking": False}


def test_get_extractor_llm_openai_thinking_can_be_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("EXTRACTOR_ENABLE_THINKING", "true")

    client = llm.get_extractor_llm()
    assert client.extra_body == {"enable_thinking": True}
