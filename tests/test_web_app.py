from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cs_mvp.web.app import fastapi_app


LEGACY_TASK = "T-50d7bb2f823e444994deac9cc85f0e8e"
QA_TASK = "T-v12-b2-smoke-rescue-off"


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def dashboard_runs(tmp_path: Path, monkeypatch) -> Path:
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
            "query": "AI notes legacy run",
            "competitors": ["Notion", "Evernote", "Mem"],
            "status": "completed",
            "completed_at": "2026-05-18 05:21:36",
            "duration_seconds": 158.071,
        },
    )
    _write_json(legacy / "claims.json", [{"claim_id": "C-1", "statement": "Supported."}])
    _write_json(
        legacy / "evidence.json",
        [
            {
                "evidence_id": "E-1",
                "source_id": "S-1",
                "competitor_name": "Notion",
                "claim_type": "feature",
                "quote": "Notion AI supports search.",
            }
        ],
    )
    _write_json(
        legacy / "sources.json",
        [{"source_id": "S-1", "url": "https://notion.example", "title": "Notion"}],
    )
    _write_json(
        legacy / "trace.json",
        {
            "node_modes": {
                "collector": "real",
                "extractor": "real",
                "analyst": "real",
                "writer": "real",
            },
            "node_runs": [
                {"node_name": name, "status": "completed", "latency_ms": 1}
                for name in ["task_init", "collector", "extractor", "analyst", "writer", "finalize"]
            ],
        },
    )
    (legacy / "report.html").write_text(
        "<!doctype html><html><body>Legacy Report</body></html>",
        encoding="utf-8",
    )

    qa = runs_dir / QA_TASK
    qa.mkdir()
    _write_json(
        qa / "run_summary.json",
        {
            "task_id": QA_TASK,
            "run_id": "RUN-qa",
            "query": "AI notes QA run",
            "competitors": ["Notion", "Evernote", "Mem"],
            "status": "completed",
            "completed_at": "2026-05-20 03:41:56",
            "duration_seconds": 47.589,
        },
    )
    _write_json(
        qa / "claims.json",
        [
            {
                "claim_id": "C-QA-1",
                "competitor_name": "Notion",
                "dimension": "features",
                "statement": "Notion AI supports search.",
                "evidence_ids": ["E-QA-1"],
            }
        ],
    )
    _write_json(
        qa / "discarded_claims.json",
        [
            {
                "claim_id": "C-QA-2",
                "statement": "Notion AI has unsupported intent wording.",
                "evidence_ids": ["E-QA-1"],
                "support_score": 0.4,
                "verdict": "uncertain",
            }
        ],
    )
    _write_json(
        qa / "evidence.json",
        [
            {
                "evidence_id": "E-QA-1",
                "source_id": "S-QA-1",
                "competitor_name": "Notion",
                "claim_type": "feature",
                "quote": "Notion AI supports search.",
            }
        ],
    )
    _write_json(
        qa / "sources.json",
        [{"source_id": "S-QA-1", "url": "https://notion.example", "title": "Notion"}],
    )
    _write_json(
        qa / "qa_audit.json",
        {
            "schema_version": "1.2.0",
            "total_claims_audited": 2,
            "accepted_count": 1,
            "needs_revision_count": 1,
            "risky_count": 0,
            "llm_cost_usd": 0.001,
            "feedbacks": [
                {
                    "claim_id": "C-QA-1",
                    "label": "accepted",
                    "reason": "Supported.",
                    "issue_tags": [],
                },
                {
                    "claim_id": "C-QA-2",
                    "label": "needs_revision",
                    "reason": "Intent wording is not in evidence.",
                    "issue_tags": ["interpretive_drift"],
                },
            ],
        },
    )
    _write_json(
        qa / "trace.json",
        {
            "node_modes": {
                "collector": "real",
                "extractor": "real",
                "analyst": "real",
                "qa_critic": "real",
                "writer": "real",
            },
            "node_runs": [
                {"node_name": name, "status": "completed", "latency_ms": 1, "cost_usd": 0.0}
                for name in [
                    "task_init",
                    "collector",
                    "extractor",
                    "analyst",
                    "qa_critic",
                    "writer",
                    "finalize",
                ]
            ],
        },
    )
    (qa / "report.md").write_text("# QA Report\n\nBody", encoding="utf-8")
    (qa / "report_pm.html").write_text(
        "<!doctype html><html><body>PM-readable QA Report</body></html>",
        encoding="utf-8",
    )
    (qa / "report.pptx").write_bytes(b"pptx-demo")
    _write_json(
        qa / "report_pm_summary.json",
        {
            "schema_version": "1.7.0",
            "task_id": QA_TASK,
            "run_id": "RUN-qa",
            "report_type": "pm",
            "section_count": 7,
            "competitor_count": 3,
            "top_finding_count": 1,
            "recommendation_count": 1,
            "evidence_digest_count": 1,
        },
    )
    _write_json(
        qa / "report_style_audit.json",
        {
            "schema_version": "1.7.0",
            "task_id": QA_TASK,
            "run_id": "RUN-qa",
            "report_type": "pm",
            "section_coverage": {
                "one_page_summary": True,
                "competitor_matrix": True,
                "top_findings": True,
                "competitor_profiles": True,
                "recommendations": True,
                "risks_and_unknowns": True,
                "evidence_digest": True,
            },
            "readability": {
                "word_count": 120,
                "bullet_count": 8,
                "bullet_ratio": 0.32,
                "long_paragraph_count": 0,
            },
            "actionability": {
                "recommendation_count": 1,
                "recommendations_with_evidence": 1,
                "recommendations_needing_validation": 0,
            },
            "evidence_density": {
                "citation_count": 4,
                "unique_citation_count": 1,
                "uncited_recommendation_count": 0,
            },
            "ai_tone_flags": [],
            "score": {
                "readability_score": 1.0,
                "actionability_score": 1.0,
                "evidence_grounding_score": 0.5,
                "overall_score": 0.833,
            },
            "notes": [],
        },
    )
    (qa / "report_style_audit.md").write_text(
        "# Report Style Audit\n\n## Summary\n\n- Overall score: 0.833\n",
        encoding="utf-8",
    )
    return runs_dir


@pytest.fixture()
def client(dashboard_runs: Path) -> TestClient:
    return TestClient(fastapi_app)


def test_home_renders(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "cs-mvp" in response.text


def test_runs_list_returns_existing_runs(client: TestClient) -> None:
    response = client.get("/runs")

    assert response.status_code == 200
    task_ids = {item["task_id"] for item in response.json()["runs"]}
    assert {LEGACY_TASK, QA_TASK}.issubset(task_ids)


def test_run_detail_404_for_unknown(client: TestClient) -> None:
    response = client.get("/runs/UNKNOWN")

    assert response.status_code == 404


def test_run_detail_renders_for_case4(client: TestClient) -> None:
    response = client.get(f"/runs/{LEGACY_TASK}")

    assert response.status_code == 200
    assert LEGACY_TASK in response.text
    assert "QA Critic not enabled for this run" in response.text


def test_dag_json_includes_qa_critic_node(client: TestClient) -> None:
    response = client.get(f"/runs/{QA_TASK}/dag.json")

    assert response.status_code == 200
    assert "qa_critic" in [item["name"] for item in response.json()["nodes"]]


def test_dag_json_omits_qa_critic_for_legacy_run(client: TestClient) -> None:
    response = client.get(f"/runs/{LEGACY_TASK}/dag.json")

    assert response.status_code == 200
    assert "qa_critic" not in [item["name"] for item in response.json()["nodes"]]


def test_artifact_endpoint_returns_qa_audit(client: TestClient) -> None:
    response = client.get(f"/runs/{QA_TASK}/artifact/qa_audit")

    assert response.status_code == 200
    assert response.json()["needs_revision_count"] == 1


def test_artifact_endpoint_404_for_missing(client: TestClient) -> None:
    response = client.get(f"/runs/{LEGACY_TASK}/artifact/qa_audit")

    assert response.status_code == 404


def test_artifact_endpoint_rejects_non_whitelisted_name(client: TestClient) -> None:
    response = client.get(f"/runs/{QA_TASK}/artifact/../trace")

    assert response.status_code == 404


def test_report_html_endpoint_returns_existing_html(client: TestClient) -> None:
    response = client.get(f"/runs/{LEGACY_TASK}/report.html")

    assert response.status_code == 200
    assert "Legacy Report" in response.text


def test_report_tab_links_to_pm_report(client: TestClient) -> None:
    response = client.get(f"/runs/{QA_TASK}")

    assert response.status_code == 200
    assert "open PM report" in response.text
    assert f"/runs/{QA_TASK}/report_pm.html" in response.text
    assert "下载 PPT" in response.text
    assert f"/runs/{QA_TASK}/report.pptx" in response.text
    assert "style audit json" in response.text
    assert "Report quality summary" in response.text


def test_pm_report_html_endpoint_returns_existing_html(client: TestClient) -> None:
    response = client.get(f"/runs/{QA_TASK}/report_pm.html")

    assert response.status_code == 200
    assert "PM-readable QA Report" in response.text


def test_report_pptx_endpoint_returns_existing_file(client: TestClient) -> None:
    response = client.get(f"/runs/{QA_TASK}/report.pptx")

    assert response.status_code == 200
    assert response.content == b"pptx-demo"
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


def test_artifact_endpoint_returns_pm_report_summary(client: TestClient) -> None:
    response = client.get(f"/runs/{QA_TASK}/artifact/report_pm_summary")

    assert response.status_code == 200
    assert response.json()["report_type"] == "pm"


def test_artifact_endpoint_returns_report_style_audit(client: TestClient) -> None:
    response = client.get(f"/runs/{QA_TASK}/artifact/report_style_audit")

    assert response.status_code == 200
    assert response.json()["score"]["overall_score"] == 0.833


def test_report_style_audit_markdown_endpoint_returns_existing_md(
    client: TestClient,
) -> None:
    response = client.get(f"/runs/{QA_TASK}/report_style_audit.md")

    assert response.status_code == 200
    assert "Report Style Audit" in response.text


def test_post_runs_starts_background_task(client: TestClient, monkeypatch) -> None:
    async def fake_launch_run(query: str, competitors_raw: str) -> str:
        assert query == "AI notes"
        assert competitors_raw == "Notion,Evernote"
        return "T-new"

    monkeypatch.setattr("cs_mvp.web.services.run_launcher.launch_run", fake_launch_run)

    response = client.post(
        "/runs",
        json={"query": "AI notes", "competitors": "Notion,Evernote"},
    )

    assert response.status_code == 200
    assert response.json()["task_id"] == "T-new"
