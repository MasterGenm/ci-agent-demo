from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cs_mvp.web.app import fastapi_app
from cs_mvp.web.services.artifact_reader import get_run_status_summary


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "T-v16-polish"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def v16_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / TASK_ID
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
    _write_json(
        run_dir / "run_summary.json",
        {
            "task_id": TASK_ID,
            "run_id": "RUN-v16-polish",
            "query": "v1.6 polish",
            "competitors": ["Milvus", "Qdrant"],
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
                {"node_name": name, "status": "completed", "latency_ms": 2, "cost_usd": 0.001}
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
    (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    return runs_dir


@pytest.fixture()
def client(v16_runs: Path) -> TestClient:
    return TestClient(fastapi_app)


def test_progress_endpoint_returns_json(client: TestClient) -> None:
    response = client.get(f"/runs/{TASK_ID}/status.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == TASK_ID
    assert payload["status"] == "completed"
    assert payload["completed_nodes"] == 9
    assert payload["total_nodes"] == 9
    assert payload["progress_percent"] == 100.0
    assert payload["total_cost_usd"] == pytest.approx(0.009)


def test_progress_endpoint_404_for_unknown(client: TestClient) -> None:
    response = client.get("/runs/UNKNOWN/status.json")

    assert response.status_code == 404


def test_progress_partial_renders_polling_markup(client: TestClient) -> None:
    response = client.get(f"/runs/{TASK_ID}/progress")

    assert response.status_code == 200
    assert 'id="run-progress"' in response.text
    assert "hx-trigger=" in response.text
    assert "Run Status" in response.text


def test_status_summary_handles_missing_trace(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "T-pending"
    run_dir.mkdir(parents=True)
    _write_json(run_dir / "run_summary.json", {"task_id": "T-pending"})

    summary = get_run_status_summary(tmp_path / "runs", "T-pending")

    assert summary["status"] == "pending"
    assert summary["completed_nodes"] == 0
    assert summary["progress_percent"] == 0.0


def test_home_includes_tailwind_and_lucide_cdn() -> None:
    base = (ROOT / "cs_mvp" / "web" / "templates" / "base.html").read_text(encoding="utf-8")

    assert "https://cdn.tailwindcss.com" in base
    assert "https://unpkg.com/lucide@latest" in base
    assert base.index("https://cdn.tailwindcss.com") < base.index("/static/style.css")


def test_progress_and_loading_partials_exist() -> None:
    progress = (ROOT / "cs_mvp" / "web" / "templates" / "_progress.html").read_text(encoding="utf-8")
    loading = (ROOT / "cs_mvp" / "web" / "templates" / "_loading.html").read_text(encoding="utf-8")

    assert "document.bodyShouldPoll" in progress
    assert "Loading run artifacts" in loading


def test_pre_commit_config_exists() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "pre-commit-hooks" in config
    assert "ruff-pre-commit" in config
    assert "check-yaml" in config


def test_pyproject_includes_dev_deps_and_tool_config() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    for dependency in ("pytest-playwright", "pytest-cov", "pre-commit", "mypy"):
        assert dependency in pyproject
    assert "[tool.mypy]" in pyproject
    assert "[tool.coverage.run]" in pyproject


def test_ci_workflow_has_e2e_job_and_mypy() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert re.search(r"^\s+e2e:", workflow, re.MULTILINE)
    assert "playwright install --with-deps chromium" in workflow
    assert "pytest tests/e2e/ -v --tb=short" in workflow
    assert "mypy cs_mvp/observability" in workflow


def test_readme_badges_count_and_v16_keywords() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.count("![") >= 9
    assert "v1.6.0" in readme
    assert "Playwright" in readme
    assert "Tailwind" in readme


def test_no_npm_project_files_added() -> None:
    assert not (ROOT / "package.json").exists()
    assert not (ROOT / "node_modules").exists()
