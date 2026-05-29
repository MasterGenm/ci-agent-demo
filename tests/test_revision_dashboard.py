from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cs_mvp.agents.writer import render_report
from cs_mvp.models import AnalysisClaim, AnalysisTask, CompetitorInput, EvidenceItem
from cs_mvp.review_queue import build_review_queue
from cs_mvp.web.app import fastapi_app
from cs_mvp.web.services.artifact_reader import get_revision_history


REVISION_TASK = "T-revision-dashboard"
LEGACY_TASK = "T-revision-legacy"


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def revision_runs(tmp_path: Path, monkeypatch) -> Path:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cs_mvp.db"))

    legacy = runs_dir / LEGACY_TASK
    legacy.mkdir()
    _write_json(
        legacy / "run_summary.json",
        {
            "task_id": LEGACY_TASK,
            "run_id": "RUN-legacy",
            "query": "Legacy run",
            "competitors": ["Notion"],
            "status": "completed",
        },
    )
    _write_json(legacy / "claims.json", [])
    _write_json(legacy / "evidence.json", [])
    _write_json(legacy / "sources.json", [])
    _write_json(
        legacy / "trace.json",
        {
            "node_runs": [
                {"node_name": name, "status": "completed", "latency_ms": 1}
                for name in [
                    "task_init",
                    "collector",
                    "extractor",
                    "analyst",
                    "writer",
                    "finalize",
                ]
            ]
        },
    )
    (legacy / "report.md").write_text("# Legacy\n", encoding="utf-8")

    run = runs_dir / REVISION_TASK
    run.mkdir()
    _write_json(
        run / "run_summary.json",
        {
            "task_id": REVISION_TASK,
            "run_id": "RUN-loop",
            "query": "AI notes revision run",
            "competitors": ["Notion"],
            "status": "completed",
            "duration_seconds": 12.3,
        },
    )
    _write_json(
        run / "claims.json",
        [
            {
                "claim_id": "C-1",
                "competitor_name": "Notion",
                "dimension": "features",
                "statement": "Notion AI supports search across notes.",
                "evidence_ids": ["E-1"],
                "accepted": True,
            }
        ],
    )
    _write_json(run / "discarded_claims.json", [])
    _write_json(
        run / "evidence.json",
        [
            {
                "evidence_id": "E-1",
                "source_id": "S-1",
                "competitor_name": "Notion",
                "claim_type": "feature",
                "quote": "Notion AI supports search across notes.",
            }
        ],
    )
    _write_json(
        run / "sources.json",
        [{"source_id": "S-1", "url": "https://notion.example", "title": "Notion"}],
    )
    _write_json(
        run / "qa_audit.json",
        {
            "schema_version": "1.2.0",
            "run_id": "RUN-loop",
            "total_claims_audited": 1,
            "accepted_count": 1,
            "needs_revision_count": 0,
            "risky_count": 0,
            "llm_cost_usd": 0.0,
            "feedbacks": [
                {
                    "claim_id": "C-1",
                    "label": "accepted",
                    "reason": "Revised claim is evidence-bounded.",
                    "issue_tags": [],
                    "suggested_revision": None,
                    "revision_instruction": None,
                }
            ],
        },
    )
    _write_json(
        run / "revision_history.json",
        {
            "run_id": "RUN-loop",
            "schema_version": "1.2.0",
            "total_revisions": 1,
            "max_revision_rounds": 1,
            "revision_round": 1,
            "total_revise_cost_usd": 0.0004,
            "revisions": [
                {
                    "claim_id": "C-1",
                    "revision_round": 1,
                    "original_statement": "Notion aims to simplify work with AI search.",
                    "original_evidence_ids": ["E-1"],
                    "qa_label_before": "needs_revision",
                    "qa_reason": "Intent wording is not supported by evidence.",
                    "qa_issue_tags": ["interpretive_drift"],
                    "suggested_revision": "Notion AI supports search across notes.",
                    "revision_instruction": "Use only E-1 and remove intent wording.",
                    "revised_statement": "Notion AI supports search across notes.",
                    "revised_evidence_ids": ["E-1"],
                    "revision_explanation": "Removed unsupported intent wording.",
                    "revision_failed": False,
                    "failure_reason": None,
                    "qa_label_after": "accepted",
                    "max_revision_reached": False,
                    "revise_cost_usd": 0.0004,
                }
            ],
        },
    )
    _write_json(
        run / "trace.json",
        {
            "node_runs": [
                {"node_name": name, "status": "completed", "latency_ms": 1, "cost_usd": 0.0}
                for name in [
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
            ]
        },
    )
    (run / "report.md").write_text("# Revision Report\n", encoding="utf-8")
    return runs_dir


@pytest.fixture()
def client(revision_runs: Path) -> TestClient:
    return TestClient(fastapi_app)


def test_revision_history_reader_returns_records(revision_runs: Path) -> None:
    view = get_revision_history(revision_runs, REVISION_TASK)

    assert view["enabled"] is True
    assert view["total_revisions"] == 1
    assert view["revisions"][0]["qa_label_after"] == "accepted"


def test_dag_json_shows_revision_loop_edge_nodes(client: TestClient) -> None:
    response = client.get(f"/runs/{REVISION_TASK}/dag.json")

    assert response.status_code == 200
    payload = response.json()
    names = [node["name"] for node in payload["nodes"]]
    assert payload["has_revision_loop"] is True
    assert names == [
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
    assert names.count("qa_critic") == 2


def test_run_detail_renders_revision_tab(client: TestClient) -> None:
    response = client.get(f"/runs/{REVISION_TASK}")

    assert response.status_code == 200
    assert "Revision History" in response.text
    assert "Notion aims to simplify work with AI search." in response.text
    assert "Notion AI supports search across notes." in response.text


def test_revision_artifact_endpoint_is_whitelisted(client: TestClient) -> None:
    response = client.get(f"/runs/{REVISION_TASK}/artifact/revision_history")

    assert response.status_code == 200
    assert response.json()["total_revisions"] == 1


def test_legacy_run_has_no_revision_loop(client: TestClient) -> None:
    response = client.get(f"/runs/{LEGACY_TASK}")
    dag_response = client.get(f"/runs/{LEGACY_TASK}/dag.json")

    assert response.status_code == 200
    assert "Revision loop not triggered for this run." in response.text
    assert dag_response.json()["has_revision_loop"] is False


def test_writer_exports_insight_candidates_as_not_accepted(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_RESCUE", "1")
    task = AnalysisTask(
        task_id="T-writer-insight",
        query="AI coding",
        competitors=[CompetitorInput(name="Cursor")],
    )
    evidence = EvidenceItem(
        evidence_id="E-1",
        source_id="S-1",
        competitor_name="Cursor",
        quote="Cursor 旨在推动团队采用 AI coding.",
        normalized_fact="Cursor 旨在推动团队采用 AI coding.",
    )
    claim = AnalysisClaim(
        claim_id="C-INSIGHT",
        run_id="RUN-1",
        competitor_name="Cursor",
        dimension="swot",
        statement="Cursor 旨在推动团队采用 AI coding.",
        evidence_ids=["E-1"],
    )

    _report, accepted, _risks, _discarded, _stats = render_report(
        task,
        "RUN-1",
        [claim],
        [evidence],
    )

    assert accepted[0].insight_candidate is True
    assert accepted[0].accepted is False


def test_review_queue_keeps_insight_candidate_when_not_accepted(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_json(
        run_dir / "claims.json",
        [
            {
                "claim_id": "C-INSIGHT",
                "competitor_name": "Cursor",
                "dimension": "swot",
                "statement": "Cursor 旨在推动团队采用 AI coding.",
                "evidence_ids": ["E-1"],
                "accepted": False,
                "insight_candidate": True,
                "interpretive_risk": True,
            }
        ],
    )
    _write_json(run_dir / "discarded_claims.json", [])
    _write_json(run_dir / "sources.json", [])
    _write_json(run_dir / "extractor_failures.json", [])
    _write_json(run_dir / "run_summary.json", {"quality_gates": {"low_recall_competitors": []}})
    _write_json(run_dir / "evidence.json", [{"evidence_id": "E-1", "competitor_name": "Cursor"}])

    queue = build_review_queue(run_dir)

    assert queue[0]["type"] == "insight_candidate"
    assert queue[0]["claim_id"] == "C-INSIGHT"
