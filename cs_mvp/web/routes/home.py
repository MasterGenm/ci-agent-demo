from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request

from cs_mvp.config import load_settings
from cs_mvp.models import SCHEMA_VERSION
from cs_mvp.web.services.artifact_reader import list_runs
from cs_mvp.web.templating import templates


router = APIRouter()


def _demo_manifest() -> dict:
    path = Path("demo/demo_manifest.json")
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


@router.get("/")
def home(request: Request):
    settings = load_settings()
    runs = list_runs(Path(settings.runs_dir))
    manifest = _demo_manifest()
    main_demo = manifest.get("main_demo") if isinstance(manifest, dict) else {}
    backup_demo = manifest.get("backup_demo") if isinstance(manifest, dict) else {}
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "runs": runs,
            "version": "1.6.0",
            "tests_count": "248+",
            "latest_run": runs[0] if runs else None,
            "total_runs": len(runs),
            "schema_version": SCHEMA_VERSION,
            "demo_main": (
                main_demo.get("task_id") if isinstance(main_demo, dict) else None
            ),
            "demo_backup": (
                backup_demo.get("task_id") if isinstance(backup_demo, dict) else None
            ),
        },
    )
