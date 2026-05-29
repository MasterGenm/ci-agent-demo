"""Declarative agent role contracts for cs-mvp v1.5."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal[
    "collector",
    "extractor",
    "analyst",
    "qa_critic",
    "analyst_revise",
    "writer",
]

PromptFamilyHint = Literal["qwen", "openai", "anthropic"]


class AgentRoleCard(BaseModel):
    """Agent contract metadata.

    RoleCards are documentation and display metadata only. They do not change
    LangGraph node behavior, model prompts, or persisted run artifacts.
    """

    name: AgentName
    role: str = Field(min_length=10, max_length=80)
    goal: str = Field(min_length=20, max_length=200)
    backstory: str = Field(min_length=30, max_length=400)
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    quality_rules: list[str] = Field(min_length=1)
    upstream: list[AgentName] = Field(default_factory=list)
    downstream: list[AgentName] = Field(default_factory=list)
    prompt_family_hint: PromptFamilyHint | None = None

    def short_metadata(self) -> dict[str, str]:
        """Return dashboard-safe role metadata."""
        return {"role": self.role, "goal": self.goal}
