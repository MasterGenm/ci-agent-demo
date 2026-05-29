from __future__ import annotations

import json
from pathlib import Path

from cs_mvp.artifacts import write_summary_artifacts
from cs_mvp.models import AnalysisTask, CompetitorInput


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _sample_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "T-test"
    run_dir.mkdir()
    (run_dir / "report.md").write_text(
        "# 竞品分析报告\n\n## Executive Summary\n\n摘要\n\n## Evidence Appendix\n",
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
                "raw_text_length": 1200,
            },
            {
                "source_id": "S-002",
                "competitor_name": "Windsurf",
                "url": "https://windsurf.com",
                "source_type": "pricing",
                "fetch_status": "failed",
                "failure_reason": "timeout",
                "raw_text_length": 0,
            },
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
                "confidence": 0.8,
            }
        ],
    )
    _write_json(
        run_dir / "claims.json",
        [
            {
                "claim_id": "C-001",
                "run_id": "RUN-1",
                "competitor_name": "Cursor",
                "dimension": "pricing",
                "statement": "Cursor Pro costs $20/mo.",
                "evidence_ids": ["E-001"],
                "support_score": 0.8,
                "accepted": True,
            },
            {
                "claim_id": "C-CROSS",
                "run_id": "RUN-1",
                "competitor_name": None,
                "dimension": "pricing",
                "statement": "Cursor and Windsurf differ in pricing.",
                "evidence_ids": ["E-001"],
                "support_score": 0.4,
                "accepted": True,
            },
        ],
    )
    _write_json(
        run_dir / "discarded_claims.json",
        [
            {
                "claim_id": "C-UNC",
                "statement": "weak",
                "evidence_ids": ["E-001"],
                "support_score": 0.4,
                "verdict": "uncertain",
            }
        ],
    )
    _write_json(
        run_dir / "extractor_stats.json",
        {
            "llm_cost_usd": 0.01,
            "max_cost_usd": 0.5,
            "model": "qwen-test",
            "input_tokens": 100,
            "output_tokens": 20,
        },
    )
    _write_json(
        run_dir / "analyst_stats.json",
        {
            "llm_cost_usd": 0.02,
            "model": "qwen-test",
            "input_tokens": 80,
            "output_tokens": 30,
        },
    )
    return run_dir


def test_write_summary_artifacts_creates_expected_files(tmp_path: Path) -> None:
    run_dir = _sample_run_dir(tmp_path)
    task = AnalysisTask(
        task_id="T-test",
        query="AI IDE",
        competitors=[CompetitorInput(name="Cursor"), CompetitorInput(name="Windsurf")],
    )
    node_runs = [
        {
            "node_name": "task_init",
            "status": "completed",
            "started_at": "2026-05-18T00:00:00",
            "ended_at": "2026-05-18T00:00:01",
            "latency_ms": 1000,
        },
        {
            "node_name": "extractor",
            "status": "completed",
            "started_at": "2026-05-18T00:00:01",
            "ended_at": "2026-05-18T00:00:02",
            "latency_ms": 1000,
            "llm_model": "qwen-test",
            "input_tokens": 100,
            "output_tokens": 20,
            "cost_usd": 0.01,
        },
    ]

    paths = write_summary_artifacts(
        run_dir,
        task=task,
        run_id="RUN-1",
        node_runs=node_runs,
    )

    expected = {
        "run_summary.json",
        "node_summary.json",
        "cost_summary.json",
        "claim_summary.json",
        "source_summary.json",
        "evidence_summary.json",
    }
    assert set(paths) == expected
    for name in expected:
        assert (run_dir / name).exists()
        json.loads((run_dir / name).read_text(encoding="utf-8"))

    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    claim_summary = json.loads((run_dir / "claim_summary.json").read_text(encoding="utf-8"))
    source_summary = json.loads((run_dir / "source_summary.json").read_text(encoding="utf-8"))
    cost_summary = json.loads((run_dir / "cost_summary.json").read_text(encoding="utf-8"))

    assert run_summary["task_id"] == "T-test"
    assert run_summary["run_id"] == "RUN-1"
    assert run_summary["competitors"] == ["Cursor", "Windsurf"]
    assert run_summary["quality_gates"]["has_report"] is True
    assert claim_summary["total_claims"] == 2
    assert claim_summary["cross_claims"] == 1
    assert source_summary["total"] == 2
    assert source_summary["valid"] == 1
    assert cost_summary["total_cost_usd"] >= 0.01
    # v0.3.1 回归:by_model 总和应等于 by_node 总和(不能因 stats 文件二次累加翻倍)
    by_model_total = sum(cost_summary["by_model"].values())
    by_node_total = sum(cost_summary["by_node"].values())
    assert abs(by_model_total - by_node_total) < 1e-6, (
        f"by_model sum {by_model_total} != by_node sum {by_node_total} "
        "(cost double-counting regression)"
    )


def test_query_fallback_from_report_md_when_task_missing(tmp_path: Path) -> None:
    """v0.3.1 回归:replay 场景下没有 task 参数,query 应能从 report.md 头部解析。"""
    run_dir = tmp_path / "T-replay"
    run_dir.mkdir()
    # 模拟一份真实 report.md(replay 时 task 已不可用)
    (run_dir / "report.md").write_text(
        "# 竞品分析报告\n\n"
        "**调研问题**:AI 笔记与个人知识管理工具竞品分析\n"
        "**竞品范围**:Notion / Evernote / Mem\n\n"
        "## Executive Summary\n\n摘要\n\n"
        "## Evidence Appendix\n",
        encoding="utf-8",
    )
    _write_json(run_dir / "sources.json", [])
    _write_json(run_dir / "evidence.json", [])
    _write_json(run_dir / "claims.json", [])
    _write_json(run_dir / "discarded_claims.json", [])

    # 不传 task!模拟 replay 脚本场景
    write_summary_artifacts(run_dir)

    run_summary = json.loads(
        (run_dir / "run_summary.json").read_text(encoding="utf-8")
    )
    assert run_summary["query"] == "AI 笔记与个人知识管理工具竞品分析"
