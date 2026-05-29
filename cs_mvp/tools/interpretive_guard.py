"""v1.1 Analyst interpretive guard for SWO/POS dimensions."""
from __future__ import annotations

from cs_mvp.models import AnalysisClaim


INTERPRETIVE_TERMS_SWO_POS: tuple[str, ...] = (
    "旨在",
    "意图",
    "试图",
    "为了",
    "推动",
    "强化",
    "侧重",
    "表明其战略",
    "说明其试图",
    "共同指向",
)

GUARDED_DIMENSIONS = frozenset({"swot", "positioning"})


def scan_interpretive_risk(claim: AnalysisClaim) -> tuple[bool, list[str]]:
    """Return whether a SWO/POS claim uses high-risk interpretive wording."""
    if claim.dimension not in GUARDED_DIMENSIONS:
        return False, []
    if not claim.statement:
        return False, []
    hits = [term for term in INTERPRETIVE_TERMS_SWO_POS if term in claim.statement]
    return bool(hits), hits
