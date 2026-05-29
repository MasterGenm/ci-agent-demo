from __future__ import annotations

import json
from pathlib import Path

from cs_mvp import db
from cs_mvp.agents.analyst_revise import revise_claim, run_revision_round
from cs_mvp.graph import _route_after_qa_critic, build_graph
from cs_mvp.models import (
    AgentRun,
    AnalysisClaim,
    AnalysisTask,
    CompetitorInput,
    EvidenceItem,
    GraphState,
    QAAudit,
    QAFeedback,
    RevisionRecord,
    SourceRecord,
)


class _StructuredLLM:
    model = "fake-reviser"

    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    def with_structured_output(self, _schema, **kwargs):
        return self

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _task(task_id: str = "T-revision") -> AnalysisTask:
    return AnalysisTask(
        task_id=task_id,
        query="AI notes",
        competitors=[CompetitorInput(name="Notion")],
    )


def _claim(claim_id: str = "C-1", *, label_subject: str = "Notion") -> AnalysisClaim:
    return AnalysisClaim(
        claim_id=claim_id,
        run_id="RUN-1",
        competitor_name=label_subject,
        dimension="features",
        statement=f"{label_subject} aims to simplify knowledge work with AI search.",
        evidence_ids=["E-1"],
        confidence=0.8,
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="E-1",
        source_id="S-1",
        competitor_name="Notion",
        claim_type="feature",
        quote="Notion AI supports search across notes.",
        normalized_fact="Notion AI supports note search.",
        confidence=0.8,
    )


def _feedback(
    claim_id: str = "C-1",
    *,
    label: str = "needs_revision",
) -> QAFeedback:
    return QAFeedback(
        claim_id=claim_id,
        label=label,  # type: ignore[arg-type]
        reason="Intent wording is not supported by evidence.",
        issue_tags=["interpretive_drift"],
        suggested_revision="Notion AI supports search across notes.",
        revision_instruction="Use only E-1 and remove intent wording.",
    )


def test_revision_loop_disabled_by_flag_omits_graph_node(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_QA_CRITIC", "1")
    monkeypatch.setenv("ENABLE_REVISION_LOOP", "0")
    db_path = str(tmp_path / "cs_mvp.db")
    db.init_db(db_path)

    graph = build_graph(db_path, str(tmp_path / "runs"))

    assert "analyst_revise" not in graph.get_graph().nodes


def test_qa_critic_produces_revision_instruction() -> None:
    feedback = QAFeedback(
        claim_id="C-1",
        label="needs_revision",
        reason="Overreach.",
        suggested_revision="Narrow the claim.",
        revision_instruction="Use only E-1.",
    )

    assert feedback.revision_instruction == "Use only E-1."


def test_revise_claim_respects_evidence_whitelist() -> None:
    llm = _StructuredLLM(
        {
            "revised_statement": "Notion AI supports search across notes.",
            "kept_evidence_ids": ["E-1", "E-outside"],
            "revision_explanation": "Removed unsupported intent wording.",
            "revision_failed": False,
            "failure_reason": None,
        }
    )

    revised, record, _cost = revise_claim(
        _claim(),
        _feedback(),
        {"E-1": _evidence()},
        llm=llm,
    )

    assert revised is None
    assert record.revision_failed is True
    assert "invalid_evidence_ids" in (record.failure_reason or "")


def test_revise_claim_preserves_dimension_and_competitor() -> None:
    llm = _StructuredLLM(
        {
            "revised_statement": "Notion AI supports search across notes.",
            "kept_evidence_ids": ["E-1"],
            "revision_explanation": "Removed unsupported intent wording.",
            "revision_failed": False,
            "failure_reason": None,
        }
    )

    revised, record, _cost = revise_claim(
        _claim(),
        _feedback(),
        {"E-1": _evidence()},
        llm=llm,
    )

    assert revised is not None
    assert revised.dimension == "features"
    assert revised.competitor_name == "Notion"
    assert revised.evidence_ids == ["E-1"]
    assert record.revised_statement == "Notion AI supports search across notes."


def test_revise_claim_failure_keeps_original_available() -> None:
    llm = _StructuredLLM(RuntimeError("transport failed"))

    revised, record, _cost = revise_claim(
        _claim(),
        _feedback(),
        {"E-1": _evidence()},
        llm=llm,
    )

    assert revised is None
    assert record.revised_statement == _claim().statement
    assert record.revised_evidence_ids == ["E-1"]
    assert record.revision_failed is True


def test_run_revision_round_only_processes_needs_revision() -> None:
    llm = _StructuredLLM(
        {
            "revised_statement": "Notion AI supports search across notes.",
            "kept_evidence_ids": ["E-1"],
            "revision_explanation": "Removed unsupported intent wording.",
            "revision_failed": False,
            "failure_reason": None,
        }
    )

    revised, records, _cost = run_revision_round(
        [_claim("C-1"), _claim("C-2")],
        [_feedback("C-1", label="needs_revision"), _feedback("C-2", label="risky")],
        [_evidence()],
        revision_round=1,
        llm=llm,
    )

    assert [claim.claim_id for claim in revised] == ["C-1"]
    assert [record.claim_id for record in records] == ["C-1"]


def test_conditional_edge_routes_to_revise_when_needs_revision(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_QA_CRITIC", "1")
    monkeypatch.setenv("ENABLE_REVISION_LOOP", "1")
    state = GraphState(
        task=_task(),
        run_id="RUN-1",
        qa_audit={
            "feedbacks": [_feedback().model_dump(mode="json")],
        },
        revision_round=0,
    )

    assert _route_after_qa_critic(state) == "analyst_revise"


def test_conditional_edge_routes_to_writer_when_round_exhausted(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_QA_CRITIC", "1")
    monkeypatch.setenv("ENABLE_REVISION_LOOP", "1")
    state = GraphState(
        task=_task(),
        run_id="RUN-1",
        qa_audit={
            "feedbacks": [_feedback().model_dump(mode="json")],
        },
        revision_round=1,
    )

    assert _route_after_qa_critic(state) == "writer"


def test_conditional_edge_routes_to_writer_when_no_needs_revision(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_QA_CRITIC", "1")
    monkeypatch.setenv("ENABLE_REVISION_LOOP", "1")
    state = GraphState(
        task=_task(),
        run_id="RUN-1",
        qa_audit={
            "feedbacks": [_feedback(label="accepted").model_dump(mode="json")],
        },
        revision_round=0,
    )

    assert _route_after_qa_critic(state) == "writer"


def test_revision_history_json_schema_with_mock_graph(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_QA_CRITIC", "1")
    monkeypatch.setenv("ENABLE_REVISION_LOOP", "1")
    monkeypatch.setenv("ENABLE_GAP_FILL", "0")
    db_path = str(tmp_path / "cs_mvp.db")
    runs_dir = tmp_path / "runs"
    db.init_db(db_path)

    task = _task("T-loop")
    run = AgentRun(run_id="RUN-loop", task_id=task.task_id)
    db.insert_task(task)
    db.insert_run(run)

    def fake_collect(run_id: str, competitor_name: str, query: str, **_kwargs):
        return [
            SourceRecord(
                source_id="S-1",
                run_id=run_id,
                competitor_name=competitor_name,
                url="https://notion.example",
                fetch_status="fetched",
                raw_text="Notion AI supports search across notes. " * 40,
                raw_text_length=1600,
            )
        ]

    def fake_extract(run_id: str, sources: list[SourceRecord], **_kwargs):
        return [_evidence()], [], {
            "llm_cost_usd": 0.0,
            "model": "fake",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    def fake_analyze(run_id: str, evidence: list[EvidenceItem], competitor_names: list[str], **_kwargs):
        claim = _claim()
        claim.run_id = run_id
        return [claim], [], {
            "llm_cost_usd": 0.0,
            "model": "fake",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    audit_calls = {"count": 0}

    def fake_audit_run(claims, evidence, run_id, rescue_outcomes=None, llm=None):
        audit_calls["count"] += 1
        label = "needs_revision" if audit_calls["count"] == 1 else "accepted"
        return QAAudit(
            run_id=run_id,
            total_claims_audited=1,
            accepted_count=1 if label == "accepted" else 0,
            needs_revision_count=1 if label == "needs_revision" else 0,
            risky_count=0,
            feedbacks=[_feedback(claims[0].claim_id, label=label)],
            auditor_model="fake",
            llm_cost_usd=0.0,
        )

    def fake_revision_round(claims, feedbacks, evidence, revision_round, llm=None):
        revised = claims[0].model_copy(
            update={"statement": "Notion AI supports search across notes."}
        )
        record = RevisionRecord(
            claim_id=claims[0].claim_id,
            revision_round=revision_round,
            original_statement=claims[0].statement,
            original_evidence_ids=claims[0].evidence_ids,
            qa_label_before="needs_revision",
            qa_reason=feedbacks[0].reason,
            qa_issue_tags=feedbacks[0].issue_tags,
            suggested_revision=feedbacks[0].suggested_revision,
            revision_instruction=feedbacks[0].revision_instruction,
            revised_statement=revised.statement,
            revised_evidence_ids=revised.evidence_ids,
            revision_explanation="Removed unsupported intent wording.",
            qa_label_after="needs_revision",
            max_revision_reached=False,
        )
        return [revised], [record], 0.0

    monkeypatch.setattr("cs_mvp.graph.real_collect", fake_collect)
    monkeypatch.setattr("cs_mvp.graph.real_extract", fake_extract)
    monkeypatch.setattr("cs_mvp.graph.real_analyze", fake_analyze)
    monkeypatch.setattr("cs_mvp.agents.qa_critic.audit_run", fake_audit_run)
    monkeypatch.setattr(
        "cs_mvp.agents.analyst_revise.run_revision_round",
        fake_revision_round,
    )

    graph = build_graph(db_path, str(runs_dir))
    graph.invoke(
        GraphState(task=task, run_id=run.run_id).model_dump(mode="json"),
        config={"configurable": {"thread_id": task.task_id}},
    )

    run_dir = runs_dir / task.task_id
    history = json.loads((run_dir / "revision_history.json").read_text(encoding="utf-8"))
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    node_names = [item["node_name"] for item in trace["node_runs"]]

    assert node_names == [
        "task_init",
        "collector",
        "extractor",
        "analyst",
        "qa_critic",
        "analyst_revise",
        "qa_critic",
        "writer",
        "finalize",
    ]
    assert history["total_revisions"] == 1
    assert history["max_revision_rounds"] == 1
    assert history["revisions"][0]["qa_label_after"] == "accepted"
    assert history["revisions"][0]["max_revision_reached"] is False
    assert (run_dir / "revision_summary.md").exists()
