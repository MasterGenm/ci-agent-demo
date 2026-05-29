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


def test_mock_dag_writes_v03_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ENABLE_GAP_FILL", "0")

    db_path = str(tmp_path / "cs_mvp.db")
    runs_dir = tmp_path / "runs"
    db.init_db(db_path)

    task = AnalysisTask(
        task_id="T-e2e",
        query="AI IDE",
        competitors=[CompetitorInput(name="Cursor"), CompetitorInput(name="Windsurf")],
    )
    run = AgentRun(run_id="RUN-e2e", task_id=task.task_id)
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
                evidence_id=f"E-{idx:03d}",
                source_id=source.source_id,
                competitor_name=source.competitor_name,
                claim_type="pricing",
                quote=f"{source.competitor_name} Pro costs $20 per month.",
                normalized_fact=f"{source.competitor_name} Pro costs $20/mo.",
                confidence=0.8,
            )
            for idx, source in enumerate(sources, start=1)
        ]
        return evidence, [], {
            "llm_cost_usd": 0.0,
            "model": "fake",
            "input_tokens": 0,
            "output_tokens": 0,
            "schema_pass_rate": 1.0,
            "quote_match_rate": 1.0,
            "duplicate_rate": 0.0,
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
        claims.append(
            AnalysisClaim(
                claim_id="C-CROSS-PRI",
                run_id=run_id,
                competitor_name=None,
                dimension="pricing",
                statement="Cursor Pro and Windsurf Pro both cost $20 per month.",
                evidence_ids=[item.evidence_id for item in evidence[:2]],
                confidence=0.8,
            )
        )
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
        "sources.json",
        "evidence.json",
        "claims.json",
        "qa_audit.json",
        "qa_summary.md",
        "trace.json",
        "run_summary.json",
        "claim_summary.json",
        "cost_summary.json",
    ]:
        assert (run_dir / filename).exists(), filename

    report = (run_dir / "report.md").read_text(encoding="utf-8")
    # Writer falls back to Chinese template when LLM is unavailable in test env
    assert "Cursor" in report
    assert len(report) > 100

    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    assert [item["node_name"] for item in trace["node_runs"]] == [
        "task_init",
        "collector",
        "extractor",
        "analyst",
        "qa_critic",
        "writer",
        "finalize",
    ]
    summary = db.get_run_summary(task.task_id)
    assert summary["run"]["status"] == "completed"
