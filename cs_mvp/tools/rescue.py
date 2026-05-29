"""v1.1 LLM judge rescue path for uncertain claims.

This module is an additive layer over the keyword verifier. It reuses
``judge_one_claim`` for claims already classified as uncertain and keeps the
primary citation verifier unchanged.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel

from cs_mvp.models import AnalysisClaim, EvidenceItem
from cs_mvp.tools.semantic_judge import judge_one_claim


RESCUE_MIN_CONFIDENCE = 0.8
RESCUE_AUTO_DIMENSIONS = frozenset({"features", "pricing"})
RESCUE_REVIEW_DIMENSIONS = frozenset({"swot", "positioning"})


class RescueOutcome(BaseModel):
    claim_id: str
    action: Literal[
        "rescue_auto",
        "rescue_to_review",
        "keep_uncertain",
        "judge_failed",
    ]
    judge_verdict: str
    judge_confidence: float
    dimension: str
    original_support_score: float
    gates_passed: list[str]
    gate_failed_reason: Optional[str] = None
    judge_reasoning: str = ""
    llm_cost_usd: float = 0.0


def _claim_to_dict(claim: AnalysisClaim) -> dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "competitor_name": claim.competitor_name,
        "dimension": claim.dimension,
        "statement": claim.statement,
        "evidence_ids": claim.evidence_ids,
        "support_score": claim.support_score or 0.0,
        "verdict": "uncertain",
    }


def _evidence_map_to_dict(
    evidence_map: dict[str, EvidenceItem],
) -> dict[str, dict[str, Any]]:
    return {
        evidence_id: item.model_dump(mode="json")
        for evidence_id, item in evidence_map.items()
    }


def _evaluate_gates(
    judgment: dict[str, Any],
    dimension: str,
) -> tuple[
    Literal[
        "rescue_auto",
        "rescue_to_review",
        "keep_uncertain",
        "judge_failed",
    ],
    list[str],
    Optional[str],
]:
    verdict = str(judgment.get("semantic_verdict") or "")
    if verdict == "judge_failed":
        return "judge_failed", [], "judge_call_failed"
    if verdict != "supported":
        return "keep_uncertain", [], f"verdict_not_supported:{verdict}"

    gates_passed = ["verdict"]
    confidence = float(judgment.get("semantic_confidence") or 0.0)
    if confidence < RESCUE_MIN_CONFIDENCE:
        return "keep_uncertain", gates_passed, f"confidence_below_0.8:{confidence}"
    gates_passed.append("confidence")

    if dimension in RESCUE_AUTO_DIMENSIONS:
        gates_passed.append("dimension")
        return "rescue_auto", gates_passed, None
    if dimension in RESCUE_REVIEW_DIMENSIONS:
        gates_passed.append("dimension")
        return "rescue_to_review", gates_passed, None
    return "keep_uncertain", gates_passed, f"dimension_unknown:{dimension}"


def rescue_uncertain_with_llm(
    uncertain_claims: list[AnalysisClaim],
    evidence_map: dict[str, EvidenceItem],
    llm: Any | None = None,
) -> tuple[list[AnalysisClaim], list[AnalysisClaim], list[RescueOutcome]]:
    """Run secondary LLM rescue over uncertain claims.

    Returns ``(rescued_auto, rescued_to_review, outcomes)``. Input claims are
    not mutated; any rescued claim is returned as a copied model with audit
    fields populated.
    """
    from cs_mvp.tools.llm import get_extractor_llm

    if not uncertain_claims:
        return [], [], []

    if llm is None:
        try:
            llm = get_extractor_llm()
        except Exception as exc:  # noqa: BLE001 - rescue must not fail writer
            return [], [], [
                RescueOutcome(
                    claim_id=claim.claim_id,
                    action="judge_failed",
                    judge_verdict="judge_failed",
                    judge_confidence=0.0,
                    dimension=claim.dimension,
                    original_support_score=claim.support_score or 0.0,
                    gates_passed=[],
                    gate_failed_reason=f"llm_init_failed:{type(exc).__name__}",
                    judge_reasoning=str(exc),
                    llm_cost_usd=0.0,
                )
                for claim in uncertain_claims
            ]
    evidence_dict = _evidence_map_to_dict(evidence_map)

    rescued_auto: list[AnalysisClaim] = []
    rescued_to_review: list[AnalysisClaim] = []
    outcomes: list[RescueOutcome] = []

    for claim in uncertain_claims:
        try:
            judgment = judge_one_claim(_claim_to_dict(claim), evidence_dict, llm)
        except Exception as exc:  # noqa: BLE001 - single-claim failure is auditable
            outcomes.append(
                RescueOutcome(
                    claim_id=claim.claim_id,
                    action="judge_failed",
                    judge_verdict="judge_failed",
                    judge_confidence=0.0,
                    dimension=claim.dimension,
                    original_support_score=claim.support_score or 0.0,
                    gates_passed=[],
                    gate_failed_reason=f"exception:{type(exc).__name__}",
                    judge_reasoning=str(exc),
                    llm_cost_usd=0.0,
                )
            )
            continue

        action, gates_passed, failed_reason = _evaluate_gates(
            judgment,
            claim.dimension,
        )
        outcome = RescueOutcome(
            claim_id=claim.claim_id,
            action=action,
            judge_verdict=str(judgment.get("semantic_verdict") or ""),
            judge_confidence=float(judgment.get("semantic_confidence") or 0.0),
            dimension=claim.dimension,
            original_support_score=claim.support_score or 0.0,
            gates_passed=gates_passed,
            gate_failed_reason=failed_reason,
            judge_reasoning=str(judgment.get("reasoning") or ""),
            llm_cost_usd=float(judgment.get("_llm_cost_usd") or 0.0),
        )
        outcomes.append(outcome)

        update = {
            "rescued_by_llm_judge": True,
            "rescue_judge_verdict": outcome.judge_verdict,
            "rescue_judge_confidence": outcome.judge_confidence,
            "rescue_gates_passed": gates_passed,
            "rescue_original_score": claim.support_score,
        }
        if action == "rescue_auto":
            rescued_auto.append(claim.model_copy(update={"accepted": True, **update}))
        elif action == "rescue_to_review":
            rescued_to_review.append(
                claim.model_copy(update={"insight_candidate": True, **update})
            )

    return rescued_auto, rescued_to_review, outcomes
