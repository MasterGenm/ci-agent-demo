from __future__ import annotations

from pathlib import Path

from cs_mvp import db
from cs_mvp.agents import gap_fill
from cs_mvp.agents.gap_fill import build_gap_queries, find_gaps, run_gap_fill
from cs_mvp.models import (
    AgentRun,
    AnalysisClaim,
    AnalysisTask,
    CompetitorInput,
    EvidenceItem,
    GraphState,
)
from cs_mvp.tools.fetch import FetchResult
from cs_mvp.tools.search import SearchResult


def _task() -> AnalysisTask:
    return AnalysisTask(
        task_id="T-gap",
        query="AI IDE",
        competitors=[CompetitorInput(name="Cursor")],
    )


def _claim(
    dimension: str,
    *,
    competitor_name: str = "Cursor",
    accepted: bool = True,
    claim_id: str | None = None,
) -> AnalysisClaim:
    return AnalysisClaim(
        claim_id=claim_id or f"C-{competitor_name}-{dimension}",
        run_id="RUN-gap",
        competitor_name=competitor_name,
        dimension=dimension,  # type: ignore[arg-type]
        statement=f"{competitor_name} has {dimension}.",
        evidence_ids=["E-001"],
        accepted=accepted,
    )


def test_find_gaps_returns_missing_dims() -> None:
    claims = [_claim("features"), _claim("pricing")]

    gaps = find_gaps(claims, ["Cursor"])

    assert gaps == {"Cursor": ["target_users", "positioning"]}


def test_find_gaps_no_gaps() -> None:
    claims = [
        _claim("features"),
        _claim("pricing"),
        _claim("target_users"),
        _claim("positioning"),
    ]

    gaps = find_gaps(claims, ["Cursor"])

    assert gaps == {}


def test_find_gaps_ignores_rejected_claims() -> None:
    claims = [
        _claim("features"),
        _claim("pricing", accepted=False),
        _claim("target_users"),
        _claim("positioning"),
    ]

    gaps = find_gaps(claims, ["Cursor"])

    assert gaps == {"Cursor": ["pricing"]}


def test_build_gap_queries_structure() -> None:
    queries = build_gap_queries({"Copilot": ["pricing", "target_users"]})

    assert "Copilot" in queries
    assert queries["Copilot"]
    assert len(queries["Copilot"]) <= 2
    assert all("Copilot" in query for query in queries["Copilot"])


def test_run_gap_fill_no_gaps_skips_fetch(monkeypatch) -> None:
    state = GraphState(
        task=_task(),
        run_id="RUN-gap",
        claims=[
            _claim("features"),
            _claim("pricing"),
            _claim("target_users"),
            _claim("positioning"),
        ],
    )
    monkeypatch.setattr(gap_fill, "find_gaps", lambda claims, competitors: {})

    def fail_search(*args, **kwargs):
        raise AssertionError("search should not be called")

    monkeypatch.setattr(gap_fill, "search", fail_search)

    result = run_gap_fill(state)

    assert result == {"gap_fill_round": 1}


def test_run_gap_fill_respects_max_rounds(monkeypatch) -> None:
    state = GraphState(task=_task(), run_id="RUN-gap", gap_fill_round=1)

    def fail_search(*args, **kwargs):
        raise AssertionError("search should not be called")

    monkeypatch.setattr(gap_fill, "search", fail_search)

    result = run_gap_fill(state)

    assert result == {"gap_fill_round": 1}


def test_run_gap_fill_adds_gap_sources_evidence_and_claims(monkeypatch) -> None:
    state = GraphState(
        task=_task(),
        run_id="RUN-abcdef",
        claims=[_claim("features", claim_id="C-original")],
    )

    monkeypatch.setattr(
        gap_fill,
        "search",
        lambda query, competitor_name, max_results=5: [
            SearchResult(
                url=f"https://cursor.example/{abs(hash(query))}",
                title="Cursor product page",
                snippet="pricing and users",
                score=0.9,
                source_type_guess="official_site",
            )
        ],
    )
    monkeypatch.setattr(
        gap_fill,
        "fetch",
        lambda url: FetchResult(
            url=url,
            status="fetched",
            title="Cursor page",
            raw_text="Cursor page text " * 80,
            content_hash="hash",
        ),
    )

    def fake_extract(run_id, sources, **kwargs):
        return [
            EvidenceItem(
                evidence_id="E-gap",
                source_id=sources[0].source_id,
                competitor_name="Cursor",
                quote="Cursor pricing page",
            )
        ], [], {}

    def fake_analyze(run_id, evidence, competitor_names, **kwargs):
        return [
            _claim("pricing", claim_id="C-gap-pricing"),
        ], [], {}

    monkeypatch.setattr(gap_fill, "real_extract", fake_extract)
    monkeypatch.setattr(gap_fill, "real_analyze", fake_analyze)

    result = run_gap_fill(state)

    assert result["gap_fill_round"] == 1
    assert any(source["source_id"].startswith("S-GAP-abcdef-Cur-") for source in result["sources"])
    assert any(item["evidence_id"] == "E-gap" for item in result["evidence"])
    assert any(item["claim_id"] == "C-gap-pricing" for item in result["claims"])


def test_run_gap_fill_swallows_search_failure(monkeypatch) -> None:
    state = GraphState(task=_task(), run_id="RUN-gap", claims=[_claim("features")])

    def fail_search(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(gap_fill, "search", fail_search)

    result = run_gap_fill(state)

    assert result == {"gap_fill_round": 1}


def test_enable_gap_fill_flag_off_excludes_graph_node(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_GAP_FILL", "0")
    from cs_mvp.graph import _gap_fill_enabled, build_graph

    db_path = str(tmp_path / "cs_mvp.db")
    db.init_db(db_path)
    task = AnalysisTask(
        task_id="T-flag",
        query="AI IDE",
        competitors=[CompetitorInput(name="Cursor")],
    )
    db.insert_task(task)
    db.insert_run(AgentRun(run_id="RUN-flag", task_id=task.task_id))

    graph = build_graph(db_path, str(tmp_path / "runs"))

    assert _gap_fill_enabled() is False
    assert "gap_fill" not in graph.get_graph().nodes
