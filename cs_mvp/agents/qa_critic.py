from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from cs_mvp.models import (
    SCHEMA_VERSION,
    AnalysisClaim,
    EvidenceItem,
    QAAudit,
    QAFeedback,
)
from cs_mvp.tools.llm import get_extractor_llm
from cs_mvp.tools.semantic_judge import (
    _parse_json_object,
    _response_text,
    _usage_from_response,
    estimate_cost,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "qa_critic.txt"
_VALID_LABELS = frozenset({"accepted", "needs_revision", "risky"})
_VALID_ISSUE_TAGS = frozenset(
    {
        "interpretive_drift",
        "weak_evidence_alignment",
        "cross_claim_overreach",
        "dimension_mismatch",
        "number_drift",
        "recency_unverified",
        "scope_ambiguity",
    }
)


def _llm_model_name(llm: Any) -> str:
    for attr in ("model", "model_name"):
        value = getattr(llm, attr, None)
        if value:
            return str(value)
    return "unknown"


def _current_verdict(claim: AnalysisClaim) -> str:
    if claim.support_score is None:
        return "not_evaluated"
    if claim.support_score >= 0.6:
        return "pass"
    if claim.support_score >= 0.3:
        return "uncertain"
    return "fail"


def _build_claim_context(
    claim: AnalysisClaim,
    evidence_map: dict[str, EvidenceItem],
    rescue_outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_items = [
        evidence_map[evidence_id].model_dump(mode="json")
        for evidence_id in claim.evidence_ids
        if evidence_id in evidence_map
    ]
    return {
        "claim": claim.model_dump(mode="json"),
        "evidence": evidence_items,
        "verifier_state": {
            "support_score": claim.support_score,
            "current_verdict": _current_verdict(claim),
            "accepted": claim.accepted,
            "rescued_by_llm_judge": claim.rescued_by_llm_judge,
            "rescue_judge_verdict": claim.rescue_judge_verdict,
            "interpretive_risk": claim.interpretive_risk,
            "rescue_outcome": rescue_outcome,
        },
    }


def _render_prompt(context: dict[str, Any]) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace(
            "{claim_json}",
            json.dumps(context["claim"], ensure_ascii=False, indent=2),
        )
        .replace(
            "{evidence_json}",
            json.dumps(context["evidence"], ensure_ascii=False, indent=2),
        )
        .replace(
            "{verifier_state_json}",
            json.dumps(context["verifier_state"], ensure_ascii=False, indent=2),
        )
    )


def _validate_feedback_payload(
    payload: dict[str, Any],
    claim_id: str,
) -> dict[str, Any]:
    label = str(payload.get("label") or "").strip().lower()
    if label not in _VALID_LABELS:
        raise ValueError(f"invalid label: {label}")

    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason is required")

    raw_tags = payload.get("issue_tags") or []
    if not isinstance(raw_tags, list):
        raw_tags = []
    issue_tags = [
        tag
        for tag in raw_tags
        if isinstance(tag, str) and tag in _VALID_ISSUE_TAGS
    ]

    suggested_revision = payload.get("suggested_revision")
    if suggested_revision is not None and not isinstance(suggested_revision, str):
        suggested_revision = None
    if isinstance(suggested_revision, str):
        suggested_revision = suggested_revision.strip() or None

    revision_instruction = payload.get("revision_instruction")
    if revision_instruction is not None and not isinstance(revision_instruction, str):
        revision_instruction = None
    if isinstance(revision_instruction, str):
        revision_instruction = revision_instruction.strip() or None

    if label != "needs_revision":
        suggested_revision = None
        revision_instruction = None

    return {
        "claim_id": claim_id,
        "label": label,
        "reason": reason,
        "issue_tags": issue_tags,
        "suggested_revision": suggested_revision,
        "revision_instruction": revision_instruction,
    }


def critic_one_claim(
    claim: AnalysisClaim,
    evidence_map: dict[str, EvidenceItem],
    llm: Any,
    rescue_outcome: dict[str, Any] | None = None,
) -> tuple[QAFeedback, float]:
    context = _build_claim_context(claim, evidence_map, rescue_outcome)
    prompt = _render_prompt(context)
    model_name = _llm_model_name(llm)
    total_cost = 0.0

    for attempt in range(2):
        attempt_prompt = prompt
        if attempt:
            attempt_prompt += (
                "\n\nPrevious response was invalid. Return one valid JSON object "
                "matching the schema exactly."
            )
        try:
            response = llm.invoke(attempt_prompt)
            text = _response_text(response)
            input_tokens, output_tokens = _usage_from_response(
                response,
                attempt_prompt,
                text,
            )
            total_cost += estimate_cost(model_name, input_tokens, output_tokens)
            payload = _validate_feedback_payload(
                _parse_json_object(text),
                claim.claim_id,
            )
            return QAFeedback(**payload), round(total_cost, 6)
        except Exception as exc:  # retry once for transport or schema failures
            logger.warning(
                "qa_critic claim=%s attempt=%s failed: %s",
                claim.claim_id,
                attempt + 1,
                exc,
            )

    return (
        QAFeedback(
            claim_id=claim.claim_id,
            label="risky",
            reason="qa_judge_failed",
            issue_tags=[],
        ),
        round(total_cost, 6),
    )


def audit_run(
    claims: list[AnalysisClaim],
    evidence: list[EvidenceItem],
    run_id: str,
    rescue_outcomes: list[dict[str, Any]] | None = None,
    llm: Any | None = None,
) -> QAAudit:
    if llm is None:
        try:
            llm = get_extractor_llm()
        except Exception as exc:
            logger.error("qa_critic llm init failed: %s", exc)
            return QAAudit(
                run_id=run_id,
                schema_version=SCHEMA_VERSION,
                total_claims_audited=0,
                accepted_count=0,
                needs_revision_count=0,
                risky_count=0,
                feedbacks=[],
                auditor_model=None,
                llm_cost_usd=0.0,
                notes=f"llm_init_failed:{type(exc).__name__}",
            )

    evidence_map = {item.evidence_id: item for item in evidence}
    rescue_map = {
        str(item.get("claim_id")): item
        for item in rescue_outcomes or []
        if item.get("claim_id")
    }
    feedbacks: list[QAFeedback] = []
    total_cost = 0.0
    counts = {"accepted": 0, "needs_revision": 0, "risky": 0}

    for claim in claims:
        feedback, cost = critic_one_claim(
            claim,
            evidence_map,
            llm,
            rescue_outcome=rescue_map.get(claim.claim_id),
        )
        feedbacks.append(feedback)
        counts[feedback.label] += 1
        total_cost += cost

    return QAAudit(
        run_id=run_id,
        schema_version=SCHEMA_VERSION,
        total_claims_audited=len(claims),
        accepted_count=counts["accepted"],
        needs_revision_count=counts["needs_revision"],
        risky_count=counts["risky"],
        feedbacks=feedbacks,
        auditor_model=_llm_model_name(llm),
        llm_cost_usd=round(total_cost, 6),
    )


def render_qa_summary_md(
    audit: QAAudit,
    claims_by_id: dict[str, AnalysisClaim],
) -> str:
    lines = [
        "# QA Critic Audit Report",
        "",
        f"- Run ID: {audit.run_id}",
        f"- Schema Version: {audit.schema_version}",
        f"- Audited At: {audit.audited_at.isoformat()}",
        f"- Auditor Model: {audit.auditor_model or 'unknown'}",
        f"- Total LLM Cost: ${audit.llm_cost_usd:.6f}",
    ]
    if audit.notes:
        lines.append(f"- Notes: {audit.notes}")

    lines.extend(
        [
            "",
            "## Summary",
            "",
            "| Label | Count |",
            "| --- | ---: |",
            f"| accepted | {audit.accepted_count} |",
            f"| needs_revision | {audit.needs_revision_count} |",
            f"| risky | {audit.risky_count} |",
            f"| total | {audit.total_claims_audited} |",
            "",
        ]
    )

    for label in ("needs_revision", "risky"):
        feedbacks = [item for item in audit.feedbacks if item.label == label]
        if not feedbacks:
            continue
        lines.extend(["", f"## {label.replace('_', ' ').title()} ({len(feedbacks)})", ""])
        for feedback in feedbacks:
            claim = claims_by_id.get(feedback.claim_id)
            statement = claim.statement if claim else "(claim not found)"
            if len(statement) > 180:
                statement = f"{statement[:179]}..."
            tags = ", ".join(feedback.issue_tags) if feedback.issue_tags else "(none)"
            revision = feedback.suggested_revision or "(none)"
            instruction = feedback.revision_instruction or "(none)"
            lines.extend(
                [
                    f"### {feedback.claim_id}",
                    "",
                    f"- Statement: {statement}",
                    f"- Issue tags: {tags}",
                    f"- Reason: {feedback.reason}",
                    f"- Suggested revision: {revision}",
                    f"- Revision instruction: {instruction}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"
