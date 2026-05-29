"""Prompt family routing for cs-mvp v1.5.

The current implementation intentionally keeps prompt text unchanged. Families
only centralize prompt file loading and create future extension points for
model-family-specific wording.
"""

from __future__ import annotations

from abc import ABC
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent


class PromptFamily(ABC):
    """Base prompt family."""

    name: str = "default"

    def get_prompt(self, agent_name: str, variant: str | None = None) -> str:
        """Load a prompt file from cs_mvp/prompts without modifying content."""
        del variant
        path = _PROMPTS_DIR / f"{agent_name}.txt"
        if not path.exists():
            raise FileNotFoundError(f"prompt file not found: {path}")
        return path.read_text(encoding="utf-8")


class DefaultPromptFamily(PromptFamily):
    """Default family; behavior equals direct prompt file loading."""

    name = "default"


def get_prompt_family(model_name: str | None = None) -> PromptFamily:
    """Select a prompt family by model/provider name."""
    if model_name is None:
        return DefaultPromptFamily()

    lowered = model_name.lower()
    if "qwen" in lowered or "tongyi" in lowered:
        from cs_mvp.prompts.families.qwen import QwenPromptFamily

        return QwenPromptFamily()
    if "gpt" in lowered or "openai" in lowered:
        from cs_mvp.prompts.families.openai import OpenAIPromptFamily

        return OpenAIPromptFamily()
    if "claude" in lowered or "anthropic" in lowered:
        from cs_mvp.prompts.families.anthropic import AnthropicPromptFamily

        return AnthropicPromptFamily()
    return DefaultPromptFamily()
