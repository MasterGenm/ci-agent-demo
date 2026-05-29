from __future__ import annotations

import json
from pathlib import Path

from scripts.replay_artifacts import replay
from scripts.report_quality_check import evaluate_run_dir, write_report_quality


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "T-scripts"
    run_dir.mkdir()
    (run_dir / "report.md").write_text(
        "# 竞品分析报告\n\n## Executive Summary\n\nCursor and Windsurf summary.\n\n"
        "## Cursor\n\n- claim\n\n## Windsurf\n\n- claim\n\n"
        "## 跨竞品对比\n\n- cross\n\n## Evidence Appendix\n",
        encoding="utf-8",
    )
    _write_json(
        run_dir / "sources.json",
        [
            {
                "source_id": "S-001",
                "competitor_name": "Cursor",
                "url": "https://cursor.com",
                "source_type": "official_site",
                "fetch_status": "fetched",
                "content_hash": "abc",
                "raw_text_length": 1000,
            }
        ],
    )
    _write_json(
        run_dir / "evidence.json",
        [
            {
                "evidence_id": "E-001",
                "source_id": "S-001",
                "competitor_name": "Cursor",
                "claim_type": "feature",
                "quote": "Cursor supports agentic coding.",
            }
        ],
    )
    _write_json(
        run_dir / "claims.json",
        [
            {
                "claim_id": "C-001",
                "competitor_name": "Cursor",
                "dimension": "features",
                "statement": "Cursor supports agentic coding.",
                "evidence_ids": ["E-001"],
                "support_score": 0.8,
                "accepted": True,
            },
            {
                "claim_id": "C-CROSS",
                "competitor_name": None,
                "dimension": "features",
                "statement": "Cursor and Windsurf differ.",
                "evidence_ids": ["E-001"],
                "support_score": 0.4,
                "accepted": True,
            },
        ],
    )
    _write_json(run_dir / "discarded_claims.json", [])
    return run_dir


def test_replay_artifacts_rebuilds_summary_files(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)

    outputs = replay(run_dir)

    assert "run_summary.json" in outputs
    assert (run_dir / "claim_summary.json").exists()
    claim_summary = json.loads((run_dir / "claim_summary.json").read_text(encoding="utf-8"))
    assert claim_summary["cross_claims"] == 1


def test_report_quality_check_writes_json_and_markdown(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    replay(run_dir)

    payload = evaluate_run_dir(run_dir)
    outputs = write_report_quality(run_dir)

    assert payload["counts"]["evidence"] == 1
    assert payload["counts"]["cross_claims"] == 1
    assert outputs["json"].exists()
    assert outputs["markdown"].exists()
    markdown = outputs["markdown"].read_text(encoding="utf-8")
    assert "Report Quality Check" in markdown
    assert "PASS report_exists" in markdown


def test_report_quality_fails_on_short_executive_summary(tmp_path: Path) -> None:
    """v0.3.1 Bug 9 回归:Executive Summary <100 字符应判 FAIL has_executive_summary。"""
    run_dir = _run_dir(tmp_path)
    # 把 Summary 改成 <100 字符
    (run_dir / "report.md").write_text(
        "# 竞品分析报告\n\n## Executive Summary\n\n太短了。\n\n"
        "## Cursor\n\n- claim text content here\n\n## Evidence Appendix\n",
        encoding="utf-8",
    )

    payload = evaluate_run_dir(run_dir)
    summary_checks = [c for c in payload["checks"] if c["name"] == "has_executive_summary"]
    assert summary_checks, "has_executive_summary check should be in output"
    assert summary_checks[0]["ok"] is False, (
        f"Short summary should FAIL, but got: {summary_checks[0]}"
    )
    # 详情应显示真实字数
    assert "summary_chars=" in summary_checks[0]["detail"]


def test_report_quality_competitor_placeholder_is_warning(tmp_path: Path) -> None:
    """v0.3.1 Bug 9 回归:竞品章节只含占位符时, mentions_competitor 应 FAIL。"""
    run_dir = _run_dir(tmp_path)
    # Cursor 章节用占位符填充
    (run_dir / "report.md").write_text(
        "# 竞品分析报告\n\n"
        "## Executive Summary\n\n"
        + ("这是一段足够长的总览,涵盖三家产品的差异点和定价对比内容。" * 3)
        + "\n\n"
        "## Cursor\n\n- (本竞品本轮未生成可信单项观察,详见跨竞品对比与待核实章节)\n\n"
        "## Windsurf\n\n- Windsurf has substantive content here.\n\n"
        "## Evidence Appendix\n",
        encoding="utf-8",
    )
    # competitors 来自 run_summary.json
    _write_json(
        run_dir / "run_summary.json",
        {"competitors": ["Cursor", "Windsurf"]},
    )

    payload = evaluate_run_dir(run_dir)
    cursor_check = next(
        (c for c in payload["checks"] if c["name"] == "mentions_competitor:Cursor"),
        None,
    )
    windsurf_check = next(
        (c for c in payload["checks"] if c["name"] == "mentions_competitor:Windsurf"),
        None,
    )
    assert cursor_check is not None
    assert cursor_check["ok"] is False, "Cursor placeholder section should FAIL"
    assert windsurf_check is not None
    assert windsurf_check["ok"] is True, "Windsurf with real content should PASS"


def test_claim_summary_has_new_generated_total_field(tmp_path: Path) -> None:
    """v0.3.1 Bug 6 回归:claim_summary 应新增 generated_total + accepted_count 字段。"""
    run_dir = _run_dir(tmp_path)
    # 加 discarded_claims
    _write_json(
        run_dir / "discarded_claims.json",
        [
            {
                "claim_id": "C-DROP1",
                "verdict": "fail",
                "support_score": 0.1,
                "evidence_ids": [],
                "statement": "weak claim",
            },
            {
                "claim_id": "C-DROP2",
                "verdict": "uncertain",
                "support_score": 0.4,
                "evidence_ids": [],
                "statement": "medium claim",
            },
        ],
    )
    replay(run_dir)

    claim_summary = json.loads(
        (run_dir / "claim_summary.json").read_text(encoding="utf-8")
    )
    # 新字段
    assert "generated_total" in claim_summary
    assert "accepted_count" in claim_summary
    # 2 accepted in claims.json + 2 discarded = 4 generated
    assert claim_summary["generated_total"] == 4
    # accepted_count == accepted == 2 (claims.json 里 2 条都 accepted=True 且 score>=0.3)
    assert claim_summary["accepted_count"] == 2
    # 老字段兼容
    assert claim_summary["accepted"] == 2
    assert claim_summary["discarded_total"] == 2
