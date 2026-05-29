from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cs_mvp.config import load_settings
from cs_mvp.web.services import run_launcher
from cs_mvp.web.services.artifact_reader import list_runs


router = APIRouter()


class RunCreate(BaseModel):
    query: str = Field(min_length=1)
    competitors: str = Field(min_length=1)


@router.get("/runs")
def runs_index():
    settings = load_settings()
    return {"runs": list_runs(Path(settings.runs_dir))}


@router.post("/runs")
async def runs_create(payload: RunCreate):
    try:
        task_id = await run_launcher.launch_run(payload.query, payload.competitors)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": task_id, "status": "running", "detail_url": f"/runs/{task_id}"}
