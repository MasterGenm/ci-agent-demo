from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cs_mvp.artifacts import export_html_report, write_summary_artifacts
from cs_mvp.cli import app


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "T-html"
    run_dir.mkdir()
    (run_dir / "report.md").write_text(
        "# 竞品分析报告\n\n## Executive Summary\n\nCursor summary [E-001]\n\n## Evidence Appendix\n",
        encoding="utf-8",
    )
    _write_json(
        run_dir / "sources.json",
        [
            {
                "source_id": "S-001",
                "competitor_name": "Cursor",
                "url": "https://cursor.com/pricing",
                "title": "Cursor Pricing",
                "source_type": "pricing",
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
                "claim_type": "pricing",
                "quote": "Cursor Pro costs $20 per month.",
                "normalized_fact": "Cursor Pro costs $20/mo.",
            }
        ],
    )
    _write_json(
        run_dir / "claims.json",
        [
            {
                "claim_id": "C-001",
                "competitor_name": "Cursor",
                "dimension": "pricing",
                "statement": "Cursor Pro costs $20/mo.",
                "evidence_ids": ["E-001"],
                "support_score": 0.8,
                "accepted": True,
            }
        ],
    )
    _write_json(run_dir / "discarded_claims.json", [])
    write_summary_artifacts(run_dir)
    return run_dir


def test_export_html_report_writes_static_file(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)

    output = export_html_report(run_dir)
    html = output.read_text(encoding="utf-8")

    assert output.name == "report.html"
    assert "<!doctype html>" in html
    assert "Executive Summary" in html
    # HTML 用 <details> 块渲染 evidence,不再保留 "Evidence Appendix" 标题
    # (markdown body 里的 ## Evidence Appendix 段被 _strip_evidence_appendix 去除)
    assert "Evidence Details" in html
    assert "https://cursor.com/pricing" in html
    assert "<details" in html
    assert 'href="#E-001"' in html


def test_export_html_no_blockquote_corruption(tmp_path: Path) -> None:
    """v0.3.1 回归:markdown `> quote` 转 HTML 时不应留下 `t;` 残留字符。

    曾经因为先 html.escape(`>`→`&gt;`) 再切前 2 字符,导致 blockquote 内文以 `t;` 开头。
    """
    run_dir = _run_dir(tmp_path)
    # 在 report.md 里加一段带 blockquote 的内容
    (run_dir / "report.md").write_text(
        "# 竞品分析报告\n\n"
        "## Executive Summary\n\n"
        "Cursor summary [E-001]\n\n"
        "> 这是一段引用 quote 文本\n\n"
        "## Evidence Appendix\n",
        encoding="utf-8",
    )
    write_summary_artifacts(run_dir)
    output = export_html_report(run_dir)
    html = output.read_text(encoding="utf-8")

    # blockquote 应正确渲染,内文不应以 t; 开头
    assert "<blockquote>这是一段引用 quote 文本</blockquote>" in html
    # v0.1 老 bug:html.escape(`>`→`&gt;`) 后切前 2 字符,导致 blockquote 内文出现 `<blockquote>t; `
    assert "<blockquote>t;" not in html


def test_export_html_no_double_bold(tmp_path: Path) -> None:
    """v0.3.1 回归:markdown `**xxx**` 转 HTML 不应同时保留字面 `**` 又包 `<strong>`。"""
    run_dir = _run_dir(tmp_path)
    (run_dir / "report.md").write_text(
        "# 竞品分析报告\n\n"
        "**调研问题**:AI 笔记赛道\n\n"
        "## Executive Summary\n\nCursor summary [E-001]\n\n"
        "## Evidence Appendix\n",
        encoding="utf-8",
    )
    write_summary_artifacts(run_dir)
    output = export_html_report(run_dir)
    html = output.read_text(encoding="utf-8")

    # 应该有 <strong>调研问题</strong>,不应有 **调研问题** 字面字符
    assert "<strong>调研问题</strong>" in html
    assert "**调研问题**" not in html


def test_export_html_no_duplicate_evidence_appendix(tmp_path: Path) -> None:
    """v0.3.1 回归:Evidence Appendix 段不应被同时渲染为 markdown 段和 details 块。"""
    run_dir = _run_dir(tmp_path)
    output = export_html_report(run_dir)
    html = output.read_text(encoding="utf-8")

    # markdown body 里不应有 <h2>Evidence Appendix</h2>(被 strip 掉)
    assert "<h2>Evidence Appendix</h2>" not in html
    # 但应该有独立 section 的 Evidence Details
    assert "<h2>Evidence Details</h2>" in html


def test_export_html_cli_uses_configured_runs_dir(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _run_dir(runs_dir)

    settings = type(
        "Settings",
        (),
        {"db_path": str(tmp_path / "db.sqlite"), "runs_dir": str(runs_dir)},
    )()

    monkeypatch.setattr("cs_mvp.cli.load_settings", lambda: settings)
    result = CliRunner().invoke(app, ["export-html", "--task-id", "T-html"])

    assert result.exit_code == 0
    assert "report.html" in result.output
    assert (runs_dir / "T-html" / "report.html").exists()
