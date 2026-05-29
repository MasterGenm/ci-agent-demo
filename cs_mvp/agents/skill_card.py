from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cs_mvp.agents.role_card import AgentName


class SkillCard(BaseModel):
    """Declarative capability metadata for one agent skill.

    SkillCards are read-only documentation and dashboard metadata. They do not
    route prompts, change graph topology, or replace RoleCards.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=3, max_length=60)
    description: str = Field(alias="purpose", min_length=20, max_length=200)
    inputs_schema: list[str] = Field(alias="inputs", min_length=1)
    outputs_schema: list[str] = Field(alias="outputs", min_length=1)
    tools: list[str] = Field(default_factory=list)
    quality_checks: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(min_length=1)
    observability_signals: list[str] = Field(default_factory=list)

    @property
    def purpose(self) -> str:
        return self.description

    @property
    def inputs(self) -> list[str]:
        return self.inputs_schema

    @property
    def outputs(self) -> list[str]:
        return self.outputs_schema

    def short_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "signals_count": len(self.observability_signals),
            "failure_modes_count": len(self.failure_modes),
        }


AgentSkill = SkillCard


class AgentCapabilityContract(BaseModel):
    """Read-only contract that groups SkillCards for one DAG agent."""

    agent_name: AgentName
    skills: list[SkillCard] = Field(min_length=1)
    quality_invariants: list[str] = Field(min_length=1)
    failure_recovery: dict[str, str] = Field(default_factory=dict)
    upstream_contract: dict[str, str] = Field(default_factory=dict)
    downstream_contract: dict[str, str] = Field(default_factory=dict)

    @field_validator("failure_recovery", "upstream_contract", "downstream_contract", mode="before")
    @classmethod
    def _coerce_contract_map(cls, value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return {str(key): str(item) for key, item in value.items()}
        if isinstance(value, list):
            return {str(index + 1): str(item) for index, item in enumerate(value)}
        return {"value": str(value)}

    def short_metadata(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "skills_count": len(self.skills),
            "skill_names": [skill.name for skill in self.skills],
            "quality_invariants_count": len(self.quality_invariants),
            "failure_recovery_count": len(self.failure_recovery),
            "observability_signals_count": sum(
                len(skill.observability_signals) for skill in self.skills
            ),
        }


__all__ = ["AgentCapabilityContract", "AgentSkill", "SkillCard"]
