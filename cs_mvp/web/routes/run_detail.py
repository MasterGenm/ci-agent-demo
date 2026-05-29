from __future__ import annotations

import html
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from cs_mvp.config import load_settings
from cs_mvp.web.services.artifact_reader import (
    ArtifactNotFound,
    UnsafeArtifactPath,
    get_dag_status,
    get_evidence,
    get_qa_feedback_view,
    get_report_quality_view,
    get_revision_history,
    get_run_metadata,
    get_run_status_summary,
    get_schema_view,
    get_trace,
    read_artifact,
    report_html_path,
    report_pm_html_path,
    report_pptx_path,
    report_style_audit_md_path,
)
from cs_mvp.web.templating import templates


router = APIRouter()


def _runs_dir() -> Path:
    return Path(load_settings().runs_dir)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/runs/{task_id}")
def run_detail(request: Request, task_id: str):
    try:
        runs_dir = _runs_dir()
        metadata = get_run_metadata(runs_dir, task_id)
        dag = get_dag_status(runs_dir, task_id)
        qa = get_qa_feedback_view(runs_dir, task_id)
        revision = get_revision_history(runs_dir, task_id)
        evidence = get_evidence(runs_dir, task_id)
        trace = get_trace(runs_dir, task_id)
        status = get_run_status_summary(runs_dir, task_id)
        schema = get_schema_view()
        report_quality = get_report_quality_view(runs_dir, task_id)
    except (ArtifactNotFound, UnsafeArtifactPath) as exc:
        raise _not_found(exc) from exc

    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "task_id": task_id,
            "metadata": metadata,
            "dag": dag,
            "qa": qa,
            "revision": revision,
            "evidence": evidence,
            "trace": trace,
            "status": status,
            "schema": schema,
            "report_quality": report_quality,
        },
    )


@router.get("/runs/{task_id}/dag.json")
def dag_json(task_id: str):
    try:
        return get_dag_status(_runs_dir(), task_id)
    except (ArtifactNotFound, UnsafeArtifactPath) as exc:
        raise _not_found(exc) from exc


@router.get("/runs/{task_id}/status.json")
def run_status(task_id: str):
    try:
        return get_run_status_summary(_runs_dir(), task_id)
    except (ArtifactNotFound, UnsafeArtifactPath) as exc:
        raise _not_found(exc) from exc


@router.get("/runs/{task_id}/progress", response_class=HTMLResponse)
def run_progress(request: Request, task_id: str):
    try:
        status = get_run_status_summary(_runs_dir(), task_id)
    except (ArtifactNotFound, UnsafeArtifactPath) as exc:
        raise _not_found(exc) from exc
    return templates.TemplateResponse(
        request,
        "_progress.html",
        {"task_id": task_id, "status": status},
    )


@router.get("/runs/{task_id}/artifact/{name}")
def artifact(task_id: str, name: str):
    try:
        return JSONResponse(read_artifact(_runs_dir(), task_id, name))
    except (ArtifactNotFound, UnsafeArtifactPath) as exc:
        raise _not_found(exc) from exc


@router.get("/runs/{task_id}/report.html")
def report_html(task_id: str):
    try:
        path = report_html_path(_runs_dir(), task_id)
    except (ArtifactNotFound, UnsafeArtifactPath) as exc:
        raise _not_found(exc) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="report not found")
    if path.suffix.lower() == ".html":
        return FileResponse(path, media_type="text/html")
    text = path.read_text(encoding="utf-8")
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:system-ui;padding:24px;line-height:1.6}"
        "pre{white-space:pre-wrap}</style></head><body><pre>"
        f"{html.escape(text)}</pre></body></html>"
    )


@router.get("/runs/{task_id}/report_pm.html")
def report_pm_html(task_id: str):
    try:
        path = report_pm_html_path(_runs_dir(), task_id)
    except (ArtifactNotFound, UnsafeArtifactPath) as exc:
        raise _not_found(exc) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="PM report not found")
    if path.suffix.lower() == ".html":
        return FileResponse(path, media_type="text/html")
    text = path.read_text(encoding="utf-8")
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:system-ui;padding:24px;line-height:1.6}"
        "pre{white-space:pre-wrap}</style></head><body><pre>"
        f"{html.escape(text)}</pre></body></html>"
    )


@router.get("/runs/{task_id}/report.pptx")
def report_pptx(task_id: str):
    try:
        path = report_pptx_path(_runs_dir(), task_id)
    except (ArtifactNotFound, UnsafeArtifactPath) as exc:
        raise _not_found(exc) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="pptx not found")
    return FileResponse(
        path,
        media_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        filename=f"report_{task_id[:12]}.pptx",
    )


@router.get("/runs/{task_id}/report_style_audit.md")
def report_style_audit_md(task_id: str):
    try:
        path = report_style_audit_md_path(_runs_dir(), task_id)
    except (ArtifactNotFound, UnsafeArtifactPath) as exc:
        raise _not_found(exc) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="report style audit not found")
    return FileResponse(path, media_type="text/markdown")
