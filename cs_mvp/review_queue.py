from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SEVERITY_RANK = {"high": 0, "warning": 1, "medium": 2, "low": 3, "info": 4}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _preview(text: str | None, limit: int = 180) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}..."


def _evidence_index(evidence: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("evidence_id")): item
        for item in evidence
        if item.get("evidence_id")
    }


def _infer_competitor(
    item: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> str | None:
    if item.get("competitor_name"):
        return str(item.get("competitor_name"))
    for evidence_id in item.get("evidence_ids") or []:
        evidence = evidence_by_id.get(str(evidence_id))
        if evidence and evidence.get("competitor_name"):
            return str(evidence.get("competitor_name"))
    return None


def _claim_entry(
    item: dict[str, Any],
    *,
    entry_type: str,
    severity: str,
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": entry_type,
        "severity": severity,
        "claim_id": item.get("claim_id"),
        "competitor_name": _infer_competitor(item, evidence_by_id),
        "dimension": item.get("dimension"),
        "statement_preview": _preview(item.get("statement")),
        "evidence_ids": item.get("evidence_ids") or [],
        "support_score": _safe_float(item.get("support_score")),
        "verdict": item.get("verdict"),
        "reason": item.get("reason"),
    }


def _build_claim_entries(
    discarded_claims: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in discarded_claims:
        verdict = str(item.get("verdict") or "").lower()
        support_score = _safe_float(item.get("support_score"))
        if verdict == "uncertain" or 0.3 <= support_score < 0.6:
            entries.append(
                _claim_entry(
                    item,
                    entry_type="claim_uncertain",
                    severity="medium",
                    evidence_by_id=evidence_by_id,
                )
            )
        elif verdict == "fail":
            entries.append(
                _claim_entry(
                    item,
                    entry_type="claim_failed",
                    severity="low",
                    evidence_by_id=evidence_by_id,
                )
            )
    return entries


def _build_insight_candidate_entries(
    claims: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in claims:
        if not item.get("insight_candidate"):
            continue
        entries.append(
            {
                "type": "insight_candidate",
                "severity": "info",
                "claim_id": item.get("claim_id"),
                "competitor_name": _infer_competitor(item, evidence_by_id),
                "dimension": item.get("dimension"),
                "statement_preview": _preview(item.get("statement")),
                "evidence_ids": item.get("evidence_ids") or [],
                "source": (
                    "rescued_to_review"
                    if item.get("rescued_by_llm_judge")
                    else "interpretive_risk"
                ),
                "rescue_judge_verdict": item.get("rescue_judge_verdict"),
                "rescue_judge_confidence": item.get("rescue_judge_confidence"),
                "interpretive_hits": item.get("interpretive_hits"),
            }
        )
    return entries


def _claim_index(
    claims: list[dict[str, Any]],
    discarded_claims: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in [*discarded_claims, *claims]:
        claim_id = item.get("claim_id")
        if claim_id:
            index[str(claim_id)] = item
    return index


def _build_qa_critic_entries(
    qa_audit: dict[str, Any] | None,
    claim_index: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not qa_audit:
        return []
    feedbacks = qa_audit.get("feedbacks")
    if not isinstance(feedbacks, list):
        return []

    entries: list[dict[str, Any]] = []
    for feedback in feedbacks:
        if not isinstance(feedback, dict):
            continue
        label = str(feedback.get("label") or "").lower()
        if label not in {"needs_revision", "risky"}:
            continue
        claim_id = str(feedback.get("claim_id") or "")
        claim = claim_index.get(claim_id, {})
        entries.append(
            {
                "type": "qa_critic",
                "severity": "warning" if label == "needs_revision" else "info",
                "claim_id": claim_id or None,
                "competitor_name": _infer_competitor(claim, evidence_by_id),
                "dimension": claim.get("dimension"),
                "statement_preview": _preview(claim.get("statement")),
                "evidence_ids": claim.get("evidence_ids") or [],
                "qa_label": label,
                "qa_issue_tags": feedback.get("issue_tags") or [],
                "qa_reason": feedback.get("reason"),
            }
        )
    return entries


def _build_low_recall_entries(
    run_summary: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    low_recall = (
        run_summary.get("quality_gates", {}).get("low_recall_competitors", [])
        if isinstance(run_summary, dict)
        else []
    )
    evidence_counts: dict[str, int] = {}
    for item in evidence:
        competitor = item.get("competitor_name")
        if competitor:
            evidence_counts[str(competitor)] = evidence_counts.get(str(competitor), 0) + 1

    return [
        {
            "type": "low_recall_competitor",
            "severity": "high",
            "competitor_name": str(name),
            "evidence_count": evidence_counts.get(str(name), 0),
            "reason": "Competitor has too few evidence items for reliable comparison.",
        }
        for name in low_recall
    ]


def _build_source_entries(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for item in sources:
        if item.get("fetch_status") != "failed":
            continue
        entries.append(
            {
                "type": "source_fetch_failed",
                "severity": "low",
                "source_id": item.get("source_id"),
                "competitor_name": item.get("competitor_name"),
                "url": item.get("url"),
                "failure_reason": item.get("failure_reason") or "unknown",
            }
        )
    return entries


def _build_extractor_entries(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for item in failures:
        stage = str(item.get("stage") or "")
        error = str(item.get("error") or "")
        if stage != "quote_match" and "quote" not in error:
            continue
        entries.append(
            {
                "type": "extractor_quote_mismatch",
                "severity": "low",
                "source_id": item.get("source_id"),
                "chunk_id": item.get("chunk_id"),
                "error": error or None,
                "quote_preview": _preview(item.get("quote_preview"), limit=120),
            }
        )
    return entries


def _sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda item: (
            _SEVERITY_RANK.get(str(item.get("severity")), 99),
            str(item.get("type") or ""),
            str(item.get("claim_id") or item.get("competitor_name") or item.get("source_id") or ""),
        ),
    )


def build_review_queue(run_dir: Path) -> list[dict[str, Any]]:
    run_dir = Path(run_dir)
    claims = _load_json(run_dir / "claims.json", [])
    discarded_claims = _load_json(run_dir / "discarded_claims.json", [])
    sources = _load_json(run_dir / "sources.json", [])
    evidence = _load_json(run_dir / "evidence.json", [])
    extractor_failures = _load_json(run_dir / "extractor_failures.json", [])
    run_summary = _load_json(run_dir / "run_summary.json", {})
    qa_audit = _load_json(run_dir / "qa_audit.json", {})

    evidence_by_id = _evidence_index(evidence if isinstance(evidence, list) else [])
    indexed_claims = _claim_index(
        claims if isinstance(claims, list) else [],
        discarded_claims if isinstance(discarded_claims, list) else [],
    )
    entries: list[dict[str, Any]] = []
    entries.extend(
        _build_low_recall_entries(
            run_summary if isinstance(run_summary, dict) else {},
            evidence if isinstance(evidence, list) else [],
        )
    )
    entries.extend(
        _build_claim_entries(
            discarded_claims if isinstance(discarded_claims, list) else [],
            evidence_by_id,
        )
    )
    entries.extend(
        _build_insight_candidate_entries(
            claims if isinstance(claims, list) else [],
            evidence_by_id,
        )
    )
    entries.extend(
        _build_qa_critic_entries(
            qa_audit if isinstance(qa_audit, dict) else {},
            indexed_claims,
            evidence_by_id,
        )
    )
    entries.extend(_build_source_entries(sources if isinstance(sources, list) else []))
    entries.extend(
        _build_extractor_entries(
            extractor_failures if isinstance(extractor_failures, list) else []
        )
    )
    return _sort_entries(entries)


def write_review_queue(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "review_queue.json"
    _write_json(path, build_review_queue(run_dir))
    return path
