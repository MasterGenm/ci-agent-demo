from __future__ import annotations

import json
from pathlib import Path

from cs_mvp import db
from cs_mvp.graph import build_graph
from cs_mvp.models import (
    AgentRun,
    AnalysisClaim,
    AnalysisTask,
    CompetitorInput,
    EvidenceItem,
    GraphState,
    SourceRecord,
)


def test_graph_writes_pm_report_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ENABLE_QA_CRITIC", "0")
    monkeypatch.setenv("ENABLE_REVISION_LOOP", "0")

    db_path = str(tmp_path / "cs_mvp.db")
    runs_dir = tmp_path / "runs"
    db.init_db(db_path)

    task = AnalysisTask(
        task_id="T-pm-export",
        query="AI IDE",
        competitors=[CompetitorInput(name="Cursor"), CompetitorInput(name="Windsurf")],
    )
    run = AgentRun(run_id="RUN-pm-export", task_id=task.task_id)
    db.insert_task(task)
    db.insert_run(run)

    def fake_collect(run_id: str, competitor_name: str, query: str, **kwargs):
        return [
            SourceRecord(
                source_id=f"S-{competitor_name[:3].upper()}-001",
                run_id=run_id,
                competitor_name=competitor_name,
                url=f"https://{competitor_name.lower()}.example/pricing",
                title=f"{competitor_name} Pricing",
                source_type="pricing",
                fetch_status="fetched",
                content_hash=f"hash-{competitor_name}",
                raw_text=f"{competitor_name} Pro costs $20 per month. " * 40,
                raw_text_length=1200,
            )
        ]

    def fake_extract(run_id: str, sources: list[SourceRecord], **kwargs):
        evidence = [
            EvidenceItem(
                evidence_id=f"E-{index:03d}",
                source_id=source.source_id,
                competitor_name=source.competitor_name,
                claim_type="pricing",
                quote=f"{source.competitor_name} Pro costs $20 per month.",
                confidence=0.8,
            )
            for index, source in enumerate(sources, start=1)
        ]
        return evidence, [], {
            "llm_cost_usd": 0.0,
            "model": "fake",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    def fake_analyze(run_id: str, evidence: list[EvidenceItem], competitor_names: list[str], **kwargs):
        claims = [
            AnalysisClaim(
                claim_id=f"C-{item.competitor_name}-PRI",
                run_id=run_id,
                competitor_name=item.competitor_name,
                dimension="pricing",
                statement=f"{item.competitor_name} Pro costs $20 per month.",
                evidence_ids=[item.evidence_id],
                confidence=0.8,
            )
            for item in evidence
        ]
        return claims, [], {
            "llm_cost_usd": 0.0,
            "model": "fake",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    monkeypatch.setattr("cs_mvp.graph.real_collect", fake_collect)
    monkeypatch.setattr("cs_mvp.graph.real_extract", fake_extract)
    monkeypatch.setattr("cs_mvp.graph.real_analyze", fake_analyze)

    graph = build_graph(db_path, str(runs_dir))
    graph.invoke(
        GraphState(task=task, run_id=run.run_id).model_dump(mode="json"),
        config={"configurable": {"thread_id": task.task_id}},
    )

    run_dir = runs_dir / task.task_id
    for filename in [
        "report.md",
        "report_context.json",
        "report_plan.json",
        "evidence_digest.json",
        "report_pm.md",
        "report_pm.html",
        "report_pm_summary.json",
        "report_style_audit.json",
        "report_style_audit.md",
    ]:
        assert (run_dir / filename).exists(), filename

    pm_report = (run_dir / "report_pm.md").read_text(encoding="utf-8")
    assert "# 竞品分析简报" in pm_report
    assert "## 2. 竞品对比矩阵" in pm_report
    assert "Cursor" in pm_report
    assert "Windsurf" in pm_report

    summary = json.loads((run_dir / "report_pm_summary.json").read_text(encoding="utf-8"))
    assert summary["report_type"] == "pm"
    assert summary["section_count"] == 7
    assert summary["competitor_count"] == 2
    audit = json.loads((run_dir / "report_style_audit.json").read_text(encoding="utf-8"))
    assert audit["report_type"] == "pm"
    assert audit["score"]["overall_score"] >= 0
