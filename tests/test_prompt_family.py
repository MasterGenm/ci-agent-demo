from pathlib import Path

import pytest

from cs_mvp.prompts.families import (
    AnthropicPromptFamily,
    DefaultPromptFamily,
    OpenAIPromptFamily,
    QwenPromptFamily,
    get_prompt_family,
)

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "cs_mvp" / "prompts"


def test_default_family_loads_existing_prompts():
    family = DefaultPromptFamily()
    prompt_names = [
        "analyst",
        "analyst_cross",
        "analyst_insights",
        "analyst_revise",
        "extractor",
        "qa_critic",
        "semantic_judge",
    ]

    for name in prompt_names:
        assert family.get_prompt(name) == (PROMPTS_DIR / f"{name}.txt").read_text(
            encoding="utf-8"
        )


def test_qwen_family_inherits_default_behavior():
    assert QwenPromptFamily().get_prompt("analyst") == DefaultPromptFamily().get_prompt(
        "analyst"
    )


def test_openai_family_inherits_default_behavior():
    assert OpenAIPromptFamily().get_prompt("qa_critic") == DefaultPromptFamily().get_prompt(
        "qa_critic"
    )


def test_anthropic_family_inherits_default_behavior():
    assert AnthropicPromptFamily().get_prompt("extractor") == DefaultPromptFamily().get_prompt(
        "extractor"
    )


def test_get_prompt_family_qwen():
    assert isinstance(get_prompt_family("qwen3.6-plus"), QwenPromptFamily)
    assert isinstance(get_prompt_family("tongyi-qianwen"), QwenPromptFamily)


def test_get_prompt_family_openai():
    assert isinstance(get_prompt_family("gpt-4o"), OpenAIPromptFamily)
    assert isinstance(get_prompt_family("openai-compatible"), OpenAIPromptFamily)


def test_get_prompt_family_anthropic():
    assert isinstance(get_prompt_family("claude-3-5-sonnet"), AnthropicPromptFamily)
    assert isinstance(get_prompt_family("anthropic-haiku"), AnthropicPromptFamily)


def test_get_prompt_family_unknown_returns_default():
    assert isinstance(get_prompt_family(None), DefaultPromptFamily)
    assert isinstance(get_prompt_family("llama-3"), DefaultPromptFamily)


def test_missing_prompt_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        DefaultPromptFamily().get_prompt("not_a_real_prompt")
