from __future__ import annotations

from cs_mvp.agents.capability_contracts.analyst import ANALYST_CAPABILITY
from cs_mvp.agents.capability_contracts.analyst_revise import ANALYST_REVISE_CAPABILITY
from cs_mvp.agents.capability_contracts.collector import COLLECTOR_CAPABILITY
from cs_mvp.agents.capability_contracts.extractor import EXTRACTOR_CAPABILITY
from cs_mvp.agents.capability_contracts.qa_critic import QA_CRITIC_CAPABILITY
from cs_mvp.agents.capability_contracts.writer import WRITER_CAPABILITY
from cs_mvp.agents.role_cards import AGENT_ROLE_ORDER, ROLE_CARDS
from cs_mvp.agents.skill_card import AgentCapabilityContract


AGENT_CAPABILITY_ORDER = list(AGENT_ROLE_ORDER)

CAPABILITY_CONTRACTS: dict[str, AgentCapabilityContract] = {
    "collector": COLLECTOR_CAPABILITY,
    "extractor": EXTRACTOR_CAPABILITY,
    "analyst": ANALYST_CAPABILITY,
    "qa_critic": QA_CRITIC_CAPABILITY,
    "analyst_revise": ANALYST_REVISE_CAPABILITY,
    "writer": WRITER_CAPABILITY,
}

if set(CAPABILITY_CONTRACTS) != set(ROLE_CARDS):
    missing = sorted(set(ROLE_CARDS) - set(CAPABILITY_CONTRACTS))
    extra = sorted(set(CAPABILITY_CONTRACTS) - set(ROLE_CARDS))
    raise RuntimeError(f"Capability contracts do not match RoleCards: missing={missing}, extra={extra}")


__all__ = [
    "AGENT_CAPABILITY_ORDER",
    "ANALYST_CAPABILITY",
    "ANALYST_REVISE_CAPABILITY",
    "CAPABILITY_CONTRACTS",
    "COLLECTOR_CAPABILITY",
    "EXTRACTOR_CAPABILITY",
    "QA_CRITIC_CAPABILITY",
    "WRITER_CAPABILITY",
]
