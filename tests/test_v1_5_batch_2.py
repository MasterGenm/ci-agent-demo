import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cs_mvp.observability.langfuse_handler import LangfuseCloudCallback
from cs_mvp.web.app import fastapi_app
from cs_mvp.web.services.artifact_reader import get_dag_status, get_role_cards_view

TASK_ID = "T-rolecard-dashboard"
ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def rolecard_runs(tmp_path: Path, monkeypatch) -> Path:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cs_mvp.db"))

    run = runs_dir / TASK_ID
    run.mkdir()
    _write_json(
        run / "run_summary.json",
        {
            "task_id": TASK_ID,
            "run_id": "RUN-rolecard",
            "query": "RoleCard dashboard smoke",
            "competitors": ["Notion", "Mem"],
            "status": "completed",
        },
    )
    _write_json(run / "claims.json", [])
    _write_json(run / "evidence.json", [])
    _write_json(run / "sources.json", [])
    _write_json(
        run / "trace.json",
        {
            "node_runs": [
                {"node_name": name, "status": "completed", "latency_ms": 1}
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
    (run / "report.md").write_text("# RoleCard Report\n", encoding="utf-8")
    return runs_dir


@pytest.fixture()
def client(rolecard_runs: Path) -> TestClient:
    return TestClient(fastapi_app)


def test_dag_status_includes_role_card(rolecard_runs: Path):
    dag = get_dag_status(rolecard_runs, TASK_ID)
    nodes = {node["name"]: node for node in dag["nodes"]}

    assert nodes["collector"]["role_card"]["role"] == "公开信息采集与网页抓取者"
    assert "source artifact" in nodes["collector"]["role_card"]["goal"]
    assert nodes["qa_critic"]["role_card"]["role"] == "独立质检与修订反馈审查者"
    assert nodes["task_init"]["role_card"] == {}


def test_dashboard_run_detail_renders_role_titles(client: TestClient):
    response = client.get(f"/runs/{TASK_ID}")

    assert response.status_code == 200
    assert 'title="公开信息采集与网页抓取者 - ' in response.text
    assert "独立质检与修订反馈审查者" in response.text


def test_dag_json_endpoint_exposes_role_card(client: TestClient):
    response = client.get(f"/runs/{TASK_ID}/dag.json")

    assert response.status_code == 200
    collector = next(node for node in response.json()["nodes"] if node["name"] == "collector")
    assert collector["role_card"]["role"] == "公开信息采集与网页抓取者"


def test_role_cards_view_lists_6_agents():
    view = get_role_cards_view()

    assert len(view["agents"]) == 6
    assert {item["name"] for item in view["agents"]} == {
        "collector",
        "extractor",
        "analyst",
        "qa_critic",
        "analyst_revise",
        "writer",
    }


def test_role_cards_doc_exists():
    doc = ROOT / "docs" / "AGENT_ROLES.md"

    assert doc.exists()
    assert len(doc.read_text(encoding="utf-8").splitlines()) > 200
    assert "crewAI" in doc.read_text(encoding="utf-8")


def test_prompt_family_doc_exists():
    doc = ROOT / "docs" / "PROMPT_FAMILY.md"

    assert doc.exists()
    assert len(doc.read_text(encoding="utf-8").splitlines()) > 100
    assert "gpt-researcher" in doc.read_text(encoding="utf-8")


def test_readme_mentions_rolecard_and_promptfamily():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Agent RoleCards And PromptFamily" in readme
    assert "docs/AGENT_ROLES.md" in readme
    assert "docs/PROMPT_FAMILY.md" in readme


class FakeSpan:
    def __init__(self) -> None:
        self.metadata = None

    def end(self, **kwargs):
        return self


class FakeLangfuse:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []
        self.last_metadata = None
        self.flushed = False

    def trace(self, **kwargs):
        return None

    def span(self, **kwargs):
        span = FakeSpan()
        span.metadata = kwargs.get("metadata")
        self.last_metadata = span.metadata
        self.spans.append(span)
        return span

    def generation(self, **kwargs):
        return self.span(**kwargs)

    def flush(self):
        self.flushed = True


def test_langfuse_chain_span_metadata_includes_agent_role():
    client = FakeLangfuse()
    callback = LangfuseCloudCallback(
        client=client,
        metadata={"cs_mvp_version": "v1.5.0"},
    )

    callback.on_chain_start({"name": "collector"}, {"task": "x"}, run_id="run-1")

    assert client.last_metadata["agent_role"] == "公开信息采集与网页抓取者"
    assert client.last_metadata["kind"] == "chain"
