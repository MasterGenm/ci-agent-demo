from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from cs_mvp.models import SCHEMA_VERSION


ALLOWED_ARTIFACTS: dict[str, str] = {
    "claims": "claims.json",
    "evidence": "evidence.json",
    "sources": "sources.json",
    "discarded_claims": "discarded_claims.json",
    "review_queue": "review_queue.json",
    "trace": "trace.json",
    "qa_audit": "qa_audit.json",
    "revision_history": "revision_history.json",
    "rescue_outcomes": "rescue_outcomes.json",
    "semantic_judge_report": "semantic_judge_report.json",
    "run_summary": "run_summary.json",
    "node_summary": "node_summary.json",
    "cost_summary": "cost_summary.json",
    "claim_summary": "claim_summary.json",
    "source_summary": "source_summary.json",
    "evidence_summary": "evidence_summary.json",
    "report_quality": "report_quality.json",
    "report_context": "report_context.json",
    "report_plan": "report_plan.json",
    "evidence_digest": "evidence_digest.json",
    "report_pm_summary": "report_pm_summary.json",
    "report_style_audit": "report_style_audit.json",
}

_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_CANONICAL_NODES = ["task_init", "collector", "extractor", "analyst", "writer", "finalize"]
_QA_CANONICAL_NODES = [
    "task_init",
    "collector",
    "extractor",
    "analyst",
    "qa_critic",
    "writer",
    "finalize",
]
_REVISION_CANONICAL_NODES = [
    "task_init",
    "collector",
    "extractor",
    "analyst",
    "qa_critic",
    "analyst_revise",
    "qa_critic",
    "writer",
    "finalize",
]
_NODE_LABELS = {
    "task_init": "Task Init",
    "collector": "Collector",
    "extractor": "Extractor",
    "analyst": "Analyst",
    "qa_critic": "QA Critic",
    "analyst_revise": "Analyst Revise",
    "writer": "Writer",
    "finalize": "Finalize",
}


def _role_card_for_node(node_name: str) -> dict[str, str] | None:
    try:
        from cs_mvp.agents.role_cards import ROLE_CARDS
    except Exception:
        return None
    card = ROLE_CARDS.get(node_name)
    if card is None:
        return None
    return card.short_metadata()


def _capability_for_node(node_name: str) -> dict[str, Any] | None:
    try:
        from cs_mvp.agents.capability_contracts import CAPABILITY_CONTRACTS
    except Exception:
        return None
    contract = CAPABILITY_CONTRACTS.get(node_name)
    if contract is None:
        return None
    return contract.short_metadata()


_SCHEMA_VIEW: list[dict[str, Any]] = [
    {
        "name": "SourceRecord",
        "produced_by": "Collector",
        "fields": [
            {"name": "source_id", "type": "str", "required": True},
            {"name": "run_id", "type": "str", "required": True},
            {"name": "competitor_name", "type": "str", "required": True},
            {"name": "url", "type": "str", "required": True},
            {"name": "source_type", "type": "official_site | pricing | docs | blog | news | other", "required": True},
            {"name": "retrieved_at", "type": "datetime", "required": True},
            {"name": "reliability_score", "type": "float", "required": True},
            {"name": "fetch_status", "type": "fetched | failed | skipped | empty", "required": True},
        ],
    },
    {
        "name": "EvidenceItem",
        "produced_by": "Extractor",
        "fields": [
            {"name": "evidence_id", "type": "str", "required": True},
            {"name": "source_id", "type": "str", "required": True},
            {"name": "competitor_name", "type": "str", "required": True},
            {"name": "claim_type", "type": "feature | pricing | positioning | metric | other", "required": True},
            {"name": "quote", "type": "str", "required": True},
            {"name": "normalized_fact", "type": "str | None", "required": False},
            {"name": "confidence", "type": "float | None", "required": False},
        ],
    },
    {
        "name": "AnalysisClaim",
        "produced_by": "Analyst / Analyst Revise",
        "fields": [
            {"name": "claim_id", "type": "str", "required": True},
            {"name": "run_id", "type": "str", "required": True},
            {"name": "competitor_name", "type": "str | None", "required": False},
            {"name": "dimension", "type": "features | pricing | positioning | swot | target_users | strategic_implications", "required": True},
            {"name": "statement", "type": "str", "required": True},
            {"name": "evidence_ids", "type": "list[str]", "required": True},
            {"name": "support_score", "type": "float | None", "required": False},
            {"name": "accepted", "type": "bool", "required": True},
        ],
    },
    {
        "name": "QAFeedback",
        "produced_by": "QA Critic",
        "fields": [
            {"name": "claim_id", "type": "str", "required": True},
            {"name": "label", "type": "accepted | needs_revision | risky", "required": True},
            {"name": "reason", "type": "str", "required": True},
            {"name": "issue_tags", "type": "list[str]", "required": True},
            {"name": "suggested_revision", "type": "str | None", "required": False},
            {"name": "revision_instruction", "type": "str | None", "required": False},
        ],
    },
    {
        "name": "RevisionRecord",
        "produced_by": "Analyst Revise",
        "fields": [
            {"name": "claim_id", "type": "str", "required": True},
            {"name": "revision_round", "type": "int", "required": True},
            {"name": "original_statement", "type": "str", "required": True},
            {"name": "revised_statement", "type": "str", "required": True},
            {"name": "qa_label_before", "type": "needs_revision | risky", "required": True},
            {"name": "qa_label_after", "type": "accepted | needs_revision | risky", "required": True},
            {"name": "revision_failed", "type": "bool", "required": True},
        ],
    },
]


class ArtifactNotFound(FileNotFoundError):
    pass


class UnsafeArtifactPath(ValueError):
    pass


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _safe_run_dir(runs_dir: Path, task_id: str) -> Path:
    if not _SAFE_TASK_ID.fullmatch(task_id):
        raise UnsafeArtifactPath(f"unsafe task_id: {task_id}")
    root = Path(runs_dir).resolve()
    run_dir = (root / task_id).resolve()
    if root != run_dir and root not in run_dir.parents:
        raise UnsafeArtifactPath(f"unsafe task path: {task_id}")
    return run_dir


def require_run_dir(runs_dir: Path, task_id: str) -> Path:
    run_dir = _safe_run_dir(runs_dir, task_id)
    if not run_dir.exists() or not run_dir.is_dir():
        raise ArtifactNotFound(task_id)
    return run_dir


def _artifact_path(runs_dir: Path, task_id: str, name: str) -> Path:
    filename = ALLOWED_ARTIFACTS.get(name)
    if filename is None:
        raise UnsafeArtifactPath(f"artifact not allowed: {name}")
    return require_run_dir(runs_dir, task_id) / filename


def read_artifact(runs_dir: Path, task_id: str, name: str) -> Any:
    path = _artifact_path(runs_dir, task_id, name)
    if not path.exists():
        raise ArtifactNotFound(name)
    return _load_json(path, {})


def _count_json_list(run_dir: Path, filename: str) -> int:
    payload = _load_json(run_dir / filename, [])
    return len(payload) if isinstance(payload, list) else 0


def _run_card(run_dir: Path) -> dict[str, Any]:
    summary = _load_json(run_dir / "run_summary.json", {})
    trace = _load_json(run_dir / "trace.json", {})
    qa_audit = _load_json(run_dir / "qa_audit.json", {})
    node_runs = trace.get("node_runs") if isinstance(trace, dict) else []
    status = summary.get("status") if isinstance(summary, dict) else None
    if not status and isinstance(node_runs, list) and node_runs:
        statuses = {str(item.get("status")) for item in node_runs if isinstance(item, dict)}
        status = "failed" if "failed" in statuses else "completed"
    return {
        "task_id": run_dir.name,
        "run_id": summary.get("run_id") if isinstance(summary, dict) else None,
        "query": summary.get("query") if isinstance(summary, dict) else "",
        "competitors": summary.get("competitors") if isinstance(summary, dict) else [],
        "status": status or "unknown",
        "completed_at": summary.get("completed_at") if isinstance(summary, dict) else None,
        "duration_seconds": summary.get("duration_seconds") if isinstance(summary, dict) else None,
        "claims_count": _count_json_list(run_dir, "claims.json"),
        "evidence_count": _count_json_list(run_dir, "evidence.json"),
        "qa_enabled": bool(qa_audit),
    }


def list_runs(runs_dir: Path) -> list[dict[str, Any]]:
    root = Path(runs_dir)
    if not root.exists():
        return []
    runs = [
        _run_card(path)
        for path in root.iterdir()
        if path.is_dir()
        and any((path / marker).exists() for marker in ("run_summary.json", "trace.json", "claims.json", "report.md"))
    ]
    return sorted(
        runs,
        key=lambda item: (
            1 if item.get("completed_at") else 0,
            str(item.get("completed_at") or item.get("task_id") or ""),
        ),
        reverse=True,
    )


def get_schema_view() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "models": _SCHEMA_VIEW,
        "industry_presets_future": [
            {
                "name": "SaaS",
                "dimensions": [
                    "features",
                    "pricing",
                    "positioning",
                    "swot",
                    "target_users",
                    "strategic_implications",
                ],
            },
            {
                "name": "Medical (future)",
                "dimensions": [
                    "regulatory_status",
                    "efficacy",
                    "safety",
                    "indication",
                    "reimbursement",
                ],
            },
            {
                "name": "Financial (future)",
                "dimensions": [
                    "product_type",
                    "fees",
                    "regulatory",
                    "risk_profile",
                    "customer_segment",
                ],
            },
        ],
        "doc_link": "/docs/SCHEMA.md",
    }


def get_role_cards_view() -> dict[str, Any]:
    try:
        from cs_mvp.agents.role_cards import AGENT_ROLE_ORDER, ROLE_CARDS
    except Exception:
        return {"agents": []}
    return {
        "agents": [
            ROLE_CARDS[name].model_dump(mode="json")
            for name in AGENT_ROLE_ORDER
            if name in ROLE_CARDS
        ]
    }


def get_run_metadata(runs_dir: Path, task_id: str) -> dict[str, Any]:
    return _run_card(require_run_dir(runs_dir, task_id))


def get_qa_audit(runs_dir: Path, task_id: str) -> dict[str, Any] | None:
    path = require_run_dir(runs_dir, task_id) / "qa_audit.json"
    if not path.exists():
        return None
    payload = _load_json(path, {})
    return payload if isinstance(payload, dict) else None


def get_revision_history(runs_dir: Path, task_id: str) -> dict[str, Any]:
    path = require_run_dir(runs_dir, task_id) / "revision_history.json"
    if not path.exists():
        return {"enabled": False, "history": None, "revisions": []}
    payload = _load_json(path, {})
    if not isinstance(payload, dict):
        return {"enabled": False, "history": None, "revisions": []}
    revisions = payload.get("revisions")
    if not isinstance(revisions, list):
        revisions = []
    return {
        "enabled": bool(revisions),
        "history": payload,
        "revisions": revisions,
        "total_revisions": payload.get("total_revisions") or len(revisions),
        "revision_round": payload.get("revision_round"),
        "max_revision_rounds": payload.get("max_revision_rounds"),
        "total_revise_cost_usd": payload.get("total_revise_cost_usd") or 0.0,
    }


def get_trace(runs_dir: Path, task_id: str) -> dict[str, Any]:
    payload = _load_json(require_run_dir(runs_dir, task_id) / "trace.json", {})
    return payload if isinstance(payload, dict) else {"node_runs": []}


def _node_runs(trace: dict[str, Any]) -> list[dict[str, Any]]:
    node_runs = trace.get("node_runs") if isinstance(trace, dict) else []
    return [
        item
        for item in node_runs or []
        if isinstance(item, dict) and item.get("node_name")
    ]


def _has_revision_loop(trace: dict[str, Any], run_dir: Path) -> bool:
    if any(str(item.get("node_name")) == "analyst_revise" for item in _node_runs(trace)):
        return True
    history = _load_json(run_dir / "revision_history.json", {})
    if not isinstance(history, dict):
        return False
    revisions = history.get("revisions")
    return bool(history.get("total_revisions") or (isinstance(revisions, list) and revisions))


def _node_order(trace: dict[str, Any], run_dir: Path) -> list[str]:
    names = [
        str(item.get("node_name"))
        for item in _node_runs(trace)
    ]
    if _has_revision_loop(trace, run_dir):
        return _REVISION_CANONICAL_NODES
    if "qa_critic" in names:
        return _QA_CANONICAL_NODES
    node_modes = trace.get("node_modes") if isinstance(trace, dict) else {}
    if isinstance(node_modes, dict) and "qa_critic" in node_modes:
        return _QA_CANONICAL_NODES
    if not names and (run_dir / "qa_audit.json").exists():
        return _QA_CANONICAL_NODES
    if not names and not trace:
        return _QA_CANONICAL_NODES
    return _CANONICAL_NODES


def get_dag_status(runs_dir: Path, task_id: str) -> dict[str, Any]:
    run_dir = require_run_dir(runs_dir, task_id)
    trace = get_trace(runs_dir, task_id)
    recorded_nodes = _node_runs(trace)
    rows = recorded_nodes or [{"node_name": name} for name in _node_order(trace, run_dir)]
    has_revision_loop = _has_revision_loop(trace, run_dir)
    nodes = []
    for index, row in enumerate(rows, start=1):
        name = str(row.get("node_name"))
        nodes.append(
            {
                "id": f"N{index}",
                "name": name,
                "label": _NODE_LABELS.get(name, name),
                "status": row.get("status") or "pending",
                "latency_ms": row.get("latency_ms"),
                "cost_usd": row.get("cost_usd"),
                "llm_model": row.get("llm_model"),
                "role_card": _role_card_for_node(name) or {},
                "capability": _capability_for_node(name) or {},
            }
        )
    return {"task_id": task_id, "nodes": nodes, "has_revision_loop": has_revision_loop}


def get_run_status_summary(runs_dir: Path, task_id: str) -> dict[str, Any]:
    """Return a compact run status view for dashboard polling."""
    run_dir = require_run_dir(runs_dir, task_id)
    trace = get_trace(runs_dir, task_id)
    node_runs = _node_runs(trace)

    completed = [
        row
        for row in node_runs
        if str(row.get("status") or "").lower() == "completed"
    ]
    failed = [
        row
        for row in node_runs
        if str(row.get("status") or "").lower() == "failed"
    ]
    running = [
        row
        for row in node_runs
        if str(row.get("status") or "").lower() == "running"
    ]

    if failed:
        status = "failed"
    elif any(str(row.get("node_name")) == "finalize" for row in completed):
        status = "completed"
    elif node_runs:
        status = "running"
    else:
        status = "pending"

    node_order = _node_order(trace, run_dir)
    total_nodes = max(len(node_order), len(node_runs), 1)
    completed_nodes = len(completed)
    current_node = None
    if running:
        current_node = str(running[0].get("node_name"))
    elif status in {"running", "pending"}:
        current_node = node_order[min(completed_nodes, total_nodes - 1)]

    total_cost = sum(float(row.get("cost_usd") or 0.0) for row in node_runs)
    total_latency = sum(int(row.get("latency_ms") or 0) for row in node_runs)
    progress = round(min(100.0, (completed_nodes / total_nodes) * 100), 1)

    return {
        "task_id": task_id,
        "status": status,
        "current_node": current_node,
        "completed_nodes": completed_nodes,
        "total_nodes": total_nodes,
        "progress_percent": progress,
        "total_cost_usd": total_cost,
        "total_latency_ms": total_latency,
    }


def get_sources_index(runs_dir: Path, task_id: str) -> dict[str, dict[str, Any]]:
    sources = _load_json(require_run_dir(runs_dir, task_id) / "sources.json", [])
    if not isinstance(sources, list):
        return {}
    return {
        str(item.get("source_id")): item
        for item in sources
        if isinstance(item, dict) and item.get("source_id")
    }


def get_evidence(runs_dir: Path, task_id: str) -> dict[str, Any]:
    run_dir = require_run_dir(runs_dir, task_id)
    evidence = _load_json(run_dir / "evidence.json", [])
    if not isinstance(evidence, list):
        evidence = []
    sources_by_id = get_sources_index(runs_dir, task_id)
    enriched = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        source = sources_by_id.get(str(item.get("source_id"))) or {}
        enriched.append(
            {
                **item,
                "source_url": source.get("url"),
                "source_title": source.get("title"),
            }
        )
    by_competitor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in enriched:
        by_competitor[str(item.get("competitor_name") or "Unknown")].append(item)
    return {
        "items": enriched,
        "by_competitor": dict(sorted(by_competitor.items())),
        "source_count": len(sources_by_id),
    }


def get_claims_index(runs_dir: Path, task_id: str) -> dict[str, dict[str, Any]]:
    run_dir = require_run_dir(runs_dir, task_id)
    index: dict[str, dict[str, Any]] = {}
    for filename in ("discarded_claims.json", "claims.json"):
        claims = _load_json(run_dir / filename, [])
        if not isinstance(claims, list):
            continue
        for item in claims:
            if isinstance(item, dict) and item.get("claim_id"):
                index[str(item["claim_id"])] = item
    return index


def get_qa_feedback_view(runs_dir: Path, task_id: str) -> dict[str, Any]:
    audit = get_qa_audit(runs_dir, task_id)
    if audit is None:
        return {"enabled": False, "audit": None, "feedbacks": []}
    claims = get_claims_index(runs_dir, task_id)
    evidence = get_evidence(runs_dir, task_id)
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in evidence["items"]
        if item.get("evidence_id")
    }
    feedbacks = []
    for item in audit.get("feedbacks") or []:
        if not isinstance(item, dict):
            continue
        claim = claims.get(str(item.get("claim_id"))) or {}
        related_evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in claim.get("evidence_ids") or []
            if evidence_id in evidence_by_id
        ]
        feedbacks.append(
            {
                **item,
                "claim": claim,
                "evidence": related_evidence,
            }
        )
    return {"enabled": True, "audit": audit, "feedbacks": feedbacks}


def get_report_quality_view(runs_dir: Path, task_id: str) -> dict[str, Any]:
    run_dir = require_run_dir(runs_dir, task_id)
    path = run_dir / "report_style_audit.json"
    if not path.exists():
        return {"enabled": False}
    payload = _load_json(path, {})
    if not isinstance(payload, dict):
        return {"enabled": False}

    section_coverage = payload.get("section_coverage")
    if not isinstance(section_coverage, dict):
        section_coverage = {}
    actionability = payload.get("actionability")
    if not isinstance(actionability, dict):
        actionability = {}
    evidence_density = payload.get("evidence_density")
    if not isinstance(evidence_density, dict):
        evidence_density = {}
    score = payload.get("score")
    if not isinstance(score, dict):
        score = {}
    tone_flags = payload.get("ai_tone_flags")
    if not isinstance(tone_flags, list):
        tone_flags = []

    covered_sections = sum(1 for value in section_coverage.values() if value)
    total_sections = len(section_coverage)
    return {
        "enabled": True,
        "overall_score": score.get("overall_score", 0.0),
        "covered_sections": covered_sections,
        "total_sections": total_sections,
        "recommendations_with_evidence": actionability.get(
            "recommendations_with_evidence",
            0,
        ),
        "recommendation_count": actionability.get("recommendation_count", 0),
        "citation_count": evidence_density.get("citation_count", 0),
        "ai_tone_flags_count": sum(
            int(item.get("count") or 0)
            for item in tone_flags
            if isinstance(item, dict)
        ),
    }


def report_html_path(runs_dir: Path, task_id: str) -> Path | None:
    run_dir = require_run_dir(runs_dir, task_id)
    html_path = run_dir / "report.html"
    if html_path.exists():
        return html_path
    md_path = run_dir / "report.md"
    return md_path if md_path.exists() else None


def report_pm_html_path(runs_dir: Path, task_id: str) -> Path | None:
    run_dir = require_run_dir(runs_dir, task_id)
    html_path = run_dir / "report_pm.html"
    if html_path.exists():
        return html_path
    md_path = run_dir / "report_pm.md"
    return md_path if md_path.exists() else None


def report_pptx_path(runs_dir: Path, task_id: str) -> Path | None:
    run_dir = require_run_dir(runs_dir, task_id)
    pptx_path = run_dir / "report.pptx"
    return pptx_path if pptx_path.exists() else None


def report_style_audit_md_path(runs_dir: Path, task_id: str) -> Path | None:
    run_dir = require_run_dir(runs_dir, task_id)
    md_path = run_dir / "report_style_audit.md"
    return md_path if md_path.exists() else None
