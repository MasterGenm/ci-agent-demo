from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cs_mvp.models import (
    AgentNodeRun,
    AgentRun,
    AnalysisClaim,
    AnalysisTask,
    EvidenceItem,
    Report,
    SourceRecord,
)

_DB_PATH = "data/cs_mvp.db"


def configure(db_path: str) -> None:
    global _DB_PATH
    _DB_PATH = db_path


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json(data: Any) -> str:
    if hasattr(data, "model_dump"):
        return data.model_dump_json()
    return json.dumps(data, ensure_ascii=False, default=str)


def _dt(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def init_db(db_path: str) -> None:
    configure(db_path)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS analysis_tasks (
                task_id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                input_json TEXT NOT NULL,
                scope_json TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                total_cost_usd REAL DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES analysis_tasks(task_id)
            );

            CREATE TABLE IF NOT EXISTS agent_node_runs (
                node_run_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                input_json TEXT,
                output_json TEXT,
                llm_model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cost_usd REAL,
                latency_ms INTEGER,
                error_message TEXT,
                FOREIGN KEY (run_id) REFERENCES agent_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                competitor_name TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                source_type TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                published_at TEXT,
                content_hash TEXT,
                raw_text TEXT,
                reliability_score REAL,
                fetch_status TEXT,
                failure_reason TEXT,
                raw_text_length INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                competitor_name TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                quote TEXT NOT NULL,
                normalized_fact TEXT,
                confidence REAL,
                extracted_at TEXT NOT NULL,
                source_chunk_index INTEGER
            );

            CREATE TABLE IF NOT EXISTS analysis_claims (
                claim_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                competitor_name TEXT,
                dimension TEXT NOT NULL,
                statement TEXT NOT NULL,
                evidence_ids_json TEXT NOT NULL,
                support_score REAL,
                confidence REAL,
                accepted INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                format TEXT NOT NULL,
                file_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        _ensure_sources_columns(conn)
        _ensure_evidence_columns(conn)
        conn.execute(
            """
            CREATE VIEW IF NOT EXISTS source_records AS
            SELECT * FROM sources
            """
        )
        _ensure_evidence_items_view(conn)


def _ensure_sources_columns(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
    for col, ddl in [
        ("fetch_status", "ALTER TABLE sources ADD COLUMN fetch_status TEXT"),
        ("failure_reason", "ALTER TABLE sources ADD COLUMN failure_reason TEXT"),
        (
            "raw_text_length",
            "ALTER TABLE sources ADD COLUMN raw_text_length INTEGER DEFAULT 0",
        ),
    ]:
        if col not in cols:
            conn.execute(ddl)


def _ensure_evidence_columns(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(evidence)")}
    if "source_chunk_index" not in cols:
        conn.execute("ALTER TABLE evidence ADD COLUMN source_chunk_index INTEGER")


def _ensure_evidence_items_view(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        """
        SELECT type
        FROM sqlite_master
        WHERE name = 'evidence_items'
        """
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            CREATE VIEW evidence_items AS
            SELECT * FROM evidence
            """
        )


def insert_task(task: AnalysisTask) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO analysis_tasks (
                task_id, query, input_json, scope_json, status, created_at,
                completed_at, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.query,
                task.model_dump_json(),
                task.scope.model_dump_json(),
                task.status,
                _dt(task.created_at),
                _dt(task.completed_at),
                task.error_message,
            ),
        )


def update_task_status(task_id: str, status: str, error: str | None = None) -> None:
    completed_expr = "datetime('now')" if status in {"completed", "failed"} else "completed_at"
    with _connect() as conn:
        conn.execute(
            f"""
            UPDATE analysis_tasks
            SET status = ?, completed_at = {completed_expr}, error_message = ?
            WHERE task_id = ?
            """,
            (status, error, task_id),
        )


def insert_run(run: AgentRun) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_runs (
                run_id, task_id, started_at, ended_at, status,
                total_cost_usd, total_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.task_id,
                _dt(run.started_at),
                _dt(run.ended_at),
                run.status,
                run.total_cost_usd,
                run.total_tokens,
            ),
        )


def update_run_status(run_id: str, status: str, cost: float, tokens: int) -> None:
    ended_expr = "datetime('now')" if status in {"completed", "failed"} else "ended_at"
    with _connect() as conn:
        conn.execute(
            f"""
            UPDATE agent_runs
            SET status = ?, ended_at = {ended_expr}, total_cost_usd = ?, total_tokens = ?
            WHERE run_id = ?
            """,
            (status, cost, tokens, run_id),
        )


def insert_node_run(node_run: AgentNodeRun) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_node_runs (
                node_run_id, run_id, node_name, started_at, ended_at, status,
                input_json, output_json, llm_model, input_tokens, output_tokens,
                cost_usd, latency_ms, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_run.node_run_id,
                node_run.run_id,
                node_run.node_name,
                _dt(node_run.started_at),
                _dt(node_run.ended_at),
                node_run.status,
                node_run.input_json,
                node_run.output_json,
                node_run.llm_model,
                node_run.input_tokens,
                node_run.output_tokens,
                node_run.cost_usd,
                node_run.latency_ms,
                node_run.error_message,
            ),
        )


def update_node_run(
    node_run_id: str,
    status: str,
    output_json: str,
    latency_ms: int,
    error: str | None = None,
    llm_model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE agent_node_runs
            SET status = ?, ended_at = datetime('now'), output_json = ?,
                latency_ms = ?, error_message = ?,
                llm_model = COALESCE(?, llm_model),
                input_tokens = COALESCE(?, input_tokens),
                output_tokens = COALESCE(?, output_tokens),
                cost_usd = COALESCE(?, cost_usd)
            WHERE node_run_id = ?
            """,
            (
                status,
                output_json,
                latency_ms,
                error,
                llm_model,
                input_tokens,
                output_tokens,
                cost_usd,
                node_run_id,
            ),
        )


def insert_source(source: SourceRecord) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO sources (
                source_id, run_id, competitor_name, url, title, source_type,
                retrieved_at, published_at, content_hash, raw_text, reliability_score,
                fetch_status, failure_reason, raw_text_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.source_id,
                source.run_id,
                source.competitor_name,
                source.url,
                source.title,
                source.source_type,
                _dt(source.retrieved_at),
                _dt(source.published_at),
                source.content_hash,
                source.raw_text,
                source.reliability_score,
                source.fetch_status,
                source.failure_reason,
                source.raw_text_length,
            ),
        )


def insert_evidence(ev: EvidenceItem) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence (
                evidence_id, source_id, competitor_name, claim_type, quote,
                normalized_fact, confidence, extracted_at, source_chunk_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ev.evidence_id,
                ev.source_id,
                ev.competitor_name,
                ev.claim_type,
                ev.quote,
                ev.normalized_fact,
                ev.confidence,
                _dt(ev.extracted_at),
                ev.source_chunk_index,
            ),
        )


def insert_claim(claim: AnalysisClaim) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO analysis_claims (
                claim_id, run_id, competitor_name, dimension, statement,
                evidence_ids_json, support_score, confidence, accepted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.claim_id,
                claim.run_id,
                claim.competitor_name,
                claim.dimension,
                claim.statement,
                json.dumps(claim.evidence_ids, ensure_ascii=False),
                claim.support_score,
                claim.confidence,
                1 if claim.accepted else 0,
            ),
        )


def insert_report(report: Report) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO reports (report_id, run_id, format, file_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                report.report_id,
                report.run_id,
                report.format,
                report.file_path,
                _dt(report.created_at),
            ),
        )


def list_node_runs(run_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM agent_node_runs
            WHERE run_id = ?
            ORDER BY started_at ASC
            """,
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_sources_for_run(run_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE run_id = ?
            ORDER BY competitor_name ASC, source_id ASC
            """,
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_evidence_for_run(run_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT e.*
            FROM evidence e
            JOIN sources s ON s.source_id = e.source_id
            WHERE s.run_id = ?
            ORDER BY e.competitor_name ASC, e.evidence_id ASC
            """,
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _url_key(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


_WS_RE = re.compile(r"\s+")


def _normalize_text(text: str | None) -> str:
    return _WS_RE.sub(" ", text or "").strip().lower()


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def get_evidence_quality_summary(run_id: str) -> dict[str, Any]:
    evidence = list_evidence_for_run(run_id)
    source_by_id = {
        source["source_id"]: source for source in list_sources_for_run(run_id)
    }
    per_competitor: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    quote_matches = 0
    seen_facts: set[tuple[str, str]] = set()
    duplicates = 0
    confidences: list[float] = []
    quote_lengths: list[int] = []

    for item in evidence:
        competitor = item.get("competitor_name") or "unknown"
        per_competitor[competitor] = per_competitor.get(competitor, 0) + 1
        claim_type = item.get("claim_type") or "other"
        type_counts[claim_type] = type_counts.get(claim_type, 0) + 1

        quote = item.get("quote") or ""
        quote_lengths.append(len(quote))
        source = source_by_id.get(item.get("source_id"))
        raw_text = source.get("raw_text") if source else ""
        if quote and _normalize_text(quote) in _normalize_text(raw_text):
            quote_matches += 1

        normalized_fact = _normalize_text(item.get("normalized_fact"))
        key = (competitor, normalized_fact)
        if normalized_fact:
            if key in seen_facts:
                duplicates += 1
            seen_facts.add(key)

        confidence = item.get("confidence")
        if confidence is not None:
            confidences.append(float(confidence))

    total = len(evidence)
    return {
        "total": total,
        "per_competitor": per_competitor,
        "per_competitor_text": _format_counts(per_competitor),
        "types": type_counts,
        "types_text": _format_counts(type_counts),
        "quote_match_rate": round(quote_matches / total, 3) if total else 0.0,
        "duplicate_rate": round(duplicates / total, 3) if total else 0.0,
        "quote_length_min": min(quote_lengths) if quote_lengths else 0,
        "quote_length_max": max(quote_lengths) if quote_lengths else 0,
        "confidence_min": min(confidences) if confidences else None,
        "confidence_max": max(confidences) if confidences else None,
    }


def get_source_quality_summary(run_id: str) -> dict[str, Any]:
    sources = list_sources_for_run(run_id)
    status_counts = {"fetched": 0, "failed": 0, "empty": 0, "skipped": 0}
    type_counts: dict[str, int] = {}
    per_competitor: dict[str, int] = {}
    seen_urls: set[str] = set()
    valid_lengths: list[int] = []

    for source in sources:
        status = source.get("fetch_status") or "skipped"
        status_counts[status] = status_counts.get(status, 0) + 1
        source_type = source.get("source_type") or "other"
        type_counts[source_type] = type_counts.get(source_type, 0) + 1

        key = _url_key(source["url"])
        is_duplicate = key in seen_urls
        seen_urls.add(key)
        is_valid = (
            status == "fetched"
            and (source.get("raw_text_length") or 0) >= 500
            and bool(source.get("content_hash"))
            and not is_duplicate
        )
        if is_valid:
            competitor = source["competitor_name"]
            per_competitor[competitor] = per_competitor.get(competitor, 0) + 1
            valid_lengths.append(source["raw_text_length"])

    total = len(sources)
    valid = len(valid_lengths)
    avg_valid_length = int(sum(valid_lengths) / valid) if valid else 0
    return {
        "total": total,
        "fetched": status_counts.get("fetched", 0),
        "failed": status_counts.get("failed", 0),
        "empty": status_counts.get("empty", 0),
        "skipped": status_counts.get("skipped", 0),
        "valid": valid,
        "per_competitor": per_competitor,
        "per_competitor_text": _format_counts(per_competitor),
        "types": type_counts,
        "types_text": _format_counts(type_counts),
        "avg_valid_length": avg_valid_length,
    }


def get_run_summary(task_id: str) -> dict[str, Any]:
    with _connect() as conn:
        task = conn.execute(
            "SELECT * FROM analysis_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            return {}
        run = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        node_runs = []
        if run is not None:
            node_runs = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT node_name, status, started_at, ended_at, latency_ms
                    FROM agent_node_runs
                    WHERE run_id = ?
                    ORDER BY started_at ASC
                    """,
                    (run["run_id"],),
                ).fetchall()
            ]
        counts = {
            "sources": conn.execute(
                "SELECT COUNT(*) AS count FROM sources WHERE run_id = ?",
                (run["run_id"] if run else "",),
            ).fetchone()["count"],
            "evidence": conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM evidence
                WHERE source_id IN (
                    SELECT source_id FROM sources WHERE run_id = ?
                )
                """,
                (run["run_id"] if run else "",),
            ).fetchone()["count"],
            "claims": conn.execute(
                "SELECT COUNT(*) AS count FROM analysis_claims WHERE run_id = ?",
                (run["run_id"] if run else "",),
            ).fetchone()["count"],
        }

    return {
        "task": dict(task),
        "run": dict(run) if run is not None else None,
        "node_runs": node_runs,
        "counts": counts,
    }


def to_json(data: Any) -> str:
    return _json(data)
