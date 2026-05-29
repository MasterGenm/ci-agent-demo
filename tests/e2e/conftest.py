from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "T-e2e-v16-dashboard"
SYSTEM_CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict[str, object]:
    args: dict[str, object] = {
        "args": ["--proxy-server=direct://", "--proxy-bypass-list=*"],
    }
    if sys.platform == "win32" and SYSTEM_CHROME.exists():
        args["executable_path"] = str(SYSTEM_CHROME)
    return args


def _build_e2e_run(root: Path) -> str:
    runs_dir = root / "runs"
    run_dir = runs_dir / TASK_ID
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "run_summary.json",
        {
            "task_id": TASK_ID,
            "run_id": "RUN-e2e-v16",
            "query": "Vector database competitive analysis",
            "competitors": ["Milvus", "Qdrant", "Weaviate"],
            "status": "completed",
            "completed_at": "2026-05-22 09:00:00",
            "duration_seconds": 42.0,
        },
    )
    _write_json(
        run_dir / "claims.json",
        [
            {
                "claim_id": "C-E2E-1",
                "competitor_name": "Qdrant",
                "dimension": "features",
                "statement": "Qdrant highlights vector search and filtering.",
                "evidence_ids": ["E-E2E-1"],
                "accepted": True,
            }
        ],
    )
    _write_json(
        run_dir / "evidence.json",
        [
            {
                "evidence_id": "E-E2E-1",
                "source_id": "S-E2E-1",
                "competitor_name": "Qdrant",
                "claim_type": "feature",
                "quote": "Qdrant highlights vector search and filtering.",
            }
        ],
    )
    _write_json(
        run_dir / "sources.json",
        [
            {
                "source_id": "S-E2E-1",
                "url": "https://qdrant.tech/documentation/",
                "title": "Qdrant documentation",
            }
        ],
    )
    _write_json(
        run_dir / "qa_audit.json",
        {
            "schema_version": "1.2.0",
            "run_id": "RUN-e2e-v16",
            "total_claims_audited": 1,
            "accepted_count": 1,
            "needs_revision_count": 0,
            "risky_count": 0,
            "llm_cost_usd": 0.0,
            "feedbacks": [
                {
                    "claim_id": "C-E2E-1",
                    "label": "accepted",
                    "reason": "The claim is grounded in the evidence quote.",
                    "issue_tags": [],
                }
            ],
        },
    )
    _write_json(
        run_dir / "revision_history.json",
        {
            "schema_version": "1.2.0",
            "run_id": "RUN-e2e-v16",
            "total_revisions": 1,
            "revision_round": 1,
            "max_revision_rounds": 1,
            "total_revise_cost_usd": 0.0,
            "revisions": [
                {
                    "claim_id": "C-E2E-1",
                    "revision_round": 1,
                    "original_statement": "Qdrant is useful for vector workloads.",
                    "revised_statement": "Qdrant highlights vector search and filtering.",
                    "qa_label_before": "needs_revision",
                    "qa_label_after": "accepted",
                    "qa_reason": "Original wording was too broad.",
                    "revision_failed": False,
                    "max_revision_reached": False,
                }
            ],
        },
    )
    _write_json(
        run_dir / "trace.json",
        {
            "node_runs": [
                {"node_name": name, "status": "completed", "latency_ms": 10, "cost_usd": 0.0}
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
    (run_dir / "report.html").write_text(
        "<!doctype html><html><body><h1>Vector database report</h1><p>Evidence-backed demo.</p></body></html>",
        encoding="utf-8",
    )
    (run_dir / "report_pm.html").write_text(
        "<!doctype html><html><body><h1>PM-readable vector database report</h1><p>Decision-ready demo.</p></body></html>",
        encoding="utf-8",
    )
    _write_json(
        run_dir / "report_style_audit.json",
        {
            "schema_version": "1.7.0",
            "task_id": TASK_ID,
            "run_id": "RUN-e2e-v16",
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
            "actionability": {
                "recommendation_count": 1,
                "recommendations_with_evidence": 1,
                "recommendations_needing_validation": 0,
            },
            "evidence_density": {
                "citation_count": 3,
                "unique_citation_count": 1,
                "uncited_recommendation_count": 0,
            },
            "score": {
                "readability_score": 1.0,
                "actionability_score": 1.0,
                "evidence_grounding_score": 0.5,
                "overall_score": 0.833,
            },
            "ai_tone_flags": [],
            "notes": [],
        },
    )
    (run_dir / "report_style_audit.md").write_text(
        "# Report Style Audit\n\n## Summary\n\n- Overall score: 0.833\n",
        encoding="utf-8",
    )
    return TASK_ID


@pytest.fixture(scope="session")
def e2e_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cs_mvp_e2e")


@pytest.fixture(scope="session")
def e2e_task_id(e2e_root: Path) -> str:
    return _build_e2e_run(e2e_root)


@pytest.fixture(scope="session")
def server_url(e2e_root: Path, e2e_task_id: str) -> str:
    root = e2e_root
    runs_dir = root / "runs"
    port = _find_free_port()
    env = {
        **os.environ,
        "RUNS_DIR": str(runs_dir),
        "DB_PATH": str(root / "cs_mvp.db"),
        "TAVILY_API_KEY": "dummy-for-e2e",
        "OPENAI_API_KEY": "dummy-for-e2e",
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "cs_mvp.web.app:fastapi_app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            response = httpx.get(f"{url}/", timeout=1, trust_env=False)
            if response.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        out, err = proc.communicate(timeout=5)
        pytest.fail(f"server failed to start\nstdout={out[-500:]}\nstderr={err[-500:]}")

    yield url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
