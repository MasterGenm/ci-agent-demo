from cs_mvp.agents.role_card import AgentRoleCard
from cs_mvp.agents.role_cards.analyst import ANALYST_ROLE
from cs_mvp.agents.role_cards.analyst_revise import ANALYST_REVISE_ROLE
from cs_mvp.agents.role_cards.collector import COLLECTOR_ROLE
from cs_mvp.agents.role_cards.extractor import EXTRACTOR_ROLE
from cs_mvp.agents.role_cards.qa_critic import QA_CRITIC_ROLE
from cs_mvp.agents.role_cards.writer import WRITER_ROLE

ROLE_CARDS: dict[str, AgentRoleCard] = {
    "collector": COLLECTOR_ROLE,
    "extractor": EXTRACTOR_ROLE,
    "analyst": ANALYST_ROLE,
    "qa_critic": QA_CRITIC_ROLE,
    "analyst_revise": ANALYST_REVISE_ROLE,
    "writer": WRITER_ROLE,
}

__all__ = [
    "AGENT_ROLE_ORDER",
    "ANALYST_REVISE_ROLE",
    "ANALYST_ROLE",
    "COLLECTOR_ROLE",
    "EXTRACTOR_ROLE",
    "QA_CRITIC_ROLE",
    "ROLE_CARDS",
    "WRITER_ROLE",
]

AGENT_ROLE_ORDER = [
    "collector",
    "extractor",
    "analyst",
    "qa_critic",
    "analyst_revise",
    "writer",
]
