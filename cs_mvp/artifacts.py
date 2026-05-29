from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from cs_mvp.models import AnalysisTask


_EVIDENCE_REF_RE = re.compile(r"\[(E-[^\]\s]+)\]")
# 匹配 markdown 头部 `**调研问题**:xxx`,冒号支持 ASCII `:` (0x3a) 和全角 `:` (U+FF1A)
_QUERY_LINE_RE = re.compile(
    r"^\*\*\s*调研问题\s*\*\*\s*[:：]\s*(.+?)\s*$",
    re.MULTILINE,
)


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


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _counter(items: list[dict[str, Any]], field: str, default: str = "unknown") -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        key = item.get(field) or default
        counts[str(key)] += 1
    return dict(sorted(counts.items()))


def _duration_seconds(started_at: Any, ended_at: Any) -> float | None:
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(ended_at).replace("Z", "+00:00"))
        return round((end - start).total_seconds(), 3)
    except ValueError:
        return None


def _source_summary(sources: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter((item.get("fetch_status") or "skipped") for item in sources)
    valid_sources = [
        item
        for item in sources
        if item.get("fetch_status") == "fetched"
        and _safe_int(item.get("raw_text_length")) >= 500
        and bool(item.get("content_hash"))
    ]
    valid_lengths = [_safe_int(item.get("raw_text_length")) for item in valid_sources]
    return {
        "total": len(sources),
        "fetched": status_counts.get("fetched", 0),
        "failed": status_counts.get("failed", 0),
        "empty": status_counts.get("empty", 0),
        "skipped": status_counts.get("skipped", 0),
        "valid": len(valid_sources),
        "by_competitor": _counter(valid_sources, "competitor_name"),
        "by_status": dict(sorted(status_counts.items())),
        "by_type": _counter(sources, "source_type", "other"),
        "avg_valid_raw_text_length": (
            int(sum(valid_lengths) / len(valid_lengths)) if valid_lengths else 0
        ),
    }


def _evidence_summary(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    quote_lengths = [len(item.get("quote") or "") for item in evidence]
    confidences = [
        _safe_float(item.get("confidence"))
        for item in evidence
        if item.get("confidence") is not None
    ]
    return {
        "total": len(evidence),
        "by_competitor": _counter(evidence, "competitor_name"),
        "by_claim_type": _counter(evidence, "claim_type", "other"),
        "quote_length": {
            "min": min(quote_lengths) if quote_lengths else 0,
            "max": max(quote_lengths) if quote_lengths else 0,
            "avg": round(sum(quote_lengths) / len(quote_lengths), 2)
            if quote_lengths
            else 0.0,
        },
        "confidence": {
            "min": min(confidences) if confidences else None,
            "max": max(confidences) if confidences else None,
            "avg": round(sum(confidences) / len(confidences), 3)
            if confidences
            else None,
        },
    }


def _claim_summary(
    claims: list[dict[str, Any]],
    discarded_claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """Claim 池的统计快照。

    字段口径(v0.3.1 重命名澄清):
    - `accepted_count`:claims.json 中 accepted=True 且 support_score>=0.3 的 claim 数
                       (= 进入主报告 + Risks 章节的总数)
    - `discarded_total`:discarded_claims.json 长度(=uncertain + failed)
    - `generated_total`:accepted + discarded = Analyst 实际生成的所有 claim
    - `total_claims`:= accepted_count(v0.1 历史字段,保留以兼容旧消费者,推荐用 accepted_count)
    """
    scores = [
        _safe_float(item.get("support_score"))
        for item in claims
        if item.get("support_score") is not None
    ]
    accepted = [
        item
        for item in claims
        if bool(item.get("accepted", True)) and _safe_float(item.get("support_score")) >= 0.3
    ]
    single_claims = [item for item in claims if item.get("competitor_name")]
    cross_claims = [item for item in claims if not item.get("competitor_name")]
    verdict_counts = Counter(item.get("verdict") or "unknown" for item in discarded_claims)
    uncertain = verdict_counts.get("uncertain", 0)
    failed = verdict_counts.get("fail", 0)
    accepted_count = len(accepted)
    discarded_total = len(discarded_claims)
    return {
        # 新字段(v0.3.1):语义清晰
        "generated_total": accepted_count + discarded_total,
        "accepted_count": accepted_count,
        # 老字段:保留兼容,但 total_claims 实际就是 accepted(只算 claims.json 长度)
        "total_claims": len(claims),
        "accepted": accepted_count,
        "uncertain": uncertain,
        "failed": failed,
        "discarded_total": discarded_total,
        "single_claims": len(single_claims),
        "cross_claims": len(cross_claims),
        "by_competitor": _counter(single_claims, "competitor_name"),
        "by_dimension": _counter(claims, "dimension"),
        "discarded_by_verdict": dict(sorted(verdict_counts.items())),
        "support_score": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "avg": round(sum(scores) / len(scores), 3) if scores else None,
        },
    }


def _node_summary(node_runs: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for item in node_runs:
        nodes.append(
            {
                "node": item.get("node_name"),
                "status": item.get("status"),
                "started_at": item.get("started_at"),
                "ended_at": item.get("ended_at"),
                "duration_seconds": round(_safe_int(item.get("latency_ms")) / 1000, 3),
                "latency_ms": item.get("latency_ms"),
                "llm_model": item.get("llm_model"),
                "input_tokens": item.get("input_tokens"),
                "output_tokens": item.get("output_tokens"),
                "cost_usd": item.get("cost_usd"),
                "error_message": item.get("error_message"),
            }
        )
    return {
        "total_nodes": len(nodes),
        "completed": sum(1 for item in nodes if item.get("status") == "completed"),
        "failed": sum(1 for item in nodes if item.get("status") == "failed"),
        "nodes": nodes,
    }


def _cost_summary(
    node_runs: list[dict[str, Any]],
    extractor_stats: dict[str, Any],
    analyst_stats: dict[str, Any],
    writer_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    writer_stats = writer_stats or {}
    by_node: dict[str, float] = {}
    by_model: dict[str, float] = {}
    total_tokens = 0
    for item in node_runs:
        node = str(item.get("node_name") or "unknown")
        model = str(item.get("llm_model") or "unknown")
        cost = _safe_float(item.get("cost_usd"))
        by_node[node] = round(by_node.get(node, 0.0) + cost, 6)
        if cost:
            by_model[model] = round(by_model.get(model, 0.0) + cost, 6)
        total_tokens += _safe_int(item.get("input_tokens")) + _safe_int(item.get("output_tokens"))

    # Historical artifacts may have richer cost stats than node_runs.
    # 守卫:如果 node_runs 已记账过这个节点,跳过 stats 文件,避免 by_node / by_model 双重计数。
    for node, stats in (
        ("extractor", extractor_stats),
        ("analyst", analyst_stats),
        ("writer", writer_stats),
    ):
        cost = _safe_float(stats.get("llm_cost_usd"))
        if not cost:
            continue
        if by_node.get(node):  # node_runs 已经覆盖,跳过整条 stats(避免 by_model 翻倍)
            continue
        by_node[node] = round(cost, 6)
        model = stats.get("model")
        if model:
            by_model[str(model)] = round(by_model.get(str(model), 0.0) + cost, 6)
        total_tokens += _safe_int(stats.get("input_tokens")) + _safe_int(stats.get("output_tokens"))

    total_cost = round(sum(by_node.values()), 6)
    budget = _safe_float(extractor_stats.get("max_cost_usd")) or 0.5
    return {
        "total_cost_usd": total_cost,
        "total_tokens": total_tokens,
        "by_node": dict(sorted(by_node.items())),
        "by_model": dict(sorted(by_model.items())),
        "budget_usd": budget,
        "budget_used_ratio": round(total_cost / budget, 3) if budget else None,
    }


def _quality_gates(
    run_dir: Path,
    source_summary: dict[str, Any],
    evidence_summary: dict[str, Any],
    claim_summary: dict[str, Any],
    competitors: list[str],
) -> dict[str, Any]:
    evidence_by_comp = evidence_summary.get("by_competitor", {})
    low_recall = [
        name
        for name in competitors
        if _safe_int(evidence_by_comp.get(name)) <= 3
    ]
    return {
        "has_report": (run_dir / "report.md").exists()
        and bool((run_dir / "report.md").read_text(encoding="utf-8").strip()),
        "has_evidence": evidence_summary.get("total", 0) > 0,
        "has_accepted_claims": claim_summary.get("accepted", 0) > 0,
        "has_cross_claims": claim_summary.get("cross_claims", 0) > 0,
        "low_recall_competitors": low_recall,
        "source_valid_count": source_summary.get("valid", 0),
    }


def write_summary_artifacts(
    run_dir: Path,
    *,
    task: AnalysisTask | None = None,
    run_id: str | None = None,
    node_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Path]:
    """Build and write v0.3 summary artifacts from an existing run directory."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    trace = _load_json(run_dir / "trace.json", {})
    node_runs = node_runs if node_runs is not None else trace.get("node_runs", [])
    sources = _load_json(run_dir / "sources.json", [])
    evidence = _load_json(run_dir / "evidence.json", [])
    claims = _load_json(run_dir / "claims.json", [])
    discarded_claims = _load_json(run_dir / "discarded_claims.json", [])
    extractor_stats = _load_json(run_dir / "extractor_stats.json", {})
    analyst_stats = _load_json(run_dir / "analyst_stats.json", {})
    writer_stats = _load_json(run_dir / "writer_stats.json", {})

    competitors = [item.name for item in task.competitors] if task else sorted(
        set(_counter(sources, "competitor_name")) | set(_counter(evidence, "competitor_name"))
    )

    source_summary = _source_summary(sources)
    evidence_summary = _evidence_summary(evidence)
    claim_summary = _claim_summary(claims, discarded_claims)
    node_summary = _node_summary(node_runs or [])
    cost_summary = _cost_summary(node_runs or [], extractor_stats, analyst_stats, writer_stats)

    first_node = (node_runs or [{}])[0] if node_runs else {}
    last_node = (node_runs or [{}])[-1] if node_runs else {}
    inferred_run_id = run_id or first_node.get("run_id")
    # task 缺失时(如 replay 重生成),从 report.md 头部解析 query
    inferred_query: str | None = task.query if task else None
    if inferred_query is None:
        report_md_path = run_dir / "report.md"
        if report_md_path.exists():
            match = _QUERY_LINE_RE.search(
                report_md_path.read_text(encoding="utf-8")
            )
            if match:
                inferred_query = match.group(1).strip()
    run_summary = {
        "task_id": task.task_id if task else run_dir.name,
        "run_id": inferred_run_id,
        "query": inferred_query,
        "competitors": competitors,
        "status": "completed" if (run_dir / "report.md").exists() else "unknown",
        "started_at": first_node.get("started_at"),
        "completed_at": last_node.get("ended_at"),
        "duration_seconds": _duration_seconds(
            first_node.get("started_at"),
            last_node.get("ended_at"),
        ),
        "report_path": str(run_dir / "report.md"),
        "html_report_path": str(run_dir / "report.html"),
        "warnings": [],
        "quality_gates": _quality_gates(
            run_dir,
            source_summary,
            evidence_summary,
            claim_summary,
            competitors,
        ),
    }

    payloads = {
        "run_summary.json": run_summary,
        "node_summary.json": node_summary,
        "cost_summary.json": cost_summary,
        "claim_summary.json": claim_summary,
        "source_summary.json": source_summary,
        "evidence_summary.json": evidence_summary,
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = run_dir / name
        _write_json(path, payload)
        paths[name] = path
    return paths


_INLINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _render_inline(text: str) -> str:
    """Escape HTML then re-apply markdown inline syntax: **bold** and [E-id] citations."""
    rendered = html.escape(text)
    rendered = _INLINE_BOLD_RE.sub(r"<strong>\1</strong>", rendered)
    rendered = _EVIDENCE_REF_RE.sub(
        r'<a class="citation" href="#\1">[\1]</a>',
        rendered,
    )
    return rendered


def _render_markdown_line(line: str) -> str:
    """Convert one markdown line to HTML.

    Strips the markdown prefix from raw `line` BEFORE escaping the body,
    so `>` / `#` / `-` / `**` markers do not leak into the HTML.
    """
    stripped = line.strip()
    if not stripped:
        return ""
    if line.startswith("# "):
        return f"<h1>{_render_inline(line[2:])}</h1>"
    if line.startswith("## "):
        return f"<h2>{_render_inline(line[3:])}</h2>"
    if line.startswith("### "):
        return f"<h3>{_render_inline(line[4:])}</h3>"
    if line.startswith("> "):
        return f"<blockquote>{_render_inline(line[2:])}</blockquote>"
    if line.startswith("- "):
        return f"<li>{_render_inline(line[2:])}</li>"
    if stripped == "---":
        return "<hr>"
    return f"<p>{_render_inline(line)}</p>"


_APPENDIX_HEADING_RE = re.compile(r"^##\s+Evidence Appendix\s*$", re.IGNORECASE)


def _strip_evidence_appendix(markdown: str) -> str:
    """Drop the Evidence Appendix section from markdown.

    HTML report renders evidence as <details> blocks below the report body,
    so leaving the raw appendix in the markdown body would duplicate it
    (and uses the inferior markdown→HTML path).
    """
    lines = markdown.splitlines()
    output: list[str] = []
    skip = False
    for line in lines:
        if _APPENDIX_HEADING_RE.match(line):
            # Drop the trailing "---" separator we just emitted (if any).
            while output and output[-1].strip() in ("", "---"):
                output.pop()
            skip = True
            continue
        if skip:
            # Stay in skip mode until end of document (Evidence Appendix is the last section).
            continue
        output.append(line)
    return "\n".join(output)


def _markdown_to_html(markdown: str) -> str:
    """Render markdown to HTML, dropping the Evidence Appendix section."""
    body_markdown = _strip_evidence_appendix(markdown)
    lines: list[str] = []
    in_list = False
    in_blockquote = False

    for line in body_markdown.splitlines():
        is_bq = line.startswith("> ") or line.strip() == ">"
        is_li = line.startswith("- ") or line.startswith("* ")

        # 关闭 blockquote
        if in_blockquote and not is_bq:
            lines.append("</blockquote>")
            in_blockquote = False
        # 关闭 list
        if in_list and not is_li:
            lines.append("</ul>")
            in_list = False

        if is_bq:
            inner = line[2:] if line.startswith("> ") else ""
            if not in_blockquote:
                lines.append("<blockquote>")
                in_blockquote = True
            if inner:
                rendered_inner = _render_markdown_line(inner)
                if rendered_inner:
                    lines.append(rendered_inner)
        elif is_li:
            if not in_list:
                lines.append("<ul>")
                in_list = True
            content = line[2:]
            lines.append(f"<li>{_render_inline(content)}</li>")
        else:
            rendered = _render_markdown_line(line)
            if rendered:
                lines.append(rendered)

    if in_blockquote:
        lines.append("</blockquote>")
    if in_list:
        lines.append("</ul>")
    return "\n".join(lines)


def _summary_card(title: str, payload: dict[str, Any]) -> str:
    rows = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            value_text = html.escape(json.dumps(value, ensure_ascii=False, default=str))
        else:
            value_text = html.escape(str(value))
        rows.append(f"<tr><th>{html.escape(str(key))}</th><td>{value_text}</td></tr>")
    return f"<section class=\"card\"><h2>{html.escape(title)}</h2><table>{''.join(rows)}</table></section>"


def _build_charts_js(
    claim_summary: dict[str, Any],
    evidence_summary: dict[str, Any],
    source_summary: dict[str, Any],
) -> str:
    """生成 ECharts 图表的 JS 初始化代码。"""
    PALETTE = ["#6366f1", "#06b6d4", "#f59e0b", "#10b981", "#f43f5e", "#8b5cf6", "#3b82f6"]

    def _js_array(d: dict[str, Any]) -> tuple[str, str]:
        items = [(str(k), int(v)) for k, v in d.items() if v]
        labels = json.dumps([x[0] for x in items], ensure_ascii=False)
        values = json.dumps([x[1] for x in items])
        return labels, values

    # 图1: 各竞品 Claim 数量
    ev_by_comp = evidence_summary.get("by_competitor") or {}
    cl_by_comp = claim_summary.get("by_competitor") or {}
    all_comps = sorted(set(list(ev_by_comp.keys()) + list(cl_by_comp.keys())))
    comp_labels = json.dumps(all_comps, ensure_ascii=False)
    ev_vals = json.dumps([int(ev_by_comp.get(c, 0)) for c in all_comps])
    cl_vals = json.dumps([int(cl_by_comp.get(c, 0)) for c in all_comps])

    # 图2: Claim 维度分布饼图
    by_dim = claim_summary.get("by_dimension") or {}
    dim_map = {
        "features": "功能特性", "pricing": "定价策略", "positioning": "市场定位",
        "swot": "SWOT", "target_users": "目标用户", "strategic_implications": "战略启示",
        "metric": "指标数据", "other": "其他",
    }
    dim_data = [
        {"name": dim_map.get(k, k), "value": int(v)}
        for k, v in by_dim.items() if v
    ]
    dim_data_js = json.dumps(dim_data, ensure_ascii=False)

    # 图3: 数据来源类型分布
    src_by_type = source_summary.get("by_type") or {}
    type_map = {"pricing": "定价页", "docs": "文档", "blog": "博客/资讯", "other": "其他"}
    src_labels, src_vals = _js_array(
        {type_map.get(k, k): v for k, v in src_by_type.items()}
    )

    # 图4: 证据类型分布
    ev_by_type = evidence_summary.get("by_claim_type") or {}
    ev_type_map = {"feature": "功能", "pricing": "定价", "positioning": "定位", "metric": "指标", "other": "其他"}
    ev_type_data = [
        {"name": ev_type_map.get(k, k), "value": int(v)}
        for k, v in ev_by_type.items() if v
    ]
    ev_type_data_js = json.dumps(ev_type_data, ensure_ascii=False)

    palette_js = json.dumps(PALETTE)

    return f"""
const PALETTE = {palette_js};
function initCharts() {{
  // 图1: 竞品证据 & Claim 对比
  const c1 = echarts.init(document.getElementById('chart-competitor'));
  c1.setOption({{
    tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }} }},
    legend: {{ data: ['证据条数', 'Claim 数'], bottom: 0 }},
    grid: {{ left: '3%', right: '4%', bottom: '12%', containLabel: true }},
    xAxis: {{ type: 'category', data: {comp_labels}, axisLabel: {{ fontSize: 12 }} }},
    yAxis: {{ type: 'value', minInterval: 1 }},
    series: [
      {{ name: '证据条数', type: 'bar', data: {ev_vals}, itemStyle: {{ color: PALETTE[0], borderRadius: [4,4,0,0] }}, barMaxWidth: 48 }},
      {{ name: 'Claim 数', type: 'bar', data: {cl_vals}, itemStyle: {{ color: PALETTE[1], borderRadius: [4,4,0,0] }}, barMaxWidth: 48 }}
    ]
  }});

  // 图2: Claim 维度分布
  const c2 = echarts.init(document.getElementById('chart-dimension'));
  c2.setOption({{
    tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
    legend: {{ orient: 'vertical', right: '5%', top: 'center', textStyle: {{ fontSize: 12 }} }},
    color: PALETTE,
    series: [{{
      type: 'pie', radius: ['40%', '70%'], center: ['38%', '50%'],
      data: {dim_data_js},
      label: {{ show: false }},
      emphasis: {{ label: {{ show: true, fontSize: 13, fontWeight: 'bold' }} }}
    }}]
  }});

  // 图3: 数据来源类型
  const c3 = echarts.init(document.getElementById('chart-source-type'));
  c3.setOption({{
    tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }} }},
    grid: {{ left: '3%', right: '4%', bottom: '8%', containLabel: true }},
    xAxis: {{ type: 'value', minInterval: 1 }},
    yAxis: {{ type: 'category', data: {src_labels} }},
    series: [{{
      type: 'bar', data: {src_vals},
      itemStyle: {{ color: PALETTE[2], borderRadius: [0,4,4,0] }},
      barMaxWidth: 36,
      label: {{ show: true, position: 'right', fontSize: 12 }}
    }}]
  }});

  // 图4: 证据类型分布
  const c4 = echarts.init(document.getElementById('chart-evidence-type'));
  c4.setOption({{
    tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
    legend: {{ orient: 'vertical', right: '5%', top: 'center', textStyle: {{ fontSize: 12 }} }},
    color: [PALETTE[3], PALETTE[0], PALETTE[4], PALETTE[2], PALETTE[5]],
    series: [{{
      type: 'pie', radius: ['40%', '70%'], center: ['38%', '50%'],
      data: {ev_type_data_js},
      label: {{ show: false }},
      emphasis: {{ label: {{ show: true, fontSize: 13, fontWeight: 'bold' }} }}
    }}]
  }});

  window.addEventListener('resize', () => {{ c1.resize(); c2.resize(); c3.resize(); c4.resize(); }});
}}
document.addEventListener('DOMContentLoaded', initCharts);
"""


def export_html_report(run_dir: Path) -> Path:
    """Render a standalone static HTML report from a run directory."""
    run_dir = Path(run_dir)
    if not (run_dir / "run_summary.json").exists():
        write_summary_artifacts(run_dir)

    report_md = (run_dir / "report.md").read_text(encoding="utf-8")
    run_summary = _load_json(run_dir / "run_summary.json", {})
    claim_summary = _load_json(run_dir / "claim_summary.json", {})
    source_summary = _load_json(run_dir / "source_summary.json", {})
    evidence_summary = _load_json(run_dir / "evidence_summary.json", {})
    sources = _load_json(run_dir / "sources.json", [])
    evidence = _load_json(run_dir / "evidence.json", [])
    claims = _load_json(run_dir / "claims.json", [])
    source_by_id = {item.get("source_id"): item for item in sources}

    # ── 封面数据 ──────────────────────────────────────────────
    competitors: list[str] = run_summary.get("competitors") or []
    query = html.escape(str(run_summary.get("query") or ""))
    completed_at = str(run_summary.get("completed_at") or "")[:10]
    duration = run_summary.get("duration_seconds")
    duration_str = f"{duration:.0f}s" if duration else "—"
    total_evidence = evidence_summary.get("total") or 0
    total_claims = claim_summary.get("accepted_count") or claim_summary.get("total_claims") or 0
    source_valid = source_summary.get("valid_count") or 0

    competitor_chips = "".join(
        f'<span class="chip">{html.escape(c)}</span>' for c in competitors
    )

    # ── 质量指标卡 ────────────────────────────────────────────
    qg = run_summary.get("quality_gates") or {}
    low_recall = qg.get("low_recall_competitors") or []
    accepted_pct = ""
    gen = claim_summary.get("generated_total") or 0
    acc = claim_summary.get("accepted_count") or 0
    if gen:
        accepted_pct = f"{acc}/{gen} ({acc*100//gen}%)"

    metric_cards = f"""
<div class="metrics-grid">
  <div class="metric-card"><div class="metric-val">{total_evidence}</div><div class="metric-label">有效证据</div></div>
  <div class="metric-card"><div class="metric-val">{total_claims}</div><div class="metric-label">通过 Claim</div></div>
  <div class="metric-card"><div class="metric-val">{source_valid}</div><div class="metric-label">有效来源</div></div>
  <div class="metric-card"><div class="metric-val">{accepted_pct or acc}</div><div class="metric-label">QA 通过率</div></div>
  <div class="metric-card"><div class="metric-val">{duration_str}</div><div class="metric-label">分析耗时</div></div>
</div>"""

    # ── 图表区 ────────────────────────────────────────────────
    charts_section = """
<section class="section-charts">
  <h2>数据洞察概览</h2>
  <div class="charts-grid">
    <div class="chart-wrap">
      <div class="chart-title">各竞品证据与 Claim 对比</div>
      <div id="chart-competitor" class="chart-box"></div>
    </div>
    <div class="chart-wrap">
      <div class="chart-title">Claim 维度分布</div>
      <div id="chart-dimension" class="chart-box"></div>
    </div>
    <div class="chart-wrap">
      <div class="chart-title">数据来源类型</div>
      <div id="chart-source-type" class="chart-box"></div>
    </div>
    <div class="chart-wrap">
      <div class="chart-title">证据类型分布</div>
      <div id="chart-evidence-type" class="chart-box"></div>
    </div>
  </div>
</section>"""

    # ── 横向对比矩阵 ─────────────────────────────────────────
    _DIM_LABEL = {
        "features": "核心功能",
        "pricing": "定价模式",
        "target_users": "目标用户",
        "positioning": "产品定位",
        "swot": "优劣势",
        "strategic_implications": "战略启示",
    }
    _KEY_DIMS = ["features", "pricing", "target_users", "positioning"]
    matrix_section = ""
    if competitors and claims:
        accepted = [c for c in claims if c.get("accepted") is not False]
        by_comp_dim: dict[str, dict[str, str]] = {comp: {} for comp in competitors}
        for claim in accepted:
            comp = str(claim.get("competitor_name") or "")
            dim = str(claim.get("dimension") or "")
            stmt = str(claim.get("statement") or "")
            if comp in by_comp_dim and dim and stmt:
                if dim not in by_comp_dim[comp]:
                    by_comp_dim[comp][dim] = stmt[:120] + ("…" if len(stmt) > 120 else "")
        present_dims = [d for d in _KEY_DIMS if any(d in by_comp_dim[c] for c in competitors)]
        if present_dims and len(competitors) >= 2:
            th_cells = "".join(f"<th>{html.escape(c)}</th>" for c in competitors)
            rows_html = ""
            for dim in present_dims:
                td_cells = ""
                for comp in competitors:
                    val = by_comp_dim[comp].get(dim, "—")
                    td_cells += f"<td>{html.escape(val)}</td>"
                dim_label = html.escape(_DIM_LABEL.get(dim, dim))
                rows_html += f"<tr><th class='matrix-dim'>{dim_label}</th>{td_cells}</tr>"
            matrix_section = f"""
<section>
  <h2>横向对比矩阵</h2>
  <div class="matrix-scroll">
  <table class="matrix-table">
    <thead><tr><th></th>{th_cells}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  </div>
</section>"""

    # ── 来源列表 ──────────────────────────────────────────────
    source_links = []
    for source in sources:
        url = source.get("url") or ""
        status = source.get("fetch_status") or ""
        stype = source.get("source_type") or ""
        comp = html.escape(str(source.get("competitor_name") or ""))
        title = html.escape(str(source.get("title") or source.get("source_id") or ""))
        status_cls = "src-ok" if status == "fetched" else "src-fail"
        source_links.append(
            f'<li class="src-item">'
            f'<span class="src-comp">{comp}</span>'
            f'<span class="src-type">{html.escape(stype)}</span>'
            f'<span class="src-status {status_cls}">{html.escape(status)}</span>'
            f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer">{title}</a>'
            f'</li>'
        )

    # ── 证据块 ────────────────────────────────────────────────
    evidence_blocks = []
    for item in evidence:
        evidence_id = html.escape(str(item.get("evidence_id") or ""))
        source = source_by_id.get(item.get("source_id"), {})
        url = source.get("url") or ""
        quote = html.escape(str(item.get("quote") or ""))
        normalized_fact = html.escape(str(item.get("normalized_fact") or ""))
        comp = html.escape(str(item.get("competitor_name") or ""))
        ctype_raw = str(item.get("claim_type") or "")
        ctype_map = {"feature": "功能", "pricing": "定价", "positioning": "定位", "metric": "指标", "other": "其他"}
        ctype = html.escape(ctype_map.get(ctype_raw, ctype_raw))
        evidence_blocks.append(
            f'<details id="{evidence_id}" class="evidence">'
            f'<summary><span class="ev-id">{evidence_id}</span>'
            f'<span class="ev-comp">{comp}</span>'
            f'<span class="ev-type">{ctype}</span></summary>'
            f'<p class="fact">{normalized_fact}</p>'
            f'<blockquote>{quote}</blockquote>'
            f'<p class="ev-src"><a href="{html.escape(url)}" target="_blank" rel="noreferrer">'
            f'{html.escape(str(item.get("source_id") or "source"))}</a></p>'
            '</details>'
        )

    low_recall_warn = ""
    if low_recall:
        names = "、".join(low_recall)
        low_recall_warn = (
            f'<div class="warn-banner">⚠️ 数据召回不足：{html.escape(names)} 的证据数量偏低，'
            '相关分析覆盖可能不完整。</div>'
        )

    charts_js = _build_charts_js(claim_summary, evidence_summary, source_summary)

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>竞品分析报告 · {html.escape(", ".join(competitors))}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; margin: 0; color: #1e293b; background: #f1f5f9; line-height: 1.75; font-size: 15px; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 40px 24px 100px; }}

    /* ── 封面 ── */
    .cover {{ background: linear-gradient(135deg, #1e3a8a 0%, #312e81 100%); border-radius: 14px; padding: 40px 48px; color: #fff; margin-bottom: 24px; }}
    .cover-label {{ font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: #a5b4fc; margin-bottom: 12px; }}
    .cover-title {{ font-size: 1.65rem; font-weight: 700; line-height: 1.4; margin: 0 0 20px; }}
    .cover-chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }}
    .chip {{ background: rgba(255,255,255,.15); border: 1px solid rgba(255,255,255,.25); border-radius: 20px; padding: 3px 14px; font-size: 13px; color: #e0e7ff; }}
    .cover-meta {{ display: flex; gap: 24px; font-size: 13px; color: #c7d2fe; flex-wrap: wrap; }}
    .cover-meta span b {{ color: #fff; }}

    /* ── 质量指标 ── */
    .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 20px 0 0; }}
    .metric-card {{ background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.2); border-radius: 10px; padding: 14px 16px; text-align: center; }}
    .metric-val {{ font-size: 1.6rem; font-weight: 700; color: #fff; line-height: 1.2; }}
    .metric-label {{ font-size: 11.5px; color: #c7d2fe; margin-top: 4px; }}

    /* ── 通用卡片 ── */
    section {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 28px 32px; margin: 20px 0; box-shadow: 0 1px 4px rgba(0,0,0,.05); }}
    h2 {{ font-size: 1.15rem; font-weight: 700; color: #0f172a; margin: 0 0 20px; padding-bottom: 12px; border-bottom: 2px solid #6366f1; display: flex; align-items: center; gap: 8px; }}
    h2::before {{ content: ''; display: inline-block; width: 4px; height: 18px; background: #6366f1; border-radius: 2px; }}
    h3 {{ font-size: 1rem; font-weight: 700; color: #1e40af; margin: 24px 0 8px; }}
    h4 {{ font-size: .95rem; font-weight: 600; color: #334155; margin: 16px 0 6px; }}

    /* ── 报告正文 ── */
    .report p {{ margin: 8px 0 14px; color: #374151; }}
    .report ul {{ padding-left: 1.5em; margin: 6px 0 14px; }}
    .report li {{ margin-bottom: 8px; color: #374151; }}
    .report li::marker {{ color: #6366f1; }}
    .report strong {{ color: #1e293b; }}
    .report blockquote {{ border-left: 4px solid #6366f1; margin: 12px 0; padding: 10px 16px; color: #4b5563; background: #f8fafc; border-radius: 0 8px 8px 0; font-size: 14px; }}
    .report table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 14px 0; border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; }}
    .report table th {{ background: #f0f4ff; font-weight: 600; color: #1e3a8a; padding: 10px 14px; text-align: left; border-bottom: 2px solid #c7d2fe; }}
    .report table td {{ padding: 9px 14px; border-bottom: 1px solid #f1f5f9; color: #374151; }}
    .report table tr:hover td {{ background: #fafbff; }}
    .report hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 24px 0; }}

    /* ── 图表区 ── */
    .charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    .chart-wrap {{ background: #fafbff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; }}
    .chart-title {{ font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 8px; }}
    .chart-box {{ height: 240px; }}
    @media (max-width: 700px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}

    /* ── 数据来源 ── */
    .src-list {{ list-style: none; padding: 0; margin: 0; }}
    .src-item {{ display: flex; align-items: baseline; gap: 8px; padding: 7px 0; border-bottom: 1px solid #f1f5f9; font-size: 13px; flex-wrap: wrap; }}
    .src-item:last-child {{ border-bottom: none; }}
    .src-comp {{ font-weight: 600; color: #1e3a8a; min-width: 80px; }}
    .src-type {{ font-size: 11px; background: #f0f4ff; color: #4338ca; border-radius: 4px; padding: 1px 7px; }}
    .src-status {{ font-size: 11px; border-radius: 4px; padding: 1px 7px; }}
    .src-ok {{ background: #f0fdf4; color: #15803d; }}
    .src-fail {{ background: #fef2f2; color: #b91c1c; }}

    /* ── 证据块 ── */
    details.evidence {{ border-top: 1px solid #f1f5f9; padding: 10px 0; }}
    details.evidence:last-child {{ border-bottom: none; }}
    summary {{ cursor: pointer; display: flex; align-items: center; gap: 8px; user-select: none; }}
    summary:hover .ev-id {{ color: #2563eb; }}
    .ev-id {{ font-weight: 700; color: #6366f1; font-size: 13px; font-family: monospace; }}
    .ev-comp {{ font-weight: 600; font-size: 13px; color: #1e293b; }}
    .ev-type {{ font-size: 11px; background: #f0f4ff; color: #4338ca; border-radius: 4px; padding: 1px 7px; }}
    .fact {{ color: #374151; font-size: 14px; margin: 8px 0 4px; line-height: 1.6; }}
    .ev-src {{ font-size: 12px; color: #94a3b8; margin-top: 4px; }}

    /* ── 其他 ── */
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{ background: #f1f5f9; padding: 1px 5px; border-radius: 4px; font-size: 12.5px; color: #d97706; font-family: monospace; }}
    .citation {{ font-weight: 700; color: #6366f1; font-size: .85em; }}
    .warn-banner {{ background: #fef2f2; border: 1px solid #fca5a5; border-radius: 8px; padding: 12px 16px; color: #b91c1c; margin-bottom: 16px; font-size: 13.5px; }}
    .section-charts h2::before {{ background: #06b6d4; }}
    .section-charts h2 {{ border-bottom-color: #06b6d4; }}
    .footer-note {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 40px; }}

    /* ── 横向对比矩阵 ── */
    .matrix-scroll {{ overflow-x: auto; }}
    .matrix-table {{ width: 100%; border-collapse: collapse; font-size: 13px; min-width: 480px; }}
    .matrix-table th {{ background: #f0f4ff; font-weight: 600; color: #1e3a8a; padding: 9px 14px; border: 1px solid #e2e8f0; text-align: left; }}
    .matrix-table td {{ padding: 9px 14px; border: 1px solid #e2e8f0; color: #374151; vertical-align: top; }}
    .matrix-table tr:hover td {{ background: #fafbff; }}
    .matrix-table th.matrix-dim {{ background: #f8fafc; color: #475569; font-weight: 600; min-width: 80px; }}
  </style>
</head>
<body>
<main>

<!-- 封面 -->
<div class="cover">
  <div class="cover-label">竞品分析报告 · AI 生成</div>
  <div class="cover-title">{query}</div>
  <div class="cover-chips">{competitor_chips}</div>
  <div class="cover-meta">
    <span><b>生成日期</b> {html.escape(completed_at)}</span>
    <span><b>分析耗时</b> {html.escape(duration_str)}</span>
    <span><b>Run ID</b> {html.escape(str(run_summary.get("run_id") or ""))}</span>
  </div>
  {metric_cards}
</div>

{low_recall_warn}

<!-- 数据洞察图表 -->
{charts_section}

<!-- 横向对比矩阵 -->
{matrix_section}

<!-- 分析报告正文 -->
<section class="report">
{_markdown_to_html(report_md)}
</section>

<!-- 数据来源 -->
<section>
  <h2>数据来源</h2>
  <ul class="src-list">{"".join(source_links)}</ul>
</section>

<!-- 证据详情 -->
<section>
  <h2>证据详情</h2>
  {"".join(evidence_blocks)}
</section>

<p class="footer-note">本报告由 cs-mvp 竞品分析系统自动生成 · AI 生成内容仅供参考</p>
</main>
<script>{charts_js}</script>
</body>
</html>
"""
    output = run_dir / "report.html"
    output.write_text(html_text, encoding="utf-8")
    return output
