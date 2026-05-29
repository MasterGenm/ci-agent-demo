from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from cs_mvp.agents.analyst import _call_llm, _load_prompt
from cs_mvp.models import AnalysisClaim, EvidenceItem, QAFeedback, RevisionRecord
from cs_mvp.tools.llm import estimate_cost, get_extractor_llm

logger = logging.getLogger(__name__)


class LLMRevision(BaseModel):
    revised_statement: str = Field(default="")
    kept_evidence_ids: list[str] = Field(default_factory=list)
    revision_explanation: str = ""
    revision_failed: bool = False
    failure_reason: str | None = None


def _llm_model_name(llm: Any) -> str:
    for attr in ("model", "model_name"):
        value = getattr(llm, attr, None)
        if value:
            return str(value)
    return "unknown"


def _base_record(
    original: AnalysisClaim,
    qa_feedback: QAFeedback,
    revision_round: int,
) -> dict[str, Any]:
    return {
        "claim_id": original.claim_id,
        "revision_round": revision_round,
        "original_statement": original.statement,
        "original_evidence_ids": list(original.evidence_ids),
        "qa_label_before": qa_feedback.label,
        "qa_reason": qa_feedback.reason,
        "qa_issue_tags": list(qa_feedback.issue_tags),
        "suggested_revision": qa_feedback.suggested_revision,
        "revision_instruction": qa_feedback.revision_instruction,
    }


def _failure_record(
    original: AnalysisClaim,
    qa_feedback: QAFeedback,
    revision_round: int,
    reason: str,
    *,
    cost_usd: float = 0.0,
) -> RevisionRecord:
    return RevisionRecord(
        **_base_record(original, qa_feedback, revision_round),
        revised_statement=original.statement,
        revised_evidence_ids=list(original.evidence_ids),
        revision_explanation=None,
        revision_failed=True,
        failure_reason=reason,
        qa_label_after="needs_revision",
        max_revision_reached=True,
        revise_cost_usd=round(cost_usd, 6),
    )


def _input_payload(
    original: AnalysisClaim,
    qa_feedback: QAFeedback,
    evidence_map: dict[str, EvidenceItem],
) -> dict[str, Any]:
    evidence = [
        evidence_map[evidence_id].model_dump(mode="json")
        for evidence_id in original.evidence_ids
        if evidence_id in evidence_map
    ]
    return {
        "original_claim": {
            "claim_id": original.claim_id,
            "statement": original.statement,
            "evidence_ids": original.evidence_ids,
            "dimension": original.dimension,
            "competitor_name": original.competitor_name,
        },
        "qa_feedback": {
            "reason": qa_feedback.reason,
            "issue_tags": qa_feedback.issue_tags,
            "suggested_revision": qa_feedback.suggested_revision,
            "revision_instruction": qa_feedback.revision_instruction,
        },
        "evidence": evidence,
    }


def revise_claim(
    original: AnalysisClaim,
    qa_feedback: QAFeedback,
    evidence_map: dict[str, EvidenceItem],
    llm: Any | None = None,
    revision_round: int = 1,
) -> tuple[AnalysisClaim | None, RevisionRecord, float]:
    """Revise one needs_revision claim under a strict no-new-evidence contract."""

    if qa_feedback.label != "needs_revision":
        record = _failure_record(
            original,
            qa_feedback,
            revision_round,
            f"unsupported_label:{qa_feedback.label}",
        )
        return None, record, 0.0

    try:
        active_llm = llm or get_extractor_llm()
    except Exception as exc:  # noqa: BLE001
        record = _failure_record(
            original,
            qa_feedback,
            revision_round,
            f"llm_init_failed:{type(exc).__name__}",
        )
        return None, record, 0.0

    payload = _input_payload(original, qa_feedback, evidence_map)
    prompt = _load_prompt("analyst_revise.txt").replace(
        "{input_payload}",
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
    )
    parsed, error, input_tokens, output_tokens = _call_llm(
        active_llm,
        prompt,
        LLMRevision,
    )
    cost_usd = estimate_cost(_llm_model_name(active_llm), input_tokens, output_tokens)

    if parsed is None:
        record = _failure_record(
            original,
            qa_feedback,
            revision_round,
            error or "llm_revision_failed",
            cost_usd=cost_usd,
        )
        return None, record, round(cost_usd, 6)

    allowed_ids = set(original.evidence_ids)
    kept_ids = list(dict.fromkeys(parsed.kept_evidence_ids))
    invalid_ids = [evidence_id for evidence_id in kept_ids if evidence_id not in allowed_ids]
    revised_statement = parsed.revised_statement.strip()

    if parsed.revision_failed:
        record = _failure_record(
            original,
            qa_feedback,
            revision_round,
            parsed.failure_reason or "revision_failed_by_model",
            cost_usd=cost_usd,
        )
        return None, record, round(cost_usd, 6)

    if invalid_ids:
        record = _failure_record(
            original,
            qa_feedback,
            revision_round,
            f"invalid_evidence_ids:{invalid_ids}",
            cost_usd=cost_usd,
        )
        return None, record, round(cost_usd, 6)

    if not kept_ids:
        record = _failure_record(
            original,
            qa_feedback,
            revision_round,
            "empty_kept_evidence_ids",
            cost_usd=cost_usd,
        )
        return None, record, round(cost_usd, 6)

    if not revised_statement:
        record = _failure_record(
            original,
            qa_feedback,
            revision_round,
            "empty_revised_statement",
            cost_usd=cost_usd,
        )
        return None, record, round(cost_usd, 6)

    revised_claim = original.model_copy(
        update={
            "statement": revised_statement,
            "evidence_ids": kept_ids,
            "support_score": None,
            "accepted": True,
        }
    )
    record = RevisionRecord(
        **_base_record(original, qa_feedback, revision_round),
        revised_statement=revised_statement,
        revised_evidence_ids=kept_ids,
        revision_explanation=parsed.revision_explanation.strip() or None,
        revision_failed=False,
        failure_reason=None,
        qa_label_after="needs_revision",
        max_revision_reached=False,
        revise_cost_usd=round(cost_usd, 6),
    )
    return revised_claim, record, round(cost_usd, 6)


def run_revision_round(
    claims: list[AnalysisClaim],
    feedbacks: list[QAFeedback],
    evidence: list[EvidenceItem],
    revision_round: int,
    llm: Any | None = None,
) -> tuple[list[AnalysisClaim], list[RevisionRecord], float]:
    """Run one revision round for needs_revision feedback only."""

    claims_by_id = {claim.claim_id: claim for claim in claims}
    evidence_map = {item.evidence_id: item for item in evidence}
    revised_claims: list[AnalysisClaim] = []
    records: list[RevisionRecord] = []
    total_cost = 0.0

    for feedback in feedbacks:
        if feedback.label != "needs_revision":
            continue
        original = claims_by_id.get(feedback.claim_id)
        if original is None:
            logger.warning("revision feedback references missing claim %s", feedback.claim_id)
            continue
        revised, record, cost = revise_claim(
            original,
            feedback,
            evidence_map,
            llm=llm,
            revision_round=revision_round,
        )
        if revised is not None:
            revised_claims.append(revised)
        records.append(record)
        total_cost += cost

    return revised_claims, records, round(total_cost, 6)
