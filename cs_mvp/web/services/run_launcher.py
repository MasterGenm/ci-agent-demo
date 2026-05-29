from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from cs_mvp import db
from cs_mvp.artifacts import export_html_report
from cs_mvp.cli import _parse_competitors
from cs_mvp.config import load_settings
from cs_mvp.graph import build_graph
from cs_mvp.models import AgentRun, AnalysisTask, GraphState


def _write_pending_summary(run_dir: Path, task: AnalysisTask, run: AgentRun) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task.task_id,
        "run_id": run.run_id,
        "query": task.query,
        "competitors": [item.name for item in task.competitors],
        "status": "running",
        "started_at": run.started_at.isoformat(),
        "completed_at": None,
        "duration_seconds": None,
        "warnings": [],
        "quality_gates": {},
    }
    (run_dir / "run_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


async def launch_run(query: str, competitors_raw: str) -> str:
    settings = load_settings()
    db.init_db(settings.db_path)
    task = AnalysisTask(
        task_id=f"T-{uuid.uuid4().hex}",
        query=query,
        competitors=_parse_competitors(competitors_raw),
    )
    agent_run = AgentRun(run_id=f"RUN-{uuid.uuid4().hex}", task_id=task.task_id)
    db.insert_task(task)
    db.insert_run(agent_run)
    _write_pending_summary(Path(settings.runs_dir) / task.task_id, task, agent_run)
    asyncio.create_task(_invoke_graph(task, agent_run, settings.db_path, settings.runs_dir))
    return task.task_id


async def _invoke_graph(
    task: AnalysisTask,
    agent_run: AgentRun,
    db_path: str,
    runs_dir: str,
) -> None:
    def _sync_run() -> None:
        graph = build_graph(db_path, runs_dir)
        initial = GraphState(task=task, run_id=agent_run.run_id)
        graph.invoke(
            initial.model_dump(mode="json"),
            config={"configurable": {"thread_id": task.task_id}},
        )

    started = datetime.utcnow()
    run_dir = Path(runs_dir) / task.task_id
    try:
        await asyncio.to_thread(_sync_run)
        try:
            export_html_report(run_dir)
        except Exception:
            pass
    except Exception as exc:
        summary_path = run_dir / "run_summary.json"
        payload = {}
        if summary_path.exists():
            try:
                payload = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        payload.update(
            {
                "task_id": task.task_id,
                "run_id": agent_run.run_id,
                "query": task.query,
                "competitors": [item.name for item in task.competitors],
                "status": "failed",
                "completed_at": datetime.utcnow().isoformat(timespec="seconds"),
                "duration_seconds": round((datetime.utcnow() - started).total_seconds(), 3),
                "error": str(exc),
            }
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
