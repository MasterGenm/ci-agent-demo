from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


REPORT_STYLE_AUDIT_SCHEMA_VERSION = "1.7.0"

REQUIRED_SECTIONS: tuple[tuple[str, str], ...] = (
    ("one_page_summary", "## 1. 一页结论"),
    ("competitor_matrix", "## 2. 竞品对比矩阵"),
    ("top_findings", "## 3. Top Findings"),
    ("competitor_profiles", "## 4. 各竞品画像"),
    ("recommendations", "## 5. 产品机会点"),
    ("risks_and_unknowns", "## 6. 风险与不确定性"),
    ("evidence_digest", "## 7. Evidence Digest"),
)

AI_TONE_RULES: tuple[tuple[str, str], ...] = (
    ("unsupported_superlative", "领先"),
    ("unsupported_superlative", "最佳"),
    ("unsupported_superlative", "革命性"),
    ("generic_transition", "全面赋能"),
    ("generic_transition", "深度融合"),
)

_CITATION_RE = re.compile(r"\[(E-[A-Za-z0-9_.-]+)\]")
_RECOMMENDATION_RE = re.compile(r"\*\*(R-\d{2})\*\*")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 3)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def _paragraphs(report_md: str) -> list[str]:
    blocks = [
        " ".join(block.split())
        for block in report_md.split("\n\n")
    ]
    return [
        block
        for block in blocks
        if block
        and not block.startswith("#")
        and not block.startswith("- ")
        and not block.startswith("|")
        and not block.startswith("**")
    ]


def _section_coverage(report_md: str) -> dict[str, bool]:
    return {
        key: heading in report_md
        for key, heading in REQUIRED_SECTIONS
    }


def _ai_tone_flags(report_md: str) -> list[dict[str, Any]]:
    paragraphs = _paragraphs(report_md)
    flags: dict[str, dict[str, Any]] = {}
    for paragraph in paragraphs:
        for flag, phrase in AI_TONE_RULES:
            if phrase not in paragraph:
                continue
            if phrase == "显著提升" and "[E-" in paragraph:
                continue
            entry = flags.setdefault(flag, {"flag": flag, "count": 0, "examples": []})
            entry["count"] += paragraph.count(phrase)
            if len(entry["examples"]) < 3:
                entry["examples"].append(paragraph[:180])
    for paragraph in paragraphs:
        if "显著提升" in paragraph and "[E-" not in paragraph:
            entry = flags.setdefault(
                "unsupported_superlative",
                {"flag": "unsupported_superlative", "count": 0, "examples": []},
            )
            entry["count"] += paragraph.count("显著提升")
            if len(entry["examples"]) < 3:
                entry["examples"].append(paragraph[:180])
    return list(flags.values())


def _recommendation_lines(report_md: str) -> list[str]:
    lines = []
    for line in report_md.splitlines():
        if _RECOMMENDATION_RE.search(line):
            lines.append(line.strip())
    return lines


def _recommendation_blocks(report_md: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in report_md.splitlines():
        if _RECOMMENDATION_RE.search(line):
            if current:
                blocks.append("\n".join(current))
            current = [line.strip()]
            continue
        if current and (line.startswith("  ") or not line.strip()):
            current.append(line.strip())
            continue
        if current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def evaluate_report_style(
    *,
    task_id: str,
    run_id: str | None,
    report_md: str,
    report_pm_summary: dict[str, Any],
    report_plan: dict[str, Any],
    evidence_digest: dict[str, Any],
) -> dict[str, Any]:
    notes: list[str] = []
    if not report_md.strip():
        notes.append("report_pm.md is missing or empty.")

    section_coverage = _section_coverage(report_md)
    covered_sections = sum(1 for value in section_coverage.values() if value)
    lines = report_md.splitlines()
    bullet_count = sum(1 for line in lines if line.strip().startswith("- "))
    word_count = len(_WORD_RE.findall(report_md))
    long_paragraph_count = sum(1 for item in _paragraphs(report_md) if len(item) > 220)
    recommendation_lines = _recommendation_lines(report_md)
    recommendation_count = int(
        report_pm_summary.get("recommendation_count")
        or len(recommendation_lines)
    )
    recommendation_blocks = _recommendation_blocks(report_md)
    recommendations_with_evidence = sum(
        1 for block in recommendation_blocks if "[E-" in block
    )
    if recommendation_count and not recommendation_lines:
        recommendations_with_evidence = min(
            recommendation_count,
            int(report_pm_summary.get("evidence_digest_count") or 0),
        )
    recommendations_needing_validation = sum(
        1 for block in recommendation_blocks if "needs validation" in block
    )
    citations = _CITATION_RE.findall(report_md)
    unique_citations = sorted(set(citations))
    uncited_recommendation_count = max(
        0,
        recommendation_count - recommendations_with_evidence,
    )
    tone_flags = _ai_tone_flags(report_md)
    finding_count = int(report_pm_summary.get("top_finding_count") or 0)
    digest_count = len(evidence_digest.get("items") or [])
    planned_sections = report_plan.get("sections")
    if isinstance(planned_sections, list) and len(planned_sections) < len(REQUIRED_SECTIONS):
        notes.append("report_plan has fewer than seven sections.")
    if digest_count == 0:
        notes.append("evidence_digest is empty.")

    section_score = _safe_ratio(covered_sections, len(REQUIRED_SECTIONS))
    readability_score = _clamp(
        section_score
        - min(0.25, long_paragraph_count * 0.05)
        - min(0.15, len(tone_flags) * 0.03)
    )
    actionability_score = _clamp(
        _safe_ratio(recommendations_with_evidence, recommendation_count)
        if recommendation_count
        else 0.0
    )
    grounding_denominator = max(1, recommendation_count + finding_count)
    evidence_grounding_score = _clamp(
        min(1.0, len(unique_citations) / grounding_denominator)
    )
    overall_score = _clamp(
        (readability_score + actionability_score + evidence_grounding_score) / 3
    )

    return {
        "schema_version": REPORT_STYLE_AUDIT_SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "report_type": "pm",
        "section_coverage": section_coverage,
        "readability": {
            "word_count": word_count,
            "bullet_count": bullet_count,
            "bullet_ratio": _safe_ratio(bullet_count, max(1, len(lines))),
            "long_paragraph_count": long_paragraph_count,
        },
        "actionability": {
            "recommendation_count": recommendation_count,
            "recommendations_with_evidence": recommendations_with_evidence,
            "recommendations_needing_validation": recommendations_needing_validation,
        },
        "evidence_density": {
            "citation_count": len(citations),
            "unique_citation_count": len(unique_citations),
            "uncited_recommendation_count": uncited_recommendation_count,
        },
        "ai_tone_flags": tone_flags,
        "score": {
            "readability_score": readability_score,
            "actionability_score": actionability_score,
            "evidence_grounding_score": evidence_grounding_score,
            "overall_score": overall_score,
        },
        "notes": notes,
    }


def render_report_style_audit_markdown(audit: dict[str, Any]) -> str:
    section_coverage = audit.get("section_coverage", {})
    readability = audit.get("readability", {})
    actionability = audit.get("actionability", {})
    evidence_density = audit.get("evidence_density", {})
    score = audit.get("score", {})
    flags = audit.get("ai_tone_flags", [])
    notes = audit.get("notes", [])

    lines = [
        "# Report Style Audit",
        "",
        "## Summary",
        "",
        f"- Task ID: {audit.get('task_id')}",
        f"- Run ID: {audit.get('run_id') or '(unknown)'}",
        f"- Report type: {audit.get('report_type')}",
        f"- Overall score: {score.get('overall_score', 0.0)}",
        "",
        "## Section Coverage",
        "",
    ]
    for key, value in section_coverage.items():
        lines.append(f"- {key}: {'PASS' if value else 'MISSING'}")
    lines.extend(
        [
            "",
            "## Readability",
            "",
            f"- Word count: {readability.get('word_count', 0)}",
            f"- Bullet count: {readability.get('bullet_count', 0)}",
            f"- Bullet ratio: {readability.get('bullet_ratio', 0.0)}",
            f"- Long paragraph count: {readability.get('long_paragraph_count', 0)}",
            "",
            "## Actionability",
            "",
            f"- Recommendation count: {actionability.get('recommendation_count', 0)}",
            f"- Recommendations with evidence: {actionability.get('recommendations_with_evidence', 0)}",
            f"- Recommendations needing validation: {actionability.get('recommendations_needing_validation', 0)}",
            "",
            "## Evidence Grounding",
            "",
            f"- Citation count: {evidence_density.get('citation_count', 0)}",
            f"- Unique citation count: {evidence_density.get('unique_citation_count', 0)}",
            f"- Uncited recommendation count: {evidence_density.get('uncited_recommendation_count', 0)}",
            "",
            "## AI Tone Flags",
            "",
        ]
    )
    if flags:
        for flag in flags:
            lines.append(f"- {flag.get('flag')}: {flag.get('count', 0)}")
            for example in flag.get("examples") or []:
                lines.append(f"  - Example: {example}")
    else:
        lines.append("- None")
    lines.extend(["", "## Notes", ""])
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- No blocking notes. This is a heuristic audit, not an LLM judge.")
    return "\n".join(lines) + "\n"


def write_report_style_audit(run_dir: Path) -> dict[str, Path]:
    run_dir = Path(run_dir)
    report_md_path = run_dir / "report_pm.md"
    report_md = report_md_path.read_text(encoding="utf-8") if report_md_path.exists() else ""
    summary = _load_json(run_dir / "report_pm_summary.json", {})
    report_plan = _load_json(run_dir / "report_plan.json", {})
    evidence_digest = _load_json(run_dir / "evidence_digest.json", {})
    run_summary = _load_json(run_dir / "run_summary.json", {})
    summary_payload = summary if isinstance(summary, dict) else {}
    run_summary_payload = run_summary if isinstance(run_summary, dict) else {}
    report_plan_payload = report_plan if isinstance(report_plan, dict) else {}
    evidence_digest_payload = (
        evidence_digest if isinstance(evidence_digest, dict) else {}
    )
    audit = evaluate_report_style(
        task_id=str(summary_payload.get("task_id") or run_dir.name),
        run_id=summary_payload.get("run_id") or run_summary_payload.get("run_id"),
        report_md=report_md,
        report_pm_summary=summary_payload,
        report_plan=report_plan_payload,
        evidence_digest=evidence_digest_payload,
    )
    json_path = run_dir / "report_style_audit.json"
    md_path = run_dir / "report_style_audit.md"
    _write_json(json_path, audit)
    md_path.write_text(render_report_style_audit_markdown(audit), encoding="utf-8")
    return {
        "json": json_path,
        "markdown": md_path,
    }
