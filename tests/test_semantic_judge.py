from __future__ import annotations

import json
from pathlib import Path

from cs_mvp.tools.semantic_judge import (
    judge_one_claim,
    judge_run_dir,
    write_semantic_judge_placeholder,
    write_semantic_judge_report,
)


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 5}


class _FakeLLM:
    model_name = "fake-semantic"

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> _FakeResponse:
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.responses) - 1)
        return _FakeResponse(self.responses[index])


def _payload(verdict: str, confidence: float = 0.9) -> str:
    action = {
        "supported": "promote_to_accepted",
        "partial": "human_review",
        "unsupported": "keep_as_fail",
    }[verdict]
    return json.dumps(
        {
            "semantic_verdict": verdict,
            "semantic_confidence": confidence,
            "reasoning": "Evidence states the concrete product detail needed for this judgment.",
            "suggested_action": action,
        }
    )


def _claim(verdict: str = "uncertain", score: float = 0.42) -> dict:
    return {
        "claim_id": "C-1",
        "statement": "Cursor Pro costs $20 per month.",
        "evidence_ids": ["E-1"],
        "support_score": score,
        "verdict": verdict,
    }


def _evidence_map() -> dict[str, dict]:
    return {
        "E-1": {
            "evidence_id": "E-1",
            "source_id": "S-1",
            "competitor_name": "Cursor",
            "claim_type": "pricing",
            "quote": "Cursor Pro costs $20 per month.",
            "normalized_fact": "Cursor Pro is $20/mo.",
        }
    }


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "T-judge"
    run_dir.mkdir()
    (run_dir / "report.md").write_text("# Report\n\nStable bytes.", encoding="utf-8")
    _write_json(
        run_dir / "claims.json",
        [
            {
                "claim_id": "C-accepted",
                "statement": "Accepted claim.",
                "evidence_ids": ["E-1"],
            }
        ],
    )
    _write_json(
        run_dir / "discarded_claims.json",
        [
            {
                "claim_id": "C-supported",
                "statement": "Cursor Pro costs $20 per month.",
                "evidence_ids": ["E-1"],
                "support_score": 0.42,
                "verdict": "uncertain",
            },
            {
                "claim_id": "C-partial",
                "statement": "Cursor includes all enterprise controls.",
                "evidence_ids": ["E-2"],
                "support_score": 0.35,
                "verdict": "uncertain",
            },
            {
                "claim_id": "C-unsupported",
                "statement": "Cursor is free for every plan.",
                "evidence_ids": ["E-3"],
                "support_score": 0.12,
                "verdict": "fail",
            },
        ],
    )
    _write_json(
        run_dir / "evidence.json",
        [
            {
                "evidence_id": "E-1",
                "source_id": "S-1",
                "competitor_name": "Cursor",
                "claim_type": "pricing",
                "quote": "Cursor Pro costs $20 per month.",
                "normalized_fact": "Cursor Pro is $20/mo.",
            },
            {
                "evidence_id": "E-2",
                "source_id": "S-2",
                "competitor_name": "Cursor",
                "claim_type": "feature",
                "quote": "Cursor supports SSO on enterprise plans.",
                "normalized_fact": "Cursor has some enterprise controls.",
            },
            {
                "evidence_id": "E-3",
                "source_id": "S-3",
                "competitor_name": "Cursor",
                "claim_type": "pricing",
                "quote": "Cursor Pro costs $20 per month.",
                "normalized_fact": "Cursor Pro is paid.",
            },
        ],
    )
    return run_dir


def test_judge_one_claim_supported() -> None:
    result = judge_one_claim(_claim(), _evidence_map(), _FakeLLM([_payload("supported")]))

    assert result["semantic_verdict"] == "supported"
    assert result["suggested_action"] == "promote_to_accepted"
    assert result["competitor_name"] == "Cursor"


def test_judge_one_claim_partial() -> None:
    result = judge_one_claim(_claim(), _evidence_map(), _FakeLLM([_payload("partial", 0.6)]))

    assert result["semantic_verdict"] == "partial"
    assert result["suggested_action"] == "human_review"


def test_judge_one_claim_unsupported() -> None:
    result = judge_one_claim(_claim(verdict="fail", score=0.1), _evidence_map(), _FakeLLM([_payload("unsupported", 0.8)]))

    assert result["semantic_verdict"] == "unsupported"
    assert result["suggested_action"] == "keep_as_fail"


def test_judge_one_claim_retries_invalid_json() -> None:
    llm = _FakeLLM(["not json", _payload("supported")])

    result = judge_one_claim(_claim(), _evidence_map(), llm)

    assert result["semantic_verdict"] == "supported"
    assert len(llm.prompts) == 2
    assert "Previous response was invalid" in llm.prompts[1]


def test_judge_one_claim_records_failure_after_two_bad_responses() -> None:
    result = judge_one_claim(_claim(), _evidence_map(), _FakeLLM(["nope", "still nope"]))

    assert result["semantic_verdict"] == "judge_failed"
    assert result["suggested_action"] == "human_review"


def test_judge_run_dir_summary_counts(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    llm = _FakeLLM([
        _payload("supported"),
        _payload("partial"),
        _payload("unsupported"),
    ])

    report = judge_run_dir(run_dir, llm=llm)

    assert report["total_judged"] == 3
    assert report["supported_count"] == 1
    assert report["partial_count"] == 1
    assert report["unsupported_count"] == 1
    assert report["false_positive_estimate"] == 1
    assert report["judge_failed_count"] == 0


def test_write_semantic_judge_report_does_not_modify_main_artifacts(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    before = {
        name: (run_dir / name).read_bytes()
        for name in ("claims.json", "discarded_claims.json", "report.md")
    }

    write_semantic_judge_report(
        run_dir,
        llm=_FakeLLM([
            _payload("supported"),
            _payload("partial"),
            _payload("unsupported"),
        ]),
    )

    after = {
        name: (run_dir / name).read_bytes()
        for name in ("claims.json", "discarded_claims.json", "report.md")
    }
    assert after == before


def test_write_semantic_judge_report_writes_json_md_and_stats(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)

    json_path, md_path = write_semantic_judge_report(
        run_dir,
        llm=_FakeLLM([
            _payload("supported"),
            _payload("partial"),
            _payload("unsupported"),
        ]),
    )

    stats = json.loads((run_dir / "judge_stats.json").read_text(encoding="utf-8"))
    report = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    assert report["total_judged"] == 3
    assert stats["model"] == "fake-semantic"
    assert stats["llm_cost_usd"] == report["llm_cost_usd"]
    assert "Semantic Judge Report" in markdown


def test_write_semantic_judge_placeholder_is_non_destructive(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    existing = run_dir / "semantic_judge_report.json"
    _write_json(existing, {"total_judged": 1})

    path = write_semantic_judge_placeholder(run_dir)

    assert path == existing
    assert json.loads(existing.read_text(encoding="utf-8")) == {"total_judged": 1}
