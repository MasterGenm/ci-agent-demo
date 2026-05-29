from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cs_mvp.web.app import fastapi_app
from cs_mvp.web.services.artifact_reader import get_dag_status


TASK_ID = "T-v16-capability"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def capability_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / TASK_ID
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
    _write_json(
        run_dir / "run_summary.json",
        {
            "task_id": TASK_ID,
            "run_id": "RUN-v16-capability",
            "query": "Capability dashboard smoke",
            "competitors": ["Qdrant", "Weaviate"],
            "status": "completed",
        },
    )
    _write_json(run_dir / "claims.json", [])
    _write_json(run_dir / "evidence.json", [])
    _write_json(run_dir / "sources.json", [])
    _write_json(
        run_dir / "trace.json",
        {
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
            ]
        },
    )
    (run_dir / "report.md").write_text("# Capability report\n", encoding="utf-8")
    return runs_dir


@pytest.fixture()
def client(capability_runs: Path) -> TestClient:
    return TestClient(fastapi_app)


def test_dag_status_includes_capability_metadata(capability_runs: Path) -> None:
    dag = get_dag_status(capability_runs, TASK_ID)
    nodes = {node["name"]: node for node in dag["nodes"]}

    assert nodes["collector"]["capability"]["skills_count"] == 3
    assert "seed_url_priority_fetch" in nodes["collector"]["capability"]["skill_names"]
    assert nodes["qa_critic"]["capability"]["skills_count"] == 2
    assert nodes["task_init"]["capability"] == {}


def test_dag_json_endpoint_exposes_capability_metadata(client: TestClient) -> None:
    response = client.get(f"/runs/{TASK_ID}/dag.json")

    assert response.status_code == 200
    collector = next(node for node in response.json()["nodes"] if node["name"] == "collector")
    assert collector["capability"]["skills_count"] == 3
    assert "low_recall_audit" in collector["capability"]["skill_names"]


def test_dashboard_dag_renders_skill_count_and_hover_title(client: TestClient) -> None:
    response = client.get(f"/runs/{TASK_ID}")

    assert response.status_code == 200
    assert "3 skills" in response.text
    assert "seed_url_priority_fetch, search_result_filtering, low_recall_audit" in response.text
    assert "Agent SkillCards" not in response.text


def test_capability_metadata_does_not_replace_role_card(client: TestClient) -> None:
    response = client.get(f"/runs/{TASK_ID}/dag.json")
    collector = next(node for node in response.json()["nodes"] if node["name"] == "collector")

    assert collector["role_card"]["role"]
    assert collector["role_card"]["goal"]
    assert collector["capability"]["skills_count"] == 3
