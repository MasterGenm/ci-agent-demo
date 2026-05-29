from __future__ import annotations

import json
from pathlib import Path

from cs_mvp.review_queue import build_review_queue, write_review_queue


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _base_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "T-review"
    run_dir.mkdir()
    _write_json(run_dir / "claims.json", [])
    _write_json(run_dir / "discarded_claims.json", [])
    _write_json(run_dir / "sources.json", [])
    _write_json(run_dir / "evidence.json", [])
    _write_json(run_dir / "extractor_failures.json", [])
    _write_json(
        run_dir / "run_summary.json",
        {"quality_gates": {"low_recall_competitors": []}},
    )
    return run_dir


def test_review_queue_empty_when_artifacts_are_clean(tmp_path: Path) -> None:
    run_dir = _base_run_dir(tmp_path)

    assert build_review_queue(run_dir) == []


def test_review_queue_includes_uncertain_claim(tmp_path: Path) -> None:
    run_dir = _base_run_dir(tmp_path)
    _write_json(
        run_dir / "evidence.json",
        [{"evidence_id": "E-1", "competitor_name": "Cursor"}],
    )
    _write_json(
        run_dir / "discarded_claims.json",
        [
            {
                "claim_id": "C-1",
                "statement": "Cursor has weakly supported claim.",
                "evidence_ids": ["E-1"],
                "support_score": 0.42,
                "verdict": "uncertain",
                "reason": "keyword support below pass threshold",
            }
        ],
    )

    queue = build_review_queue(run_dir)

    assert len(queue) == 1
    assert queue[0]["type"] == "claim_uncertain"
    assert queue[0]["severity"] == "medium"
    assert queue[0]["competitor_name"] == "Cursor"


def test_review_queue_includes_failed_claim(tmp_path: Path) -> None:
    run_dir = _base_run_dir(tmp_path)
    _write_json(
        run_dir / "discarded_claims.json",
        [
            {
                "claim_id": "C-2",
                "statement": "Unsupported claim.",
                "evidence_ids": [],
                "support_score": 0.1,
                "verdict": "fail",
            }
        ],
    )

    queue = build_review_queue(run_dir)

    assert queue[0]["type"] == "claim_failed"
    assert queue[0]["severity"] == "low"
    assert queue[0]["support_score"] == 0.1


def test_review_queue_includes_low_recall_competitor(tmp_path: Path) -> None:
    run_dir = _base_run_dir(tmp_path)
    _write_json(
        run_dir / "run_summary.json",
        {"quality_gates": {"low_recall_competitors": ["Windsurf"]}},
    )
    _write_json(
        run_dir / "evidence.json",
        [{"evidence_id": "E-1", "competitor_name": "Cursor"}],
    )

    queue = build_review_queue(run_dir)

    assert queue[0]["type"] == "low_recall_competitor"
    assert queue[0]["severity"] == "high"
    assert queue[0]["competitor_name"] == "Windsurf"
    assert queue[0]["evidence_count"] == 0


def test_review_queue_includes_failed_source_and_quote_mismatch(tmp_path: Path) -> None:
    run_dir = _base_run_dir(tmp_path)
    _write_json(
        run_dir / "sources.json",
        [
            {
                "source_id": "S-1",
                "competitor_name": "Cursor",
                "url": "https://cursor.example",
                "fetch_status": "failed",
                "failure_reason": "timeout",
            }
        ],
    )
    _write_json(
        run_dir / "extractor_failures.json",
        [
            {
                "source_id": "S-1",
                "chunk_id": "S-1#chunk-00",
                "stage": "quote_match",
                "error": "quote_not_in_raw_text",
                "quote_preview": "Quoted sentence not present in source.",
            }
        ],
    )

    types = {entry["type"] for entry in build_review_queue(run_dir)}

    assert "source_fetch_failed" in types
    assert "extractor_quote_mismatch" in types


def test_review_queue_sorts_by_severity_desc(tmp_path: Path) -> None:
    run_dir = _base_run_dir(tmp_path)
    _write_json(
        run_dir / "run_summary.json",
        {"quality_gates": {"low_recall_competitors": ["Mem"]}},
    )
    _write_json(
        run_dir / "sources.json",
        [{"source_id": "S-1", "fetch_status": "failed"}],
    )
    _write_json(
        run_dir / "discarded_claims.json",
        [
            {
                "claim_id": "C-1",
                "statement": "Uncertain claim.",
                "support_score": 0.5,
                "verdict": "uncertain",
                "evidence_ids": [],
            },
            {
                "claim_id": "C-2",
                "statement": "Failed claim.",
                "support_score": 0.1,
                "verdict": "fail",
                "evidence_ids": [],
            },
        ],
    )

    queue = build_review_queue(run_dir)

    assert [entry["severity"] for entry in queue] == ["high", "medium", "low", "low"]


def test_write_review_queue_writes_json_array(tmp_path: Path) -> None:
    run_dir = _base_run_dir(tmp_path)

    path = write_review_queue(run_dir)

    assert path == run_dir / "review_queue.json"
    assert json.loads(path.read_text(encoding="utf-8")) == []
