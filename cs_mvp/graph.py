from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph

from cs_mvp import db
from cs_mvp.agents.analyst import real_analyze
from cs_mvp.agents.collector import real_collect
from cs_mvp.agents.extractor import real_extract
from cs_mvp.agents.gap_fill import MAX_GAP_FILL_ROUNDS, find_gaps, run_gap_fill
from cs_mvp.agents.writer import render_pm_report_artifacts, render_report
from cs_mvp.artifacts import export_html_report, write_summary_artifacts
from cs_mvp.models import AgentNodeRun, GraphState, QAFeedback, Report, RevisionRecord
from cs_mvp.report_style_audit import write_report_style_audit
from cs_mvp.review_queue import write_review_queue
from cs_mvp.tools.semantic_judge import write_semantic_judge_placeholder
from cs_mvp.tools.url_utils import normalize_url_key

logger = logging.getLogger(__name__)

_RUNS_DIR = "runs"

NODE_MODES = {
    "collector": "real",
    "extractor": "real",
    "analyst": "real",
    "analyst_revise": "real",
    "qa_critic": "real",
    "writer": "real",
}


def _qa_critic_enabled() -> bool:
    return os.environ.get("ENABLE_QA_CRITIC", "1") != "0"


def _revision_loop_enabled() -> bool:
    return os.environ.get("ENABLE_REVISION_LOOP", "1") != "0"


def _gap_fill_enabled() -> bool:
    return os.environ.get("ENABLE_GAP_FILL", "1") != "0"


def _active_node_modes() -> dict[str, str]:
    modes = dict(NODE_MODES)
    if _gap_fill_enabled():
        modes["gap_fill"] = "real"
    if not _qa_critic_enabled():
        modes.pop("qa_critic", None)
        modes.pop("analyst_revise", None)
    if not _gap_fill_enabled():
        modes.pop("gap_fill", None)
    if not _revision_loop_enabled():
        modes.pop("analyst_revise", None)
    return modes


def _as_state(state: GraphState | dict[str, Any]) -> GraphState:
    return state if isinstance(state, GraphState) else GraphState.model_validate(state)


def _json(data: Any) -> str:
    if hasattr(data, "model_dump"):
        return data.model_dump_json()
    return json.dumps(data, ensure_ascii=False, default=str)


def _output_summary(updates: dict[str, Any]) -> dict[str, Any]:
    """节点输出摘要：只记录产物数量和小型字段，避免 trace.json 暴涨。"""
    summary: dict[str, Any] = {}
    for key, value in updates.items():
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
            if key == "sources":
                summary["source_ids"] = [item.get("source_id") for item in value][:50]
            elif key == "evidence":
                summary["evidence_ids"] = [item.get("evidence_id") for item in value][:50]
            elif key in ("claims", "discarded_claims"):
                summary[f"{key}_ids"] = [item.get("claim_id") for item in value][:50]
        elif key == "report_md" and isinstance(value, str):
            summary["report_md_chars"] = len(value)
        elif key == "qa_audit" and isinstance(value, dict):
            summary["qa_audit"] = {
                "total_claims_audited": value.get("total_claims_audited"),
                "accepted_count": value.get("accepted_count"),
                "needs_revision_count": value.get("needs_revision_count"),
                "risky_count": value.get("risky_count"),
                "notes": value.get("notes"),
            }
        elif key == "revision_history" and isinstance(value, list):
            summary["revision_history_count"] = len(value)
        elif key == "task":
            summary["task_id"] = value.get("task_id") if isinstance(value, dict) else None
        else:
            summary[key] = value
    return summary


def _json_file(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _node_input_summary(state: GraphState, node_name: str) -> dict[str, Any]:
    """节点输入摘要：只记录上游产物的数量和关键标识，不存完整 state。

    M1 接真实抓取后 raw_text 会让完整 state 暴涨到 MB 级，导致 trace.json
    无法浏览。这里按"我消费什么"原则做瘦身。
    """
    summary: dict[str, Any] = {
        "task_id": state.task.task_id,
        "run_id": state.run_id,
        "competitors": [c.name for c in state.task.competitors],
    }
    if node_name in ("extractor", "analyst", "gap_fill", "qa_critic", "writer", "finalize"):
        summary["sources_count"] = len(state.sources)
    if node_name in ("analyst", "gap_fill", "qa_critic", "analyst_revise", "writer", "finalize"):
        summary["evidence_count"] = len(state.evidence)
    if node_name in ("gap_fill", "qa_critic", "analyst_revise", "writer", "finalize"):
        summary["claims_count"] = len(state.claims)
    if node_name in ("gap_fill", "qa_critic", "analyst_revise", "writer", "finalize"):
        summary["gap_fill_round"] = state.gap_fill_round
    if node_name in ("qa_critic", "analyst_revise", "writer", "finalize"):
        summary["revision_round"] = state.revision_round
        summary["revision_history_count"] = len(state.revision_history)
    if node_name == "finalize":
        summary["accepted_claims"] = sum(1 for c in state.claims if c.accepted)
        summary["discarded_claims_count"] = len(state.discarded_claims)
        summary["qa_audit_present"] = bool(state.qa_audit)
    return summary


def _new_node_run(state: GraphState, node_name: str) -> AgentNodeRun:
    return AgentNodeRun(
        node_run_id=f"NR-{uuid.uuid4().hex}",
        run_id=state.run_id,
        node_name=node_name,  # type: ignore[arg-type]
        status="running",
        input_json=json.dumps(_node_input_summary(state, node_name), ensure_ascii=False),
    )


def _run_node(
    raw_state: GraphState | dict[str, Any],
    node_name: str,
    fn: Callable[[GraphState], dict[str, Any]],
) -> dict[str, Any]:
    state = _as_state(raw_state)
    node_run = _new_node_run(state, node_name)
    db.insert_node_run(node_run)
    logger.info("node %s started", node_name)
    started = time.perf_counter()
    try:
        updates = fn(state)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        db.update_node_run(node_run.node_run_id, "failed", "{}", latency_ms, str(exc))
        db.update_run_status(state.run_id, "failed", 0.0, 0)
        db.update_task_status(state.task.task_id, "failed", str(exc))
        logger.exception("node %s failed", node_name)
        raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    output_summary = json.dumps(_output_summary(updates), ensure_ascii=False)
    # extractor_stats / analyst_stats / writer_stats 都遵循同样的字段约定
    llm_stats = (
        updates.get("extractor_stats")
        or updates.get("analyst_stats")
        or updates.get("analyst_revise_stats")
        or updates.get("qa_critic_stats")
        or updates.get("writer_stats")
    )
    db.update_node_run(
        node_run.node_run_id,
        "completed",
        output_summary,
        latency_ms,
        llm_model=llm_stats.get("model") if isinstance(llm_stats, dict) else None,
        input_tokens=llm_stats.get("input_tokens")
        if isinstance(llm_stats, dict)
        else None,
        output_tokens=llm_stats.get("output_tokens")
        if isinstance(llm_stats, dict)
        else None,
        cost_usd=llm_stats.get("llm_cost_usd")
        if isinstance(llm_stats, dict)
        else None,
    )
    logger.info("node %s completed", node_name)
    return updates


def node_task_init(state: GraphState | dict[str, Any]) -> dict[str, Any]:
    def logic(current: GraphState) -> dict[str, Any]:
        db.update_task_status(current.task.task_id, "running")
        return {"task": current.task.model_dump(mode="json")}

    return _run_node(state, "task_init", logic)


def node_collector(state: GraphState | dict[str, Any]) -> dict[str, Any]:
    def logic(current: GraphState) -> dict[str, Any]:
        sources = []
        seen_urls: set[str] = set()
        for competitor in current.task.competitors:
            for source in real_collect(
                current.run_id,
                competitor.name,
                current.task.query,
                exclude_keywords=competitor.exclude_keywords,
                seed_urls=competitor.seed_urls,
            ):
                key = normalize_url_key(source.url)
                if key in seen_urls:
                    source.fetch_status = "skipped"
                    source.failure_reason = "duplicate"
                    source.content_hash = None
                    source.raw_text = None
                    source.raw_text_length = 0
                seen_urls.add(key)
                db.insert_source(source)
                sources.append(source)
        return {"sources": [source.model_dump(mode="json") for source in sources]}

    return _run_node(state, "collector", logic)


def node_extractor(state: GraphState | dict[str, Any]) -> dict[str, Any]:
    def logic(current: GraphState) -> dict[str, Any]:
        max_concurrency = int(os.getenv("EXTRACTOR_MAX_CONCURRENCY", "4"))
        max_cost_usd = float(os.getenv("EXTRACTOR_MAX_COST_USD", "2.0"))
        evidence, failures, stats = real_extract(
            current.run_id,
            current.sources,
            max_concurrency=max_concurrency,
            max_cost_usd=max_cost_usd,
        )
        run_dir = Path(_RUNS_DIR) / current.task.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        _json_file(run_dir / "extractor_failures.json", failures)
        _json_file(run_dir / "extractor_stats.json", stats)

        for item in evidence:
            db.insert_evidence(item)
        return {
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "extractor_failures": failures,
            "extractor_stats": stats,
        }

    return _run_node(state, "extractor", logic)


def node_analyst(state: GraphState | dict[str, Any]) -> dict[str, Any]:
    def logic(current: GraphState) -> dict[str, Any]:
        max_concurrency = int(os.getenv("ANALYST_MAX_CONCURRENCY", "4"))
        claims, failures, stats = real_analyze(
            current.run_id,
            current.evidence,
            [c.name for c in current.task.competitors],
            max_concurrency=max_concurrency,
        )
        run_dir = Path(_RUNS_DIR) / current.task.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        _json_file(run_dir / "analyst_failures.json", failures)
        _json_file(run_dir / "analyst_stats.json", stats)
        # claims 在 Writer 经 CitationVerifier 评估后再统一入库
        return {
            "claims": [claim.model_dump(mode="json") for claim in claims],
            "analyst_failures": failures,
            "analyst_stats": stats,
        }

    return _run_node(state, "analyst", logic)


def _next_after_analyst() -> str:
    return "qa_critic" if _qa_critic_enabled() else "writer"


def _route_after_analyst(state: GraphState | dict[str, Any]) -> str:
    if not _gap_fill_enabled():
        return _next_after_analyst()
    current = _as_state(state)
    if current.gap_fill_round >= MAX_GAP_FILL_ROUNDS:
        return _next_after_analyst()
    competitors = [competitor.name for competitor in current.task.competitors]
    gaps = find_gaps(current.claims, competitors)
    if not gaps:
        return _next_after_analyst()
    return "gap_fill"


def node_gap_fill(state: GraphState | dict[str, Any]) -> dict[str, Any]:
    def logic(current: GraphState) -> dict[str, Any]:
        try:
            return run_gap_fill(current)
        except Exception as exc:  # noqa: BLE001
            logger.debug("gap_fill node skipped after failure: %s", exc)
            return {"gap_fill_round": min(current.gap_fill_round + 1, MAX_GAP_FILL_ROUNDS)}

    return _run_node(state, "gap_fill", logic)


def _qa_feedbacks_from_audit(audit_payload: dict[str, Any] | None) -> list[QAFeedback]:
    feedbacks: list[QAFeedback] = []
    if not audit_payload:
        return feedbacks
    for item in audit_payload.get("feedbacks") or []:
        try:
            feedbacks.append(QAFeedback.model_validate(item))
        except Exception as exc:  # noqa: BLE001
            logger.warning("invalid qa feedback ignored during revision routing: %s", exc)
    return feedbacks


def _has_needs_revision(state: GraphState | dict[str, Any]) -> bool:
    current = _as_state(state)
    if not _qa_critic_enabled() or not _revision_loop_enabled():
        return False
    if current.revision_round >= 1:
        return False
    return any(
        feedback.label == "needs_revision"
        for feedback in _qa_feedbacks_from_audit(current.qa_audit)
    )


def _route_after_qa_critic(state: GraphState | dict[str, Any]) -> str:
    return "analyst_revise" if _has_needs_revision(state) else "writer"


def _apply_qa_after_labels(
    revision_history: list[dict[str, Any]],
    audit_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if not revision_history:
        return []
    feedback_by_id = {
        feedback.get("claim_id"): feedback
        for feedback in audit_payload.get("feedbacks", [])
        if isinstance(feedback, dict)
    }
    updated: list[dict[str, Any]] = []
    for raw_record in revision_history:
        record = RevisionRecord.model_validate(raw_record)
        feedback = feedback_by_id.get(record.claim_id)
        if feedback and feedback.get("label") in {"accepted", "needs_revision", "risky"}:
            record.qa_label_after = feedback["label"]
            record.max_revision_reached = (
                record.revision_round >= 1
                and record.qa_label_after == "needs_revision"
            )
        updated.append(record.model_dump(mode="json"))
    return updated


def node_qa_critic(state: GraphState | dict[str, Any]) -> dict[str, Any]:
    def logic(current: GraphState) -> dict[str, Any]:
        if not _qa_critic_enabled():
            logger.info("qa_critic skipped (ENABLE_QA_CRITIC=0)")
            return {}

        from cs_mvp.agents.qa_critic import audit_run, render_qa_summary_md

        run_dir = Path(_RUNS_DIR) / current.task.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        audit = audit_run(
            current.claims,
            current.evidence,
            current.run_id,
            rescue_outcomes=None,
        )
        audit_payload = audit.model_dump(mode="json")
        revision_history = _apply_qa_after_labels(
            current.revision_history,
            audit_payload,
        )
        _json_file(run_dir / "qa_audit.json", audit_payload)
        (run_dir / "qa_summary.md").write_text(
            render_qa_summary_md(
                audit,
                {claim.claim_id: claim for claim in current.claims},
            ),
            encoding="utf-8",
        )
        return {
            "qa_audit": audit_payload,
            "revision_history": revision_history or current.revision_history,
            "qa_critic_stats": {
                "model": audit.auditor_model,
                "llm_cost_usd": audit.llm_cost_usd,
            },
        }

    return _run_node(state, "qa_critic", logic)


def node_analyst_revise(state: GraphState | dict[str, Any]) -> dict[str, Any]:
    def logic(current: GraphState) -> dict[str, Any]:
        if not _revision_loop_enabled():
            logger.info("analyst_revise skipped (ENABLE_REVISION_LOOP=0)")
            return {}
        if current.revision_round >= 1:
            logger.info("analyst_revise skipped (max revision round reached)")
            return {}

        from cs_mvp.agents.analyst_revise import run_revision_round

        feedbacks = [
            feedback
            for feedback in _qa_feedbacks_from_audit(current.qa_audit)
            if feedback.label == "needs_revision"
        ]
        if not feedbacks:
            return {}

        next_round = current.revision_round + 1
        revised_claims, records, total_cost = run_revision_round(
            current.claims,
            feedbacks,
            current.evidence,
            revision_round=next_round,
        )
        revised_by_id = {claim.claim_id: claim for claim in revised_claims}
        updated_claims = [
            revised_by_id.get(claim.claim_id, claim) for claim in current.claims
        ]
        revision_history = [
            *current.revision_history,
            *[record.model_dump(mode="json") for record in records],
        ]
        return {
            "claims": [claim.model_dump(mode="json") for claim in updated_claims],
            "revision_round": next_round,
            "revision_history": revision_history,
            "analyst_revise_stats": {
                "model": "analyst_revise",
                "llm_cost_usd": total_cost,
                "revised_claims": len(revised_claims),
                "revision_records": len(records),
            },
        }

    return _run_node(state, "analyst_revise", logic)


def node_writer(state: GraphState | dict[str, Any]) -> dict[str, Any]:
    def logic(current: GraphState) -> dict[str, Any]:
        report_md, accepted_claims, risks_claims, discarded_claims, summary_stats = render_report(
            current.task,
            current.run_id,
            current.claims,
            current.evidence,
            node_modes=_active_node_modes(),
        )
        # 统一在 Writer 入库：accepted=True/False 由 verifier 决定，support_score 已写入
        accepted_ids = {claim.claim_id for claim in accepted_claims}
        for claim in accepted_claims:
            db.insert_claim(claim)
        for claim in current.claims:
            if claim.claim_id not in accepted_ids:
                db.insert_claim(claim)  # accepted=False, 保留 dropped 痕迹

        # v0.3.1 Bug 5:把 Executive Summary 的 LLM cost 落到 writer_stats.json,
        # 让 _run_node 能写入 agent_node_runs.cost_usd
        run_dir = Path(_RUNS_DIR) / current.task.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        rescue_payload = summary_stats.pop("_rescue_outcomes_payload", None)
        if rescue_payload is not None:
            _json_file(run_dir / "rescue_outcomes.json", rescue_payload)
        pm_artifacts = render_pm_report_artifacts(
            current.task,
            current.run_id,
            accepted_claims,
            risks_claims=risks_claims,
            evidence=current.evidence,
            qa_audit=current.qa_audit,
            revision_history=current.revision_history,
        )
        _json_file(run_dir / "report_context.json", pm_artifacts["report_context"])
        _json_file(run_dir / "report_plan.json", pm_artifacts["report_plan"])
        _json_file(run_dir / "evidence_digest.json", pm_artifacts["evidence_digest"])
        (run_dir / "report_pm.md").write_text(
            pm_artifacts["report_pm_md"],
            encoding="utf-8",
        )
        (run_dir / "report_pm.html").write_text(
            pm_artifacts["report_pm_html"],
            encoding="utf-8",
        )
        _json_file(run_dir / "report_pm_summary.json", pm_artifacts["report_pm_summary"])
        _json_file(run_dir / "writer_stats.json", summary_stats)
        return {
            "claims": [claim.model_dump(mode="json") for claim in accepted_claims],
            "discarded_claims": [
                claim.model_dump(mode="json") for claim in discarded_claims
            ],
            "report_md": report_md,
            "writer_stats": summary_stats,
        }

    return _run_node(state, "writer", logic)


def _write_run_log(path: Path, node_runs: list[dict[str, Any]]) -> None:
    lines = []
    for row in node_runs:
        lines.append(
            (
                f"{row['node_name']} | start={row['started_at']} | "
                f"end={row['ended_at']} | status={row['status']} | "
                f"latency_ms={row['latency_ms']}"
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_revision_summary(path: Path, records: list[dict[str, Any]]) -> None:
    lines = ["# Revision History", ""]
    if not records:
        lines.append("No revision loop was triggered for this run.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    for raw_record in records:
        record = RevisionRecord.model_validate(raw_record)
        lines.extend(
            [
                f"## {record.claim_id}",
                "",
                f"- Revision round: {record.revision_round}",
                f"- Before label: {record.qa_label_before}",
                f"- After label: {record.qa_label_after}",
                f"- Max revision reached: {record.max_revision_reached}",
                f"- Revision failed: {record.revision_failed}",
                f"- QA reason: {record.qa_reason}",
                f"- Issue tags: {', '.join(record.qa_issue_tags) or '(none)'}",
                f"- Suggested revision: {record.suggested_revision or '(none)'}",
                f"- Revision instruction: {record.revision_instruction or '(none)'}",
                "",
                "Original statement:",
                "",
                record.original_statement,
                "",
                "Revised statement:",
                "",
                record.revised_statement,
                "",
            ]
        )
        if record.revision_explanation:
            lines.extend(["Revision explanation:", "", record.revision_explanation, ""])
        if record.failure_reason:
            lines.extend(["Failure reason:", "", record.failure_reason, ""])

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def node_finalize(state: GraphState | dict[str, Any]) -> dict[str, Any]:
    current = _as_state(state)
    node_run = _new_node_run(current, "finalize")
    db.insert_node_run(node_run)
    logger.info("node finalize started")
    started = time.perf_counter()
    try:
        run_dir = Path(_RUNS_DIR) / current.task.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        report_path = run_dir / "report.md"
        trace_path = run_dir / "trace.json"
        log_path = run_dir / "run.log"
        discarded_path = run_dir / "discarded_claims.json"
        sources_path = run_dir / "sources.json"
        evidence_path = run_dir / "evidence.json"
        extractor_failures_path = run_dir / "extractor_failures.json"

        claims_path = run_dir / "claims.json"
        analyst_failures_path = run_dir / "analyst_failures.json"
        rescue_outcomes_path = run_dir / "rescue_outcomes.json"
        qa_audit_path = run_dir / "qa_audit.json"
        qa_summary_path = run_dir / "qa_summary.md"
        revision_history_path = run_dir / "revision_history.json"
        revision_summary_path = run_dir / "revision_summary.md"
        review_queue_path = run_dir / "review_queue.json"
        semantic_judge_report_path = run_dir / "semantic_judge_report.json"
        report_context_path = run_dir / "report_context.json"
        report_plan_path = run_dir / "report_plan.json"
        evidence_digest_path = run_dir / "evidence_digest.json"
        report_pm_path = run_dir / "report_pm.md"
        report_pm_html_path = run_dir / "report_pm.html"
        report_pm_summary_path = run_dir / "report_pm_summary.json"
        report_style_audit_path = run_dir / "report_style_audit.json"
        report_style_audit_md_path = run_dir / "report_style_audit.md"

        report_path.write_text(current.report_md, encoding="utf-8")
        _json_file(
            discarded_path,
            [claim.model_dump(mode="json") for claim in current.discarded_claims],
        )
        _json_file(sources_path, db.list_sources_for_run(current.run_id))
        _json_file(evidence_path, db.list_evidence_for_run(current.run_id))
        # claims.json 直接从内存 state 导出(claims 由 Writer 阶段经 CitationVerifier 入库,
        # 此处 state.claims 已经包含 support_score)
        _json_file(
            claims_path,
            [claim.model_dump(mode="json") for claim in current.claims],
        )
        if not extractor_failures_path.exists():
            _json_file(extractor_failures_path, [])
        if not analyst_failures_path.exists():
            _json_file(analyst_failures_path, [])
        if current.revision_history:
            revision_payload = {
                "run_id": current.run_id,
                "schema_version": current.task.schema_version,
                "total_revisions": len(current.revision_history),
                "max_revision_rounds": 1,
                "revision_round": current.revision_round,
                "total_revise_cost_usd": round(
                    sum(
                        float(item.get("revise_cost_usd") or 0.0)
                        for item in current.revision_history
                    ),
                    6,
                ),
                "revisions": current.revision_history,
            }
            _json_file(revision_history_path, revision_payload)
            _write_revision_summary(revision_summary_path, current.revision_history)
        report = Report(
            report_id=f"R-{uuid.uuid4().hex}",
            run_id=current.run_id,
            format="md",
            file_path=str(report_path),
        )
        db.insert_report(report)

        output = {
            "report_path": str(report_path),
            "trace_path": str(trace_path),
            "run_log_path": str(log_path),
            "discarded_claims_path": str(discarded_path),
            "sources_path": str(sources_path),
            "evidence_path": str(evidence_path),
            "claims_path": str(claims_path),
            "rescue_outcomes_path": str(rescue_outcomes_path)
            if rescue_outcomes_path.exists()
            else None,
            "qa_audit_path": str(qa_audit_path) if qa_audit_path.exists() else None,
            "qa_summary_path": str(qa_summary_path) if qa_summary_path.exists() else None,
            "revision_history_path": str(revision_history_path)
            if revision_history_path.exists()
            else None,
            "revision_summary_path": str(revision_summary_path)
            if revision_summary_path.exists()
            else None,
            "review_queue_path": str(review_queue_path),
            "semantic_judge_report_path": str(semantic_judge_report_path),
            "report_context_path": str(report_context_path)
            if report_context_path.exists()
            else None,
            "report_plan_path": str(report_plan_path)
            if report_plan_path.exists()
            else None,
            "evidence_digest_path": str(evidence_digest_path)
            if evidence_digest_path.exists()
            else None,
            "report_pm_path": str(report_pm_path) if report_pm_path.exists() else None,
            "report_pm_html_path": str(report_pm_html_path)
            if report_pm_html_path.exists()
            else None,
            "report_pm_summary_path": str(report_pm_summary_path)
            if report_pm_summary_path.exists()
            else None,
            "report_style_audit_path": str(report_style_audit_path),
            "report_style_audit_md_path": str(report_style_audit_md_path),
        }
        latency_ms = int((time.perf_counter() - started) * 1000)
        db.update_node_run(node_run.node_run_id, "completed", _json(output), latency_ms)
        node_runs = db.list_node_runs(current.run_id)
        total_cost = sum(float(row.get("cost_usd") or 0.0) for row in node_runs)
        total_tokens = sum(
            int(row.get("input_tokens") or 0) + int(row.get("output_tokens") or 0)
            for row in node_runs
        )
        db.update_run_status(current.run_id, "completed", total_cost, total_tokens)
        db.update_task_status(current.task.task_id, "completed")

        node_runs = db.list_node_runs(current.run_id)
        trace_payload = {
            "node_modes": _active_node_modes(),
            "gap_fill_round": current.gap_fill_round,
            "revision_round": current.revision_round,
            "revision_history_count": len(current.revision_history),
            "source_quality_evaluated": True,
            "report_quality_evaluated": True,
            "node_runs": node_runs,
        }
        _json_file(trace_path, trace_payload)
        _write_run_log(log_path, node_runs)
        write_summary_artifacts(
            run_dir,
            task=current.task,
            run_id=current.run_id,
            node_runs=node_runs,
        )
        run_summary_path = run_dir / "run_summary.json"
        if run_summary_path.exists():
            run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
            if isinstance(run_summary, dict):
                run_summary["gap_fill_round"] = current.gap_fill_round
                _json_file(run_summary_path, run_summary)
        write_report_style_audit(run_dir)
        write_review_queue(run_dir)
        write_semantic_judge_placeholder(run_dir)
        try:
            export_html_report(run_dir)
        except Exception:
            pass
        try:
            from cs_mvp.agents.ppt_visual_builder import build_ppt_visual

            build_ppt_visual(run_dir)
        except Exception:
            try:
                from cs_mvp.agents.ppt_builder import build_ppt

                build_ppt(run_dir)
            except Exception:
                pass
        logger.info("node finalize completed")
        return output
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        db.update_node_run(node_run.node_run_id, "failed", "{}", latency_ms, str(exc))
        db.update_run_status(current.run_id, "failed", 0.0, 0)
        db.update_task_status(current.task.task_id, "failed", str(exc))
        logger.exception("node finalize failed")
        raise


def build_graph(db_path: str, runs_dir: str = "runs"):
    global _RUNS_DIR
    _RUNS_DIR = runs_dir
    db.configure(db_path)

    builder = StateGraph(GraphState)
    builder.add_node("task_init", node_task_init)
    builder.add_node("collector", node_collector)
    builder.add_node("extractor", node_extractor)
    builder.add_node("analyst", node_analyst)
    if _gap_fill_enabled():
        builder.add_node("gap_fill", node_gap_fill)
    if _qa_critic_enabled():
        builder.add_node("qa_critic", node_qa_critic)
    if _qa_critic_enabled() and _revision_loop_enabled():
        builder.add_node("analyst_revise", node_analyst_revise)
    builder.add_node("writer", node_writer)
    builder.add_node("finalize", node_finalize)

    builder.set_entry_point("task_init")
    builder.add_edge("task_init", "collector")
    builder.add_edge("collector", "extractor")
    builder.add_edge("extractor", "analyst")
    next_after_analyst = _next_after_analyst()
    if _gap_fill_enabled():
        route_map = {"gap_fill": "gap_fill", next_after_analyst: next_after_analyst}
        builder.add_conditional_edges("analyst", _route_after_analyst, route_map)
        builder.add_edge("gap_fill", next_after_analyst)
    else:
        builder.add_edge("analyst", next_after_analyst)
    if _qa_critic_enabled():
        if _revision_loop_enabled():
            builder.add_conditional_edges(
                "qa_critic",
                _route_after_qa_critic,
                {"analyst_revise": "analyst_revise", "writer": "writer"},
            )
            builder.add_edge("analyst_revise", "qa_critic")
        else:
            builder.add_edge("qa_critic", "writer")
    builder.add_edge("writer", "finalize")
    builder.set_finish_point("finalize")

    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return builder.compile(checkpointer=checkpointer)
