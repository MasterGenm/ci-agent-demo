from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from cs_mvp.agents.capability_contracts.writer import WRITER_CAPABILITY
from cs_mvp.models import AnalysisClaim, AnalysisTask, EvidenceItem


REPORT_HARNESS_SCHEMA_VERSION = "1.7.0"
MAX_DIGEST_EVIDENCE_PER_CLAIM = 3
MAX_TOP_FINDINGS = 5
MAX_RECOMMENDATIONS = 5

REPORT_SECTIONS = [
    {
        "id": "one_page_summary",
        "title": "一页结论",
        "purpose": "快速说明最重要的 3-5 条结论。",
        "source": "top_findings",
    },
    {
        "id": "competitor_matrix",
        "title": "竞品对比矩阵",
        "purpose": "把定位、能力、定价、用户和风险放到同一张表里。",
        "source": "competitor_matrix",
    },
    {
        "id": "top_findings",
        "title": "Top Findings",
        "purpose": "用证据支撑的短段落说明核心发现。",
        "source": "accepted_claims",
    },
    {
        "id": "competitor_profiles",
        "title": "各竞品画像",
        "purpose": "给每个竞品一个可扫读的产品画像。",
        "source": "competitor_matrix",
    },
    {
        "id": "product_opportunities",
        "title": "产品机会点",
        "purpose": "把发现翻译成可验证的产品动作。",
        "source": "recommendations",
    },
    {
        "id": "risks_and_unknowns",
        "title": "风险与不确定性",
        "purpose": "保留低置信、低召回和待人工复核项。",
        "source": "risks",
    },
    {
        "id": "evidence_digest",
        "title": "Evidence Digest",
        "purpose": "只列支撑 PM report 的关键证据,完整证据仍在 evidence.json。",
        "source": "evidence_digest",
    },
]


def _clip(value: str | None, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _claim_score(claim: AnalysisClaim) -> float:
    if claim.support_score is not None:
        return float(claim.support_score)
    if claim.confidence is not None:
        return float(claim.confidence)
    return 0.0


def _citation_ids(evidence_ids: list[str]) -> str:
    return "".join(f"[{evidence_id}]" for evidence_id in evidence_ids)


def _main_claims(claims: list[AnalysisClaim]) -> list[AnalysisClaim]:
    return [claim for claim in claims if bool(getattr(claim, "accepted", True))]


def _sorted_claims(claims: list[AnalysisClaim]) -> list[AnalysisClaim]:
    return sorted(
        claims,
        key=lambda claim: (
            _claim_score(claim),
            len(claim.evidence_ids),
            claim.statement,
        ),
        reverse=True,
    )


def _best_claim_for_dimension(
    claims: list[AnalysisClaim],
    dimension: str,
) -> AnalysisClaim | None:
    candidates = [claim for claim in claims if claim.dimension == dimension]
    return _sorted_claims(candidates)[0] if candidates else None


def _claim_brief(claim: AnalysisClaim | None) -> str:
    if claim is None:
        return "待补充"
    return _clip(claim.statement, 120)


def _claim_evidence_ids(claim: AnalysisClaim | None) -> list[str]:
    return list(claim.evidence_ids) if claim is not None else []


def _writer_capabilities() -> list[dict[str, Any]]:
    return [
        {
            "name": skill.name,
            "purpose": skill.purpose,
            "quality_checks": list(skill.quality_checks),
            "observability_signals": list(skill.observability_signals),
        }
        for skill in WRITER_CAPABILITY.skills
    ]


def _qa_feedback_count(qa_audit: dict[str, Any] | None) -> int:
    if not isinstance(qa_audit, dict):
        return 0
    feedbacks = qa_audit.get("feedbacks")
    return len(feedbacks) if isinstance(feedbacks, list) else 0


def build_report_context(
    *,
    task: AnalysisTask,
    run_id: str,
    accepted_claims: list[AnalysisClaim],
    risks_claims: list[AnalysisClaim],
    evidence: list[EvidenceItem],
    qa_audit: dict[str, Any] | None = None,
    revision_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    main_claims = _main_claims(accepted_claims)
    return {
        "schema_version": REPORT_HARNESS_SCHEMA_VERSION,
        "task_id": task.task_id,
        "run_id": run_id,
        "target_audience": ["pm", "interviewer", "evaluator"],
        "analysis_goal": task.query,
        "competitors": [competitor.name for competitor in task.competitors],
        "writer_capabilities": _writer_capabilities(),
        "inputs": {
            "accepted_claim_count": len(main_claims),
            "risk_claim_count": len(risks_claims),
            "evidence_count": len(evidence),
            "qa_feedback_count": _qa_feedback_count(qa_audit),
            "revision_count": len(revision_history or []),
        },
        "constraints": [
            "Do not invent new evidence.",
            "Keep evidence ids attached to findings and recommendations.",
            "Keep report.md as the audit artifact; report_pm.md is a reader-facing summary.",
        ],
    }


def build_evidence_digest(
    *,
    task: AnalysisTask,
    claims: list[AnalysisClaim],
    evidence: list[EvidenceItem],
    max_evidence_per_claim: int = MAX_DIGEST_EVIDENCE_PER_CLAIM,
) -> dict[str, Any]:
    evidence_map = {item.evidence_id: item for item in evidence}
    items: list[dict[str, Any]] = []
    for claim in _sorted_claims(_main_claims(claims)):
        digest_evidence = []
        for evidence_id in claim.evidence_ids[:max_evidence_per_claim]:
            item = evidence_map.get(evidence_id)
            if item is None:
                continue
            digest_evidence.append(
                {
                    "evidence_id": item.evidence_id,
                    "source_id": item.source_id,
                    "source_title": item.source_id,
                    "quote": _clip(item.quote, 260),
                    "why_it_matters": (
                        f"支撑 {claim.dimension} 维度判断: "
                        f"{_clip(claim.statement, 90)}"
                    ),
                }
            )
        items.append(
            {
                "claim_id": claim.claim_id,
                "competitor_name": claim.competitor_name,
                "dimension": claim.dimension,
                "statement": claim.statement,
                "support_score": claim.support_score,
                "digest_evidence": digest_evidence,
            }
        )
    return {
        "schema_version": REPORT_HARNESS_SCHEMA_VERSION,
        "task_id": task.task_id,
        "items": items,
    }


def build_competitor_matrix(
    *,
    task: AnalysisTask,
    accepted_claims: list[AnalysisClaim],
    risks_claims: list[AnalysisClaim],
) -> list[dict[str, Any]]:
    main_claims = _main_claims(accepted_claims)
    rows: list[dict[str, Any]] = []
    for competitor in task.competitors:
        name = competitor.name
        claims = [claim for claim in main_claims if claim.competitor_name == name]
        risks = [claim for claim in risks_claims if claim.competitor_name == name]
        features = _best_claim_for_dimension(claims, "features")
        pricing = _best_claim_for_dimension(claims, "pricing")
        positioning = _best_claim_for_dimension(claims, "positioning")
        users = _best_claim_for_dimension(claims, "target_users")
        strategic = _best_claim_for_dimension(claims, "strategic_implications")
        row_evidence_ids = []
        for claim in [features, pricing, positioning, users, strategic]:
            for evidence_id in _claim_evidence_ids(claim):
                if evidence_id not in row_evidence_ids:
                    row_evidence_ids.append(evidence_id)
        rows.append(
            {
                "competitor_name": name,
                "positioning": _claim_brief(positioning),
                "core_capabilities": _claim_brief(features),
                "pricing_or_business_model": _claim_brief(pricing),
                "target_users": _claim_brief(users),
                "strategic_signal": _claim_brief(strategic),
                "visible_risk": _clip(risks[0].statement, 120)
                if risks
                else "未发现高优先级风险项",
                "evidence_ids": row_evidence_ids[:6],
            }
        )
    return rows


def build_top_findings(
    *,
    accepted_claims: list[AnalysisClaim],
    limit: int = MAX_TOP_FINDINGS,
) -> list[dict[str, Any]]:
    findings = []
    for index, claim in enumerate(_sorted_claims(_main_claims(accepted_claims))[:limit], start=1):
        competitor = claim.competitor_name or "跨竞品"
        evidence_ids = list(claim.evidence_ids)
        findings.append(
            {
                "finding_id": f"F-{index:02d}",
                "competitor_name": competitor,
                "dimension": claim.dimension,
                "statement": claim.statement,
                "evidence_ids": evidence_ids,
                "citation_text": _citation_ids(evidence_ids),
                "support_score": claim.support_score,
                "needs_validation": not bool(evidence_ids),
            }
        )
    return findings


def build_action_recommendations(
    *,
    findings: list[dict[str, Any]],
    limit: int = MAX_RECOMMENDATIONS,
) -> list[dict[str, Any]]:
    recommendations = []
    for index, finding in enumerate(findings[:limit], start=1):
        dimension = str(finding.get("dimension") or "other")
        competitor = str(finding.get("competitor_name") or "竞品")
        statement = _clip(str(finding.get("statement") or ""), 110)
        evidence_ids = list(finding.get("evidence_ids") or [])
        if dimension == "pricing":
            action = f"复核 {competitor} 的定价与套餐边界,判断我方是否需要调整打包方式。"
        elif dimension == "features":
            action = f"围绕 {competitor} 的能力点建立功能对照表,评估是否进入近期路线图。"
        elif dimension == "positioning":
            action = f"对照 {competitor} 的定位表达,检查我方首页和销售话术是否足够清晰。"
        elif dimension == "target_users":
            action = f"验证 {competitor} 覆盖的人群是否与我方目标用户重叠。"
        else:
            action = f"把 {competitor} 的这条观察纳入下一轮产品访谈或资料复核。"
        recommendations.append(
            {
                "recommendation_id": f"R-{index:02d}",
                "action": action,
                "rationale": statement,
                "evidence_ids": evidence_ids,
                "citation_text": _citation_ids(evidence_ids),
                "needs_validation": not bool(evidence_ids),
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "recommendation_id": "R-01",
                "action": "补充更多公开信息采集后再进入产品决策。",
                "rationale": "当前没有足够的 accepted claim 支撑 PM-readable 机会判断。",
                "evidence_ids": [],
                "citation_text": "",
                "needs_validation": True,
            }
        )
    return recommendations


def build_competitor_profiles(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles = []
    for row in matrix:
        profiles.append(
            {
                "competitor_name": row["competitor_name"],
                "summary": (
                    f"{row['competitor_name']} 当前可见定位是「{row['positioning']}」。"
                    f"核心能力线索是「{row['core_capabilities']}」。"
                ),
                "business_signal": row["pricing_or_business_model"],
                "risk": row["visible_risk"],
                "evidence_ids": row["evidence_ids"],
                "citation_text": _citation_ids(row["evidence_ids"]),
            }
        )
    return profiles


def build_report_plan(
    *,
    task: AnalysisTask,
    top_findings: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    evidence_digest: dict[str, Any],
) -> dict[str, Any]:
    sections = []
    for section in REPORT_SECTIONS:
        item: dict[str, Any] = dict(section)
        if section["id"] == "top_findings":
            item["item_count"] = len(top_findings)
        elif section["id"] == "product_opportunities":
            item["item_count"] = len(recommendations)
        elif section["id"] == "evidence_digest":
            item["item_count"] = len(evidence_digest.get("items") or [])
        elif section["id"] == "competitor_matrix":
            item["item_count"] = len(task.competitors)
        else:
            item["item_count"] = None
        sections.append(item)
    return {
        "schema_version": REPORT_HARNESS_SCHEMA_VERSION,
        "task_id": task.task_id,
        "sections": sections,
    }


def build_pm_report_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": REPORT_HARNESS_SCHEMA_VERSION,
        "task_id": payload["task_id"],
        "run_id": payload["run_id"],
        "report_type": "pm",
        "section_count": len(payload["report_plan"]["sections"]),
        "competitor_count": len(payload["competitors"]),
        "top_finding_count": len(payload["top_findings"]),
        "recommendation_count": len(payload["recommendations"]),
        "evidence_digest_count": len(payload["evidence_digest"]["items"]),
        "used_writer_skills": [
            item["name"] for item in payload["report_context"]["writer_capabilities"]
        ],
        "files": {
            "report_pm_md": "report_pm.md",
            "report_pm_html": "report_pm.html",
        },
    }


def build_pm_report_payload(
    *,
    task: AnalysisTask,
    run_id: str,
    accepted_claims: list[AnalysisClaim],
    risks_claims: list[AnalysisClaim],
    evidence: list[EvidenceItem],
    qa_audit: dict[str, Any] | None = None,
    revision_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = build_report_context(
        task=task,
        run_id=run_id,
        accepted_claims=accepted_claims,
        risks_claims=risks_claims,
        evidence=evidence,
        qa_audit=qa_audit,
        revision_history=revision_history,
    )
    evidence_digest = build_evidence_digest(
        task=task,
        claims=accepted_claims,
        evidence=evidence,
    )
    matrix = build_competitor_matrix(
        task=task,
        accepted_claims=accepted_claims,
        risks_claims=risks_claims,
    )
    top_findings = build_top_findings(accepted_claims=accepted_claims)
    recommendations = build_action_recommendations(findings=top_findings)
    profiles = build_competitor_profiles(matrix)
    report_plan = build_report_plan(
        task=task,
        top_findings=top_findings,
        recommendations=recommendations,
        evidence_digest=evidence_digest,
    )
    return {
        "schema_version": REPORT_HARNESS_SCHEMA_VERSION,
        "task_id": task.task_id,
        "run_id": run_id,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "query": task.query,
        "competitors": [competitor.name for competitor in task.competitors],
        "report_context": context,
        "report_plan": report_plan,
        "evidence_digest": evidence_digest,
        "competitor_matrix": matrix,
        "top_findings": top_findings,
        "competitor_profiles": profiles,
        "recommendations": recommendations,
        "risks": [
            {
                "claim_id": claim.claim_id,
                "competitor_name": claim.competitor_name,
                "dimension": claim.dimension,
                "statement": claim.statement,
                "support_score": claim.support_score,
                "evidence_ids": list(claim.evidence_ids),
                "citation_text": _citation_ids(claim.evidence_ids),
            }
            for claim in risks_claims
        ],
    }


def render_pm_report_html(markdown_text: str, *, task_id: str) -> str:
    escaped = html.escape(markdown_text)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>cs-mvp PM report {html.escape(task_id)}</title>
  <style>
    body {{ margin: 0; background: #f8fafc; color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ max-width: 1040px; margin: 0 auto; padding: 32px 20px 64px; }}
    article {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 28px; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08); }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; font-family: inherit; line-height: 1.7; font-size: 15px; }}
  </style>
</head>
<body>
<main>
  <article><pre>{escaped}</pre></article>
</main>
</body>
</html>
"""
