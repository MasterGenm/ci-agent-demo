from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cs_mvp import db
from cs_mvp.agents.qa_critic import (
    audit_run,
    critic_one_claim,
    render_qa_summary_md,
)
from cs_mvp.graph import build_graph
from cs_mvp.models import (
    AgentRun,
    AnalysisClaim,
    AnalysisTask,
    CompetitorInput,
    EvidenceItem,
    GraphState,
    QAFeedback,
    SourceRecord,
)
from cs_mvp.review_queue import build_review_queue


class _MockLLM:
    model = "qwen3.6-plus"

    def __init__(self, responses: str | list[str]):
        self._responses = [responses] if isinstance(responses, str) else list(responses)
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self._responses) - 1)
        return SimpleNamespace(
            content=self._responses[index],
            response_metadata={
                "token_usage": {"prompt_tokens": 120, "completion_tokens": 30}
            },
        )


def _claim(claim_id: str = "C-1", *, statement: str | None = None) -> AnalysisClaim:
    return AnalysisClaim(
        claim_id=claim_id,
        run_id="RUN-1",
        competitor_name="Notion",
        dimension="features",
        statement=statement or "Notion AI supports search across notes.",
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


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_qa_critic_disabled_by_flag_preserves_old_graph_topology(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_QA_CRITIC", "0")
    monkeypatch.setenv("ENABLE_GAP_FILL", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    db_path = str(tmp_path / "cs_mvp.db")
    runs_dir = tmp_path / "runs"
    db.init_db(db_path)

    task = AnalysisTask(
        task_id="T-qa-off",
        query="AI notes",
        competitors=[CompetitorInput(name="Notion")],
    )
    run = AgentRun(run_id="RUN-qa-off", task_id=task.task_id)
    db.insert_task(task)
    db.insert_run(run)

    def fail_qa_critic(_state):
        raise AssertionError("qa_critic should not be in the disabled graph")

    def fake_collect(run_id: str, competitor_name: str, query: str, **kwargs):
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

    def fake_extract(run_id: str, sources: list[SourceRecord], **kwargs):
        return [_evidence()], [], {
            "llm_cost_usd": 0.0,
            "model": "fake",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    def fake_analyze(run_id: str, evidence: list[EvidenceItem], competitor_names: list[str], **kwargs):
        return [_claim()], [], {
            "llm_cost_usd": 0.0,
            "model": "fake",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    monkeypatch.setattr("cs_mvp.graph.node_qa_critic", fail_qa_critic)
    monkeypatch.setattr("cs_mvp.graph.real_collect", fake_collect)
    monkeypatch.setattr("cs_mvp.graph.real_extract", fake_extract)
    monkeypatch.setattr("cs_mvp.graph.real_analyze", fake_analyze)

    graph = build_graph(db_path, str(runs_dir))
    graph.invoke(
        GraphState(task=task, run_id=run.run_id).model_dump(mode="json"),
        config={"configurable": {"thread_id": task.task_id}},
    )

    run_dir = runs_dir / task.task_id
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    assert [item["node_name"] for item in trace["node_runs"]] == [
        "task_init",
        "collector",
        "extractor",
        "analyst",
        "writer",
        "finalize",
    ]
    assert not (run_dir / "qa_audit.json").exists()


def test_critic_one_claim_accepted() -> None:
    llm = _MockLLM(
        '{"label":"accepted","reason":"Evidence directly supports the claim.","issue_tags":[],"suggested_revision":null}'
    )

    feedback, cost = critic_one_claim(_claim(), {"E-1": _evidence()}, llm)

    assert feedback == QAFeedback(
        claim_id="C-1",
        label="accepted",
        reason="Evidence directly supports the claim.",
        issue_tags=[],
        suggested_revision=None,
    )
    assert cost > 0


def test_critic_one_claim_needs_revision_with_tags() -> None:
    llm = _MockLLM(
        '{"label":"needs_revision","reason":"The claim infers product intent not stated in evidence.","issue_tags":["interpretive_drift"],"suggested_revision":"Remove the intent wording."}'
    )

    feedback, _cost = critic_one_claim(_claim(), {"E-1": _evidence()}, llm)

    assert feedback.label == "needs_revision"
    assert feedback.issue_tags == ["interpretive_drift"]
    assert feedback.suggested_revision == "Remove the intent wording."


def test_critic_one_claim_invalid_label_falls_back_to_risky() -> None:
    llm = _MockLLM(
        [
            '{"label":"unsupported","reason":"bad","issue_tags":[],"suggested_revision":null}',
            '{"label":"unsupported","reason":"still bad","issue_tags":[],"suggested_revision":null}',
        ]
    )

    feedback, _cost = critic_one_claim(_claim(), {"E-1": _evidence()}, llm)

    assert feedback.label == "risky"
    assert feedback.reason == "qa_judge_failed"
    assert len(llm.prompts) == 2


def test_critic_one_claim_invalid_issue_tag_filtered() -> None:
    llm = _MockLLM(
        '{"label":"risky","reason":"Scope is unclear.","issue_tags":["scope_ambiguity","made_up_tag"],"suggested_revision":null}'
    )

    feedback, _cost = critic_one_claim(_claim(), {"E-1": _evidence()}, llm)

    assert feedback.label == "risky"
    assert feedback.issue_tags == ["scope_ambiguity"]


def test_audit_run_counts() -> None:
    claims = [_claim("C-1"), _claim("C-2"), _claim("C-3")]
    llm = _MockLLM(
        [
            '{"label":"accepted","reason":"Supported.","issue_tags":[],"suggested_revision":null}',
            '{"label":"needs_revision","reason":"Overreach.","issue_tags":["weak_evidence_alignment"],"suggested_revision":null}',
            '{"label":"risky","reason":"Borderline.","issue_tags":["scope_ambiguity"],"suggested_revision":null}',
        ]
    )

    audit = audit_run(claims, [_evidence()], "RUN-1", llm=llm)

    assert audit.total_claims_audited == 3
    assert audit.accepted_count == 1
    assert audit.needs_revision_count == 1
    assert audit.risky_count == 1
    assert audit.auditor_model == "qwen3.6-plus"
    assert audit.llm_cost_usd > 0


def test_audit_run_llm_init_failure_returns_empty_audit(monkeypatch) -> None:
    def fail_init():
        raise RuntimeError("missing key")

    monkeypatch.setattr("cs_mvp.agents.qa_critic.get_extractor_llm", fail_init)

    audit = audit_run([_claim()], [_evidence()], "RUN-1")

    assert audit.total_claims_audited == 0
    assert audit.feedbacks == []
    assert audit.notes == "llm_init_failed:RuntimeError"


def test_review_queue_includes_qa_critic_entries(tmp_path: Path) -> None:
    run_dir = tmp_path / "T-review"
    run_dir.mkdir()
    _write_json(
        run_dir / "claims.json",
        [
            {
                "claim_id": "C-1",
                "competitor_name": "Notion",
                "dimension": "features",
                "statement": "Notion AI supports search across notes.",
                "evidence_ids": ["E-1"],
            }
        ],
    )
    _write_json(
        run_dir / "discarded_claims.json",
        [
            {
                "claim_id": "C-2",
                "statement": "Notion AI has unclear strategic intent.",
                "evidence_ids": ["E-1"],
                "support_score": 0.4,
                "verdict": "uncertain",
            }
        ],
    )
    _write_json(
        run_dir / "evidence.json",
        [{"evidence_id": "E-1", "competitor_name": "Notion"}],
    )
    _write_json(run_dir / "sources.json", [])
    _write_json(run_dir / "extractor_failures.json", [])
    _write_json(run_dir / "run_summary.json", {"quality_gates": {"low_recall_competitors": []}})
    _write_json(
        run_dir / "qa_audit.json",
        {
            "feedbacks": [
                {
                    "claim_id": "C-1",
                    "label": "needs_revision",
                    "reason": "Evidence does not support intent wording.",
                    "issue_tags": ["interpretive_drift"],
                },
                {
                    "claim_id": "C-2",
                    "label": "risky",
                    "reason": "Borderline support.",
                    "issue_tags": ["scope_ambiguity"],
                },
            ]
        },
    )

    queue = build_review_queue(run_dir)
    qa_entries = [entry for entry in queue if entry["type"] == "qa_critic"]

    assert [entry["qa_label"] for entry in qa_entries] == ["needs_revision", "risky"]
    assert qa_entries[0]["severity"] == "warning"
    assert qa_entries[0]["competitor_name"] == "Notion"
    assert qa_entries[1]["severity"] == "info"


def test_render_qa_summary_includes_needs_revision_section() -> None:
    audit = audit_run(
        [_claim()],
        [_evidence()],
        "RUN-1",
        llm=_MockLLM(
            '{"label":"needs_revision","reason":"Intent wording is unsupported.","issue_tags":["interpretive_drift"],"suggested_revision":null}'
        ),
    )

    summary = render_qa_summary_md(audit, {"C-1": _claim()})

    assert "## Needs Revision (1)" in summary
    assert "Intent wording is unsupported." in summary
