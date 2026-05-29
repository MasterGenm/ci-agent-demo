"""Static report quality checks for a cs-mvp run directory.

Usage:
    python scripts/report_quality_check.py runs/<task_id>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _check(ok: bool, name: str, detail: str, severity: str = "error") -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "severity": severity,
        "detail": detail,
    }


_PLACEHOLDER_MARKER = "本竞品本轮未生成可信单项观察"
_MIN_EXECUTIVE_SUMMARY_CHARS = 100


def _extract_executive_summary(report_text: str) -> str:
    """提取 ## Executive Summary 段落正文(不含标题, 不含后续章节)。"""
    if "## Executive Summary" not in report_text:
        return ""
    after_heading = report_text.split("## Executive Summary", 1)[1]
    # 在下一个 ## 之前的内容是 summary body
    if "##" in after_heading:
        body = after_heading.split("\n##", 1)[0]
    else:
        body = after_heading
    return body.strip()


def _competitor_has_content(report_text: str, competitor: str) -> tuple[bool, str]:
    """检查 ## <competitor> 主章节是否有实质内容。

    返回 (has_content, detail):
    - has_content=False 当且仅当章节存在但全是占位符,或章节不存在
    """
    heading = f"## {competitor}"
    if heading not in report_text:
        return False, f"missing heading"
    section = report_text.split(heading, 1)[1].split("\n## ", 1)[0]
    if _PLACEHOLDER_MARKER in section:
        return False, "section contains placeholder only"
    # 至少要有一条 bullet 或字符串内容,排除掉只有空白+分隔符
    stripped = section.strip()
    if not stripped or len(stripped) < 20:
        return False, f"section too short ({len(stripped)} chars)"
    return True, f"section_chars={len(stripped)}"


def evaluate_run_dir(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    report_path = run_dir / "report.md"
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    run_summary = _load_json(run_dir / "run_summary.json", {})
    sources = _load_json(run_dir / "sources.json", [])
    evidence = _load_json(run_dir / "evidence.json", [])
    claims = _load_json(run_dir / "claims.json", [])
    discarded = _load_json(run_dir / "discarded_claims.json", [])

    competitors = run_summary.get("competitors") or sorted(
        {
            item.get("competitor_name")
            for item in evidence + claims
            if item.get("competitor_name")
        }
    )
    accepted_claims = [
        item
        for item in claims
        if item.get("accepted", True) and (item.get("support_score") or 0.0) >= 0.3
    ]
    cross_claims = [item for item in claims if not item.get("competitor_name")]
    low_recall_warning = "数据召回警告" in report_text

    # v0.3.1 Bug 9: Executive Summary 必须有实质内容(>=100 字符),不只是含标题
    summary_body = _extract_executive_summary(report_text)
    summary_chars = len(summary_body)

    checks = [
        _check(report_path.exists() and bool(report_text.strip()), "report_exists", str(report_path)),
        _check(
            summary_chars >= _MIN_EXECUTIVE_SUMMARY_CHARS,
            "has_executive_summary",
            f"summary_chars={summary_chars} (min={_MIN_EXECUTIVE_SUMMARY_CHARS})",
        ),
        _check("Evidence Appendix" in report_text, "has_evidence_appendix", "Evidence Appendix heading"),
        _check(bool(evidence), "has_evidence", f"evidence_count={len(evidence)}"),
        _check(bool(accepted_claims), "has_accepted_claims", f"accepted={len(accepted_claims)}"),
        _check(bool(cross_claims), "has_cross_claims", f"cross={len(cross_claims)}", severity="warning"),
        _check(bool(sources), "has_sources", f"source_count={len(sources)}"),
        _check(not low_recall_warning, "no_low_recall_warning", str(low_recall_warning), severity="warning"),
    ]
    for competitor in competitors:
        # v0.3.1 Bug 9: 不只看字符串存在,还要看主章节是否有实质内容
        has_content, detail = _competitor_has_content(report_text, competitor)
        checks.append(
            _check(
                has_content,
                f"mentions_competitor:{competitor}",
                detail,
                severity="warning",
            )
        )

    passed = sum(1 for item in checks if item["ok"])
    failed = len(checks) - passed
    payload = {
        "run_dir": str(run_dir),
        "passed": passed,
        "failed": failed,
        "checks": checks,
        "counts": {
            "sources": len(sources),
            "evidence": len(evidence),
            "claims": len(claims),
            "discarded": len(discarded),
            "accepted_claims": len(accepted_claims),
            "cross_claims": len(cross_claims),
        },
    }
    return payload


def write_report_quality(run_dir: Path) -> dict[str, Path]:
    payload = evaluate_run_dir(run_dir)
    run_dir = Path(run_dir)
    json_path = run_dir / "report_quality.json"
    md_path = run_dir / "report_quality.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Report Quality Check",
        "",
        f"- run_dir: `{payload['run_dir']}`",
        f"- passed: {payload['passed']}",
        f"- failed: {payload['failed']}",
        "",
        "## Checks",
        "",
    ]
    for item in payload["checks"]:
        status = "PASS" if item["ok"] else "FAIL"
        lines.append(f"- {status} {item['name']}: {item['detail']}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    outputs = write_report_quality(args.run_dir)
    for name, path in outputs.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
