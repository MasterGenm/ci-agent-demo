from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cs_mvp.web.routes import home, run_detail, runs


fastapi_app = FastAPI(title="cs-mvp dashboard", version="1.6")

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
fastapi_app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
fastapi_app.mount("/docs", StaticFiles(directory=str(_DOCS_DIR)), name="docs")

fastapi_app.include_router(home.router)
fastapi_app.include_router(runs.router)
fastapi_app.include_router(run_detail.router)
