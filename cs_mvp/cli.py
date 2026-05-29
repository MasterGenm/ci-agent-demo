from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from pathlib import Path

import typer

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

from cs_mvp import db
from cs_mvp.artifacts import export_html_report
from cs_mvp.config import load_settings
from cs_mvp.graph import build_graph
from cs_mvp.models import AgentRun, AnalysisTask, CompetitorInput, GraphState
from cs_mvp.observability import get_langfuse_callback, get_langfuse_metadata
from cs_mvp.tools.semantic_judge import write_semantic_judge_report

app = typer.Typer(help="CS-MVP competitive analysis CLI.")

_NICHE_NAME_PATTERN = re.compile(r"^[A-Za-z]{1,4}$")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _is_niche_name(name: str) -> bool:
    return bool(_NICHE_NAME_PATTERN.match(name))


def _split_competitor_specs(raw: str) -> list[str]:
    specs: list[str] = []
    current: list[str] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if current and item.lower().startswith(("http://", "https://")):
            current.append(item)
            continue
        if current:
            specs.append(",".join(current).strip())
        current = [item]
    if current:
        specs.append(",".join(current).strip())
    return specs


def _parse_competitor_spec(item: str) -> CompetitorInput:
    parts = [part.strip() for part in item.split("|") if part.strip()]
    if not parts:
        raise typer.BadParameter("empty competitor entry")

    name = parts[0]
    exclude_keywords: list[str] = []
    seed_urls: list[str] = []
    for part in parts[1:]:
        if part.lower().startswith("seed="):
            seed_value = part.split("=", 1)[1]
            seed_urls.extend(url.strip() for url in seed_value.split(",") if url.strip())
        else:
            exclude_keywords.extend(kw.strip() for kw in part.split(";") if kw.strip())

    return CompetitorInput(
        name=name,
        exclude_keywords=exclude_keywords,
        seed_urls=seed_urls,
    )


def _parse_competitors(raw: str) -> list[CompetitorInput]:
    """Parse competitors.

    Supported forms:
    - Cursor,Windsurf,Copilot
    - GitHub Copilot|microsoft 365;copilot studio
    - Mem|seed=https://mem.ai,https://mem.ai/pricing
    - Mem|seed=https://mem.ai|memory card;memory foam
    """
    items = _split_competitor_specs(raw)
    if not items:
        raise typer.BadParameter("competitors must contain at least one name")

    competitors: list[CompetitorInput] = []
    niche_warnings: list[str] = []
    for item in items:
        competitor = _parse_competitor_spec(item)
        if (
            _is_niche_name(competitor.name)
            and not competitor.exclude_keywords
            and not competitor.seed_urls
        ):
            niche_warnings.append(competitor.name)
        competitors.append(competitor)

    if niche_warnings:
        typer.echo(
            "⚠️  Niche competitor warning: "
            f"{niche_warnings} are short English names. "
            "Search recall may drift; consider a domain-like name, seed URLs, "
            'or exclude keywords such as "Mem|memory card;memory foam".',
            err=True,
        )
    return competitors


def _percent(value: float | None) -> str:
    if value is None:
        return "0%"
    return f"{value * 100:.0f}%"


@app.command()
def run(
    query: str = typer.Option(..., help="分析问题"),
    competitors: str = typer.Option(..., help="竞品列表，逗号分隔"),
) -> None:
    """Start one competitive-analysis run."""
    _configure_logging()
    settings = load_settings()
    db.init_db(settings.db_path)

    task = AnalysisTask(
        task_id=f"T-{uuid.uuid4().hex}",
        query=query,
        competitors=_parse_competitors(competitors),
    )
    agent_run = AgentRun(run_id=f"RUN-{uuid.uuid4().hex}", task_id=task.task_id)

    db.insert_task(task)
    db.insert_run(agent_run)

    graph = build_graph(settings.db_path, settings.runs_dir)
    initial_state = GraphState(task=task, run_id=agent_run.run_id)
    invoke_config: dict[str, object] = {"configurable": {"thread_id": task.task_id}}
    langfuse_callback = get_langfuse_callback()
    if langfuse_callback is not None:
        invoke_config["callbacks"] = [langfuse_callback]
        invoke_config["metadata"] = get_langfuse_metadata()
        invoke_config["tags"] = ["cs-mvp", "v1.5", task.task_id]

    graph.invoke(
        initial_state.model_dump(mode="json"),
        config=invoke_config,
    )

    summary = db.get_source_quality_summary(agent_run.run_id)
    typer.echo("\n===== Source Quality Summary =====")
    typer.echo(
        f"Total:   {summary['total']}  |  fetched: {summary['fetched']}  |  "
        f"failed: {summary['failed']}  |  empty: {summary['empty']}"
    )
    typer.echo(
        f"Valid:   {summary['valid']} / {summary['total']}  "
        f"({summary['per_competitor_text']})"
    )
    typer.echo(f"Types:   {summary['types_text']}")
    typer.echo(f"Avg raw_text length (valid): {summary['avg_valid_length']:,} chars")
    typer.echo("===================================\n")

    evidence_summary = db.get_evidence_quality_summary(agent_run.run_id)
    stats_path = Path(settings.runs_dir) / task.task_id / "extractor_stats.json"
    extractor_stats = {}
    if stats_path.exists():
        extractor_stats = json.loads(stats_path.read_text(encoding="utf-8"))

    typer.echo("===== Evidence Quality Summary =====")
    typer.echo(
        f"Evidence: {evidence_summary['total']} items  |  "
        f"{evidence_summary['per_competitor_text']}"
    )
    typer.echo(f"Types:    {evidence_summary['types_text']}")
    typer.echo(
        "Schema pass rate: "
        f"{_percent(extractor_stats.get('schema_pass_rate'))} "
        f"({extractor_stats.get('pass_chunks', 0)}/"
        f"{extractor_stats.get('total_chunks', 0)} chunks)"
    )
    typer.echo(
        "Quote match rate: "
        f"{_percent(extractor_stats.get('quote_match_rate', evidence_summary['quote_match_rate']))}"
    )
    typer.echo(
        "Duplicate rate:   "
        f"{_percent(extractor_stats.get('duplicate_rate', evidence_summary['duplicate_rate']))}"
    )
    typer.echo(
        "LLM cost: "
        f"${extractor_stats.get('llm_cost_usd', 0.0):.2f} / "
        f"${extractor_stats.get('max_cost_usd', 0.0):.2f} budget"
    )
    typer.echo("====================================\n")

    analyst_stats_path = Path(settings.runs_dir) / task.task_id / "analyst_stats.json"
    claims_path = Path(settings.runs_dir) / task.task_id / "claims.json"
    if analyst_stats_path.exists() and claims_path.exists():
        analyst_stats = json.loads(analyst_stats_path.read_text(encoding="utf-8"))
        claims = json.loads(claims_path.read_text(encoding="utf-8"))
        _print_claim_summary(claims, analyst_stats)

    review_queue_path = Path(settings.runs_dir) / task.task_id / "review_queue.json"
    if review_queue_path.exists():
        review_queue = json.loads(review_queue_path.read_text(encoding="utf-8"))
        typer.echo(f"Review Queue: {len(review_queue)} entries")

    typer.echo(f"task_id: {task.task_id}")
    typer.echo(f"run_id: {agent_run.run_id}")
    typer.echo(f"report: {settings.runs_dir}/{task.task_id}/report.md")


def _print_claim_summary(claims: list[dict], stats: dict) -> None:
    single = [c for c in claims if c.get("competitor_name")]
    cross = [c for c in claims if not c.get("competitor_name")]
    by_comp: dict[str, int] = {}
    by_dim: dict[str, int] = {}
    accepted = 0
    uncertain = 0
    dropped = 0
    bilingual = 0
    en_re = re.compile(r"[a-zA-Z]{3,}")
    for claim in claims:
        comp = claim.get("competitor_name") or "CROSS"
        by_comp[comp] = by_comp.get(comp, 0) + 1
        dim = claim.get("dimension") or "?"
        by_dim[dim] = by_dim.get(dim, 0) + 1
        score = claim.get("support_score") or 0.0
        if score >= 0.6:
            accepted += 1
        elif score >= 0.3:
            uncertain += 1
        else:
            dropped += 1
        if len(en_re.findall(claim.get("statement") or "")) >= 2:
            bilingual += 1

    total = len(claims) or 1
    comp_text = ", ".join(f"{k}={v}" for k, v in sorted(by_comp.items()))
    dim_text = ", ".join(f"{k}={v}" for k, v in sorted(by_dim.items()))
    typer.echo("===== Claim Quality Summary =====")
    typer.echo(f"Claims: {len(single)} single + {len(cross)} cross = {len(claims)} total")
    typer.echo(f"Per competitor: {comp_text}")
    typer.echo(f"Per dimension:  {dim_text}")
    typer.echo(
        f"Accepted (support>=0.6): {accepted}/{len(claims)} "
        f"({_percent(accepted / total)})"
    )
    typer.echo(
        f"Uncertain (0.3-0.6):    {uncertain}/{len(claims)} "
        f"({_percent(uncertain / total)})"
    )
    typer.echo(
        f"Dropped (<0.3):         {dropped}/{len(claims)} "
        f"({_percent(dropped / total)})"
    )
    typer.echo(
        f"Bilingual statement rate: {_percent(bilingual / total)} "
        f"({bilingual}/{len(claims)})"
    )
    cost = stats.get("llm_cost_usd", 0.0)
    typer.echo(f"LLM cost: ${cost:.4f}")
    typer.echo("=================================\n")


@app.command()
def status(
    task_id: str = typer.Option(..., help="task_id"),
) -> None:
    """Show a historical run summary."""
    settings = load_settings()
    db.init_db(settings.db_path)
    summary = db.get_run_summary(task_id)
    if not summary:
        typer.echo(f"task not found: {task_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


@app.command("export-html")
def export_html(
    task_id: str = typer.Option(..., help="task_id"),
) -> None:
    """Export a completed run report as a standalone HTML file."""
    settings = load_settings()
    run_dir = Path(settings.runs_dir) / task_id
    if not run_dir.exists():
        typer.echo(f"run directory not found: {run_dir}", err=True)
        raise typer.Exit(code=1)
    report_path = run_dir / "report.md"
    if not report_path.exists():
        typer.echo(f"report not found: {report_path}", err=True)
        raise typer.Exit(code=1)

    html_path = export_html_report(run_dir)
    typer.echo(str(html_path))


@app.command("judge")
def judge(
    task_id: str = typer.Option(..., help="task_id"),
) -> None:
    """Run semantic judge on discarded claims for an existing run."""
    settings = load_settings()
    run_dir = Path(settings.runs_dir) / task_id
    if not run_dir.exists():
        typer.echo(f"run directory not found: {run_dir}", err=True)
        raise typer.Exit(code=1)
    discarded_path = run_dir / "discarded_claims.json"
    evidence_path = run_dir / "evidence.json"
    if not discarded_path.exists() or not evidence_path.exists():
        typer.echo(
            f"missing discarded_claims.json or evidence.json in {run_dir}",
            err=True,
        )
        raise typer.Exit(code=1)

    report_path, markdown_path = write_semantic_judge_report(run_dir)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    typer.echo(str(report_path))
    typer.echo(str(markdown_path))
    typer.echo(
        "Semantic Judge: "
        f"{report.get('total_judged', 0)} judged | "
        f"supported={report.get('supported_count', 0)} | "
        f"partial={report.get('partial_count', 0)} | "
        f"unsupported={report.get('unsupported_count', 0)} | "
        f"failed={report.get('judge_failed_count', 0)} | "
        f"cost=${float(report.get('llm_cost_usd') or 0.0):.4f}"
    )


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Web server host"),
    port: int = typer.Option(8000, help="Web server port"),
) -> None:
    """Start the cs-mvp web dashboard."""
    import socket as _socket

    import uvicorn

    def _port_in_use(candidate: int) -> bool:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as sock:
            return sock.connect_ex(("127.0.0.1", candidate)) == 0

    if _port_in_use(port):
        typer.echo(f"[cs-mvp] port {port} is in use; trying {port + 1}")
        port = port + 1
        if _port_in_use(port):
            typer.echo(
                f"[cs-mvp] port {port} is also in use; specify --port manually",
                err=True,
            )
            raise typer.Exit(1)

    uvicorn.run(
        "cs_mvp.web.app:fastapi_app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    app()
