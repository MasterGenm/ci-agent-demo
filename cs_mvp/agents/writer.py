from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cs_mvp.agents.writer_skills import (
    build_pm_report_payload,
    build_pm_report_summary,
    render_pm_report_html,
)
from cs_mvp.models import AnalysisClaim, AnalysisTask, EvidenceItem
from cs_mvp.tools.citation import verify_claim
from cs_mvp.tools.interpretive_guard import GUARDED_DIMENSIONS, scan_interpretive_risk
from cs_mvp.tools.rescue import RescueOutcome, rescue_uncertain_with_llm

logger = logging.getLogger(__name__)

_RISKS_MAX_PER_REPORT = 8  # Risks 章节硬上限,避免倒挂
_RISKS_MIN_SCORE_FLOOR = 0.30  # 低于此分的不再单列(过于不可信)
_LOW_RECALL_EVIDENCE_THRESHOLD = 3  # 单竞品 evidence ≤此值视为召回失败


def format_citation_ids(evidence_ids: list[str]) -> str:
    return "".join(f"[{evidence_id}]" for evidence_id in evidence_ids)


def render_report(
    task: AnalysisTask,
    run_id: str,
    claims: list[AnalysisClaim],
    evidence: list[EvidenceItem],
    node_modes: dict[str, str] | None = None,
) -> tuple[str, list[AnalysisClaim], list[AnalysisClaim], list[object], dict[str, Any]]:
    """M4: 报告组织优化。

    塔罗第五轮(2026-05-17)结论:
    - cross claim 全部进"跨竞品对比"章节(不受 0.6 阈值限制)——星币四逆位
    - Risks 只留 single-competitor uncertain/fail,且总数控制 ≤主章节
    - Executive Summary 由 LLM 生成,失败 fallback 到模板——星币侍从正位
    """
    evidence_map = {item.evidence_id: item for item in evidence}

    # Phase 1: 三态分类 single-competitor claim
    accepted_claims: list[AnalysisClaim] = []
    uncertain_claims: list[AnalysisClaim] = []
    discarded_claims: list[object] = []
    raw_cross: list[AnalysisClaim] = []

    for claim in claims:
        # cross claim 跳过 verifier 阈值裁决:塔罗结论"cross 是跨证据综合观察,
        # 不适合用单条关键词 score 粗暴裁决"
        if claim.competitor_name is None:
            # 仍跑一次 verifier 算 support_score 用于展示,但不据此分类
            accepted, discarded = verify_claim(claim, evidence_map)
            if accepted is not None:
                raw_cross.append(accepted)
            if discarded is not None and discarded.verdict == "fail":
                discarded_claims.append(discarded)
            continue

        # single claim 走原 verifier 三态逻辑
        accepted, discarded = verify_claim(claim, evidence_map)
        is_uncertain = discarded is not None and discarded.verdict == "uncertain"
        if accepted is not None and not is_uncertain:
            accepted_claims.append(accepted)
        if is_uncertain and accepted is not None:
            uncertain_claims.append(accepted)
        if discarded is not None:
            discarded_claims.append(discarded)

    # Phase 1.5: v1.1 rescue path(feature flag)
    rescue_enabled = os.environ.get("ENABLE_LLM_RESCUE") == "1"
    rescue_total_uncertain = len(uncertain_claims)
    rescue_outcomes: list[RescueOutcome] = []
    if rescue_enabled:
        rescued_auto, rescued_review, rescue_outcomes = rescue_uncertain_with_llm(
            uncertain_claims,
            evidence_map,
        )
        rescued_ids = {
            claim.claim_id
            for claim in [*rescued_auto, *rescued_review]
        }
        uncertain_claims = [
            claim for claim in uncertain_claims if claim.claim_id not in rescued_ids
        ]
        accepted_claims.extend(rescued_auto)
        uncertain_claims.extend(rescued_review)

    # Phase 1.6: v1.1 interpretive guard(post-process only for SWO/POS)
    # Guard is tied to the v1.1 feature flag so flag-off output remains
    # equivalent to the v1.0 baseline.
    if rescue_enabled:
        accepted_claims, uncertain_claims = _apply_interpretive_guard(
            accepted_claims,
            uncertain_claims,
        )
    insight_candidates = [
        claim for claim in uncertain_claims if claim.insight_candidate
    ]

    # Phase 2: 按竞品分组 accepted single
    raw_cross.extend(
        _build_missing_cross_claims(
            run_id=run_id,
            task=task,
            accepted_claims=accepted_claims,
            raw_cross=raw_cross,
            evidence_map=evidence_map,
        )
    )

    claims_by_competitor: dict[str, list[AnalysisClaim]] = {
        competitor.name: [] for competitor in task.competitors
    }
    for claim in accepted_claims:
        if claim.competitor_name:
            claims_by_competitor.setdefault(claim.competitor_name, []).append(claim)

    # Phase 3: Risks 瘦身——按 support_score 降序,只留 floor 之上 + 上限内
    risks_pool = [
        c for c in uncertain_claims
        if (c.support_score or 0) >= _RISKS_MIN_SCORE_FLOOR
        and not c.insight_candidate
    ]
    risks_pool.sort(key=lambda c: c.support_score or 0, reverse=True)
    main_total = sum(len(v) for v in claims_by_competitor.values())
    risks_cap = min(_RISKS_MAX_PER_REPORT, max(2, main_total // 2))
    risks_claims = risks_pool[:risks_cap]

    # Phase 4: Executive Summary
    executive_summary, summary_stats = _build_executive_summary(
        task=task,
        accepted_claims=accepted_claims,
        cross_claims=raw_cross,
        risks_count=len(risks_claims),
    )
    rescue_payload = _build_rescue_outcomes_payload(
        run_id=run_id,
        enabled=rescue_enabled,
        total_uncertain=rescue_total_uncertain,
        outcomes=rescue_outcomes,
    )
    if rescue_payload is not None:
        rescue_cost = float(rescue_payload["total_llm_cost_usd"])
        summary_stats["rescue_llm_cost_usd"] = rescue_cost
        summary_stats["llm_cost_usd"] = round(
            float(summary_stats.get("llm_cost_usd") or 0.0) + rescue_cost,
            6,
        )
        summary_stats["_rescue_outcomes_payload"] = rescue_payload

    # Phase 4.5: M5 v0.2 — 召回质量门
    # 统计每个 competitor 的 evidence 数,识别召回失败的竞品
    evidence_count_by_competitor: dict[str, int] = {
        c.name: 0 for c in task.competitors
    }
    for ev in evidence:
        name = ev.competitor_name
        if name in evidence_count_by_competitor:
            evidence_count_by_competitor[name] += 1
    low_recall_competitors = [
        name
        for name, count in evidence_count_by_competitor.items()
        if count <= _LOW_RECALL_EVIDENCE_THRESHOLD
    ]

    # Phase 5: 渲染模板
    template_dir = Path(__file__).resolve().parents[1] / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["citation_ids"] = format_citation_ids
    template = env.get_template("report.md.j2")
    report_md = template.render(
        task=task,
        run_id=run_id,
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        competitors=[competitor.name for competitor in task.competitors],
        claims_by_competitor=claims_by_competitor,
        cross_claims=raw_cross,
        insight_candidates=insight_candidates,
        risks_claims=risks_claims,
        executive_summary=executive_summary,
        evidence=evidence,
        node_modes=node_modes or {},
        low_recall_competitors=low_recall_competitors,
        evidence_count_by_competitor=evidence_count_by_competitor,
    )
    # 返回 cross 也算作 accepted(主报告内容),便于 CLI summary 显示一致。
    # insight candidates 不进主章节,但写入 claims.json 作为审计型输出,
    # 供 review_queue 生成对应条目。
    insight_artifacts = [
        claim.model_copy(update={"accepted": False})
        for claim in insight_candidates
    ]
    all_accepted = accepted_claims + raw_cross + insight_artifacts
    return report_md, all_accepted, risks_claims, discarded_claims, summary_stats


def render_pm_report_artifacts(
    task: AnalysisTask,
    run_id: str,
    accepted_claims: list[AnalysisClaim],
    risks_claims: list[AnalysisClaim],
    evidence: list[EvidenceItem],
    *,
    qa_audit: dict[str, Any] | None = None,
    revision_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build deterministic PM-readable report artifacts.

    This is intentionally separate from render_report() so the existing audit
    report tuple remains stable for legacy tests and callers.
    """
    payload = build_pm_report_payload(
        task=task,
        run_id=run_id,
        accepted_claims=accepted_claims,
        risks_claims=risks_claims,
        evidence=evidence,
        qa_audit=qa_audit,
        revision_history=revision_history,
    )
    template_dir = Path(__file__).resolve().parents[1] / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report_pm.md.j2")
    report_pm_md = template.render(payload=payload)
    report_pm_summary = build_pm_report_summary(payload)
    return {
        "report_context": payload["report_context"],
        "report_plan": payload["report_plan"],
        "evidence_digest": payload["evidence_digest"],
        "report_pm_md": report_pm_md,
        "report_pm_html": render_pm_report_html(
            report_pm_md,
            task_id=task.task_id,
        ),
        "report_pm_summary": report_pm_summary,
    }


def _apply_interpretive_guard(
    accepted_claims: list[AnalysisClaim],
    uncertain_claims: list[AnalysisClaim],
) -> tuple[list[AnalysisClaim], list[AnalysisClaim]]:
    kept_accepted: list[AnalysisClaim] = []
    guarded_uncertain: list[AnalysisClaim] = []

    for claim in accepted_claims:
        if claim.dimension not in GUARDED_DIMENSIONS:
            kept_accepted.append(claim)
            continue
        is_risk, hits = scan_interpretive_risk(claim)
        if not is_risk:
            kept_accepted.append(claim)
            continue
        guarded_uncertain.append(
            claim.model_copy(
                update={
                    "interpretive_risk": True,
                    "interpretive_hits": hits,
                    "insight_candidate": True,
                }
            )
        )

    for claim in uncertain_claims:
        if claim.dimension not in GUARDED_DIMENSIONS:
            guarded_uncertain.append(claim)
            continue
        is_risk, hits = scan_interpretive_risk(claim)
        if not is_risk:
            guarded_uncertain.append(claim)
            continue
        guarded_uncertain.append(
            claim.model_copy(
                update={
                    "interpretive_risk": True,
                    "interpretive_hits": hits,
                    "insight_candidate": True,
                }
            )
        )

    return kept_accepted, guarded_uncertain


def _build_rescue_outcomes_payload(
    *,
    run_id: str,
    enabled: bool,
    total_uncertain: int,
    outcomes: list[RescueOutcome],
) -> dict[str, Any] | None:
    if not enabled:
        return None
    actions = [outcome.action for outcome in outcomes]
    return {
        "run_id": run_id,
        "executed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "feature_flag": "ENABLE_LLM_RESCUE=1",
        "total_uncertain": total_uncertain,
        "rescued_auto": actions.count("rescue_auto"),
        "rescued_to_review": actions.count("rescue_to_review"),
        "kept_uncertain": actions.count("keep_uncertain"),
        "judge_failed": actions.count("judge_failed"),
        "total_llm_cost_usd": round(
            sum(outcome.llm_cost_usd for outcome in outcomes),
            6,
        ),
        "outcomes": [outcome.model_dump(mode="json") for outcome in outcomes],
    }


def _build_missing_cross_claims(
    run_id: str,
    task: AnalysisTask,
    accepted_claims: list[AnalysisClaim],
    raw_cross: list[AnalysisClaim],
    evidence_map: dict[str, EvidenceItem],
) -> list[AnalysisClaim]:
    if len(task.competitors) < 2 or not accepted_claims:
        return []

    covered: set[str] = set()
    for claim in raw_cross:
        for evidence_id in claim.evidence_ids:
            evidence = evidence_map.get(evidence_id)
            if evidence is not None:
                covered.add(evidence.competitor_name)

    by_comp: dict[str, list[AnalysisClaim]] = {}
    for claim in accepted_claims:
        if claim.competitor_name:
            by_comp.setdefault(claim.competitor_name, []).append(claim)

    supplemental: list[AnalysisClaim] = []
    run_suffix = run_id[-6:]
    for competitor in task.competitors:
        comp_name = competitor.name
        if comp_name in covered or comp_name not in by_comp:
            continue

        primary = by_comp[comp_name][0]
        peer = _find_peer_claim(primary, by_comp)
        if peer is None:
            continue

        evidence_ids = []
        for evidence_id in primary.evidence_ids[:1] + peer.evidence_ids[:1]:
            if evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
        if len(evidence_ids) < 2:
            continue

        peer_name = peer.competitor_name or "peer"
        candidate = AnalysisClaim(
            claim_id=(
                f"C-{run_suffix}-CROSS-AUTO-{len(supplemental) + 1:02d}"
            ),
            run_id=run_id,
            competitor_name=None,
            dimension=primary.dimension,
            statement=(
                f"{comp_name} 与 {peer_name} 在 {primary.dimension} 上可对比: "
                f"{comp_name}: {primary.statement}; "
                f"{peer_name}: {peer.statement}"
            )[:240],
            evidence_ids=evidence_ids,
            confidence=min(primary.confidence or 0.7, peer.confidence or 0.7),
        )
        accepted, _discarded = verify_claim(candidate, evidence_map)
        if accepted is not None:
            supplemental.append(accepted)
            covered.add(comp_name)

    return supplemental


def _find_peer_claim(
    primary: AnalysisClaim,
    by_comp: dict[str, list[AnalysisClaim]],
) -> AnalysisClaim | None:
    for comp_name, claims in by_comp.items():
        if comp_name == primary.competitor_name:
            continue
        for claim in claims:
            if claim.dimension == primary.dimension:
                return claim
    for comp_name, claims in by_comp.items():
        if comp_name != primary.competitor_name and claims:
            return claims[0]
    return None


def _build_executive_summary(
    task: AnalysisTask,
    accepted_claims: list[AnalysisClaim],
    cross_claims: list[AnalysisClaim],
    risks_count: int,
) -> tuple[str, dict[str, Any]]:
    """LLM 生成 200-400 字总览,失败 fallback 到模板统计。

    返回 (summary_text, stats):
    - stats["mode"]:"llm" 或 "template_fallback"
    - stats["model"] / stats["input_tokens"] / stats["output_tokens"] / stats["llm_cost_usd"](仅 LLM 模式)
    - stats["error"](fallback 时的失败原因)
    """
    try:
        text, llm_stats = _llm_executive_summary(task, accepted_claims, cross_claims)
        return text, {"mode": "llm", **llm_stats}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Executive Summary LLM failed, fallback to template: %s", exc)
        text = _template_executive_summary(task, accepted_claims, cross_claims, risks_count)
        return text, {"mode": "template_fallback", "error": str(exc)}


def _template_executive_summary(
    task: AnalysisTask,
    accepted_claims: list[AnalysisClaim],
    cross_claims: list[AnalysisClaim],
    risks_count: int,
) -> str:
    """模板兜底:输出结构化统计摘要。"""
    competitor_names = " / ".join(c.name for c in task.competitors)
    by_comp: dict[str, int] = {}
    for c in accepted_claims:
        if c.competitor_name:
            by_comp[c.competitor_name] = by_comp.get(c.competitor_name, 0) + 1
    per_comp = ", ".join(f"{k}={v}" for k, v in by_comp.items()) or "(暂无)"
    return (
        f"本报告基于自动化 Agent 采集与分析,覆盖 {competitor_names} 三个竞品。"
        f"共生成 {len(accepted_claims)} 条单竞品观察(per competitor: {per_comp})、"
        f"{len(cross_claims)} 条跨竞品对比、{risks_count} 条待核实补充观察。"
        f"详细内容见下方章节。"
    )


def _llm_executive_summary(
    task: AnalysisTask,
    accepted_claims: list[AnalysisClaim],
    cross_claims: list[AnalysisClaim],
) -> tuple[str, dict[str, Any]]:
    """用 LLM 写 200-400 字中文 Executive Summary。

    硬约束:
    - 不允许新增未被 claim 支撑的事实
    - 必须中文主体 + 关键英文短语
    - 长度 200-400 字

    返回 (text, stats):stats 含 model / input_tokens / output_tokens / llm_cost_usd
    """
    from cs_mvp.tools.llm import estimate_cost, get_extractor_llm

    if not accepted_claims and not cross_claims:
        raise RuntimeError("no claims to summarize")

    prompt = _render_summary_prompt(task, accepted_claims, cross_claims)
    llm = get_extractor_llm()
    model_name = (
        getattr(llm, "model", None)
        or getattr(llm, "model_name", None)
        or "unknown"
    )
    response = llm.invoke(prompt)
    # langchain ChatModel 返回 AIMessage,取 content
    text = getattr(response, "content", None) or str(response)
    text = text.strip()
    # 去掉 LLM 偶尔输出的标题行，如 "**Executive Summary**" 或 "# Executive Summary"
    text = re.sub(r"^[#*\s]*Executive\s+Summary[#*\s]*\n+", "", text, flags=re.IGNORECASE)
    text = text.strip()
    if not text:
        raise RuntimeError("LLM returned empty summary")

    # 估算 token / cost(用与 extractor/analyst 相同的粗估算法)
    input_tokens = len(prompt) // 4
    output_tokens = len(text) // 4
    llm_cost = estimate_cost(model_name, input_tokens, output_tokens)
    stats = {
        "model": model_name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "llm_cost_usd": round(llm_cost, 6),
    }
    return text, stats


def _render_summary_prompt(
    task: AnalysisTask,
    accepted_claims: list[AnalysisClaim],
    cross_claims: list[AnalysisClaim],
) -> str:
    competitor_names = " / ".join(c.name for c in task.competitors)
    bullets: list[str] = []
    for c in accepted_claims:
        bullets.append(f"- [{c.competitor_name}|{c.dimension}] {c.statement}")
    for c in cross_claims:
        bullets.append(f"- [CROSS|{c.dimension}] {c.statement}")
    claims_block = "\n".join(bullets[:30])  # 限上下文体量

    return (
        "你是一名资深竞品分析师。基于下方已通过证据校验的 claim 列表,"
        f"为「{task.query}」赛道的竞品分析报告撰写一段中文 Executive Summary。\n\n"
        "【硬约束】\n"
        "- 长度 200-400 字\n"
        "- 中文主体,关键产品名/价格/英文术语保留原文(如 Cursor / $20/mo. / MCP)\n"
        "- 不得新增未在下方 claim 中出现的事实\n"
        "- 不得使用『领先』『最佳』『革命性』等价值判断词\n"
        "- 用 3-5 个段落或 bullet,聚焦真实差异点\n"
        "- 不要重复 claim 原文,做归纳和提炼\n\n"
        f"【竞品范围】{competitor_names}\n"
        f"【已通过的 claim】\n{claims_block}\n\n"
        "直接输出 Executive Summary 文本,不要包含 markdown 标题或代码块。"
    )
