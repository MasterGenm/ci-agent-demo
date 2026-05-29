from __future__ import annotations

from cs_mvp.models import (
    AgentNodeRun,
    AgentRun,
    AnalysisClaim,
    AnalysisTask,
    CompetitorInput,
    DiscardedClaim,
    EvidenceItem,
    GraphState,
    Report,
    SourceRecord,
    TaskScope,
)


def test_models_can_be_instantiated() -> None:
    competitor = CompetitorInput(name="Cursor")
    task = AnalysisTask(task_id="T-1", query="AI IDE", competitors=[competitor])
    run = AgentRun(run_id="RUN-1", task_id=task.task_id)
    node_run = AgentNodeRun(
        node_run_id="NR-1",
        run_id=run.run_id,
        node_name="collector",
    )
    source = SourceRecord(
        source_id="S-001",
        run_id=run.run_id,
        competitor_name="Cursor",
        url="https://example.com",
    )
    evidence = EvidenceItem(
        evidence_id="E-001",
        source_id=source.source_id,
        competitor_name="Cursor",
        quote="Cursor Pro costs $20/month.",
    )
    claim = AnalysisClaim(
        claim_id="C-001",
        run_id=run.run_id,
        competitor_name="Cursor",
        dimension="pricing",
        statement="Cursor Pro costs $20/month.",
        evidence_ids=[evidence.evidence_id],
    )
    discarded = DiscardedClaim(
        claim_id=claim.claim_id,
        statement=claim.statement,
        evidence_ids=claim.evidence_ids,
        support_score=0.1,
        verdict="fail",
        reason="missing evidence",
    )
    report = Report(
        report_id="R-1",
        run_id=run.run_id,
        format="md",
        file_path="runs/T-1/report.md",
    )

    assert TaskScope().language == "zh-CN"
    assert task.competitors[0].name == "Cursor"
    assert node_run.status == "pending"
    assert source.source_type == "other"
    assert evidence.evidence_id == "E-001"
    assert claim.accepted is True
    assert discarded.verdict == "fail"
    assert report.format == "md"


def test_graph_state_serialization_round_trip() -> None:
    task = AnalysisTask(
        task_id="T-1",
        query="AI IDE",
        competitors=[CompetitorInput(name="Cursor")],
    )
    state = GraphState(task=task, run_id="RUN-1")
    encoded = state.model_dump_json()
    decoded = GraphState.model_validate_json(encoded)

    assert decoded.task.task_id == "T-1"
    assert decoded.task.competitors[0].name == "Cursor"
    assert decoded.sources == []
