from __future__ import annotations

from typing import Any

from cs_mvp.agents import analyst
from cs_mvp.models import EvidenceItem


VALID_BI_STATEMENT = "Cursor 的 Individual 方案定价为 20 美元/月(Individual $20/mo.),并支持 Agent 模式。"


import threading


class FakeStructuredLLM:
    """invoke 时根据 prompt 内容决定返回哪个响应。

    并发友好:不依赖队列顺序,通过解析 prompt 中的 competitor + dimension
    定位预设响应。如果没匹配,退回共享队列(用于测试简单场景)。
    """

    def __init__(self, owner: "FakeLLM", schema_name: str) -> None:
        self.owner = owner
        self.schema_name = schema_name

    def invoke(self, prompt: str) -> Any:
        # 优先匹配预设映射(by_match)
        with self.owner._lock:
            for matcher, response in list(self.owner._by_match.get(self.schema_name, [])):
                if matcher(prompt):
                    if isinstance(response, Exception):
                        raise response
                    return response
            queue = self.owner._queue_for(self.schema_name)
            if not queue:
                return {"items": []}
            r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeLLM:
    """支持两种响应映射模式:
    1. by_schema={schema_name: [resp, ...]}: 按队列 pop
    2. by_match={schema_name: [(matcher_fn, resp), ...]}: 按 prompt 内容匹配
       (适合并发场景,不依赖顺序)
    """

    model = "qwen3.6-plus"

    def __init__(
        self,
        responses: list[Any] | None = None,
        by_schema: dict[str, list[Any]] | None = None,
        by_match: dict[str, list[tuple]] | None = None,
    ) -> None:
        self._global: list[Any] = list(responses or [])
        self._by_schema: dict[str, list[Any]] = {
            k: list(v) for k, v in (by_schema or {}).items()
        }
        self._by_match: dict[str, list[tuple]] = {
            k: list(v) for k, v in (by_match or {}).items()
        }
        self._lock = threading.Lock()

    def _queue_for(self, schema_name: str) -> list[Any]:
        if schema_name in self._by_schema:
            return self._by_schema[schema_name]
        return self._global

    def with_structured_output(self, schema_cls: Any, **kwargs: Any) -> FakeStructuredLLM:
        return FakeStructuredLLM(self, schema_cls.__name__)


def _has(needles: tuple[str, ...]):
    """构造一个 prompt 匹配函数:prompt 必须包含所有 needle。"""
    def matcher(prompt: str) -> bool:
        return all(n in prompt for n in needles)
    return matcher


def _ev(eid: str, competitor: str, claim_type: str = "feature", quote: str = "x" * 60) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=eid,
        source_id=f"S-{eid}",
        competitor_name=competitor,
        claim_type=claim_type,  # type: ignore[arg-type]
        quote=quote,
        normalized_fact="standard fact",
        confidence=0.8,
    )


def _single_item(
    competitor: str = "Cursor",
    dimension: str = "features",
    statement: str = VALID_BI_STATEMENT,
    evidence_ids: list[str] | None = None,
    confidence: float = 0.85,
) -> dict:
    return {
        "competitor_name": competitor,
        "dimension": dimension,
        "statement": statement,
        "evidence_ids": evidence_ids or ["E1"],
        "confidence": confidence,
    }


def _cross_item(
    dimension: str = "pricing",
    statement: str = "Cursor 与 Windsurf 在 enterprise deployment 上路径差异显著,定价跨度约 2 倍(2x spread)。",
    evidence_ids: list[str] | None = None,
) -> dict:
    return {
        "competitor_name": None,
        "dimension": dimension,
        "statement": statement,
        "evidence_ids": evidence_ids or ["E1", "E2"],
        "confidence": 0.80,
    }


# ============ is_bilingual ============


def test_is_bilingual_detects_two_english_tokens() -> None:
    # Cursor + inline + suggestions 三个 token → 通过
    assert analyst.is_bilingual("Cursor 提供 inline suggestions 体验") is True


def test_is_bilingual_rejects_pure_chinese() -> None:
    assert analyst.is_bilingual("光纸提供编程辅助和代码补全功能") is False


def test_is_bilingual_rejects_single_token_competitor_name_only() -> None:
    # 只含 "Cursor" 这一个英文 token, 应被判为非双语(防止空话)
    assert analyst.is_bilingual("Cursor 提供领先的 AI 编程体验") is False


def test_is_bilingual_accepts_two_tokens() -> None:
    # Cursor + Pro 恰好 2 个 token → 通过
    assert analyst.is_bilingual("Cursor 定价(Pro)") is True


def test_is_bilingual_rejects_pure_numbers() -> None:
    assert analyst.is_bilingual("定价 $20 元") is False


# ============ real_analyze - phase 1 single ============


def test_real_analyze_generates_single_claims_for_each_competitor(monkeypatch) -> None:
    """4 个 dimension × 1 个 competitor = 4 次 LLM 调用,按 dimension 匹配响应。"""
    evidence = [
        _ev("E1", "Cursor", "feature"),
        _ev("E2", "Cursor", "pricing"),
        _ev("E3", "Cursor", "positioning"),
        _ev("E4", "Cursor", "metric"),
    ]
    # 按 dimension 关键词匹配,确保 prompt 提到的 dimension 与响应一致
    by_match = {
        "LLMClaimList": [
            (_has(("Cursor", f"dimension: {d}")),
             {"items": [_single_item(dimension=d, evidence_ids=["E1"])]})
            for d in ("features", "pricing", "positioning", "swot")
        ],
    }
    fake = FakeLLM(by_match=by_match)
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, stats = analyst.real_analyze(
        "RUN-abcdef",
        evidence,
        ["Cursor"],
    )

    # 4 个 single claim, 没有 cross(只有 1 个竞品)
    assert stats["single_claims"] == 4
    assert stats["cross_claims"] == 0
    assert stats["total_claims"] == 4
    assert failures == []


def test_real_analyze_rejects_monolingual_statement(monkeypatch) -> None:
    """LLM 返回单 token 英文 statement → 进 failures。"""
    evidence = [_ev("E1", "Cursor", "feature")]
    # 只含 "Cursor" 一个英文 token, 不达双语 ≥2 阈值
    monolingual = "Cursor 是一款 AI 编程助手,支持代码补全和对话编程。"
    by_match = {
        "LLMClaimList": [
            (_has(("Cursor", f"dimension: {d}")),
             {"items": [_single_item(dimension=d, statement=monolingual)]})
            for d in ("features", "pricing", "positioning", "swot")
        ],
    }
    fake = FakeLLM(by_match=by_match)
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, stats = analyst.real_analyze("RUN-abcdef", evidence, ["Cursor"])

    assert stats["single_claims"] == 0
    assert all(f.get("error") == "monolingual_statement" for f in failures)
    assert len(failures) >= 1


def test_real_analyze_rejects_invalid_evidence_id(monkeypatch) -> None:
    evidence = [_ev("E1", "Cursor", "feature")]
    by_match = {
        "LLMClaimList": [
            (_has(("Cursor", f"dimension: {d}")),
             {"items": [_single_item(dimension=d, evidence_ids=["E_NOT_EXIST"])]})
            for d in ("features", "pricing", "positioning", "swot")
        ],
    }
    fake = FakeLLM(by_match=by_match)
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, _ = analyst.real_analyze("RUN-abcdef", evidence, ["Cursor"])

    assert claims == []
    assert any(f["error"].startswith("invalid_evidence_ids") for f in failures)


def test_real_analyze_caps_at_3_claims_via_schema(monkeypatch) -> None:
    """LLM 试图返回 5 条 → Pydantic schema max_length=3 拒绝, 一次重试也失败 → failure。"""
    evidence = [_ev("E1", "Cursor", "feature")]
    # 任何 dimension 都返回 5 条 → schema 拒绝
    overflow = {"items": [_single_item() for _ in range(5)]}
    by_match = {
        "LLMClaimList": [
            (_has(("Cursor", f"dimension: {d}")), overflow)
            for d in ("features", "pricing", "positioning", "swot")
        ],
    }
    fake = FakeLLM(by_match=by_match)
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, stats = analyst.real_analyze("RUN-abcdef", evidence, ["Cursor"])

    assert stats["single_claims"] == 0
    assert any("schema_invalid" in f.get("error", "") for f in failures)


def test_real_analyze_accepts_bare_list_output(monkeypatch) -> None:
    """DashScope qwen 偶尔返回裸数组而非 {"items":[...]} - 兼容路径。"""
    evidence = [_ev("E1", "Cursor", "feature")]
    by_match = {
        "LLMClaimList": [
            (_has(("Cursor", f"dimension: {d}")),
             [_single_item(dimension=d)])
            for d in ("features", "pricing", "positioning", "swot")
        ],
    }
    fake = FakeLLM(by_match=by_match)
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, stats = analyst.real_analyze("RUN-abcdef", evidence, ["Cursor"])

    # 4 个 dimension 都收到合法 single claim(裸数组兼容)
    assert stats["single_claims"] >= 1


# ============ real_analyze - phase 2 cross ============


def test_real_analyze_cross_claim_requires_two_competitors(monkeypatch) -> None:
    """cross claim 引用只属于 1 个 competitor 的 evidence → 被拒。"""
    evidence = [
        _ev("E1", "Cursor", "feature"),
        _ev("E2", "Cursor", "feature"),
        _ev("E3", "Windsurf", "feature"),
    ]
    single_matches = []
    for comp in ("Cursor", "Windsurf"):
        for d in ("features", "pricing", "positioning", "swot"):
            single_matches.append((
                _has((comp, f"dimension: {d}")),
                {"items": [_single_item(comp, d, evidence_ids=["E1" if comp == "Cursor" else "E3"])]},
            ))
    # cross 对每个 dim 返回 1 条只引 Cursor 的 → 全部应被拒
    cross_matches = [
        (_has((f"dimension: {d}",)),
         {"items": [_cross_item(dimension=d, evidence_ids=["E1", "E2"])]})
        for d in ("features", "pricing", "positioning", "swot")
    ]
    fake = FakeLLM(by_match={"LLMClaimList": single_matches, "LLMCrossClaimList": cross_matches})
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, stats = analyst.real_analyze(
        "RUN-abcdef", evidence, ["Cursor", "Windsurf"]
    )

    assert stats["cross_claims"] == 0
    assert any(
        f.get("phase") == "cross" and "single_competitor" in f.get("error", "")
        for f in failures
    )


def test_real_analyze_cross_claim_accepted_when_two_competitors(monkeypatch) -> None:
    evidence = [
        _ev("E1", "Cursor", "pricing"),
        _ev("E2", "Windsurf", "pricing"),
    ]
    single_matches = []
    for comp in ("Cursor", "Windsurf"):
        for d in ("features", "pricing", "positioning", "swot"):
            single_matches.append((
                _has((comp, f"dimension: {d}")),
                {"items": [_single_item(comp, d, evidence_ids=["E1" if comp == "Cursor" else "E2"])]},
            ))
    # cross 对 4 个 dim 都返回引用 E1+E2 (两个不同竞品) 的 claim
    cross_matches = [
        (_has((f"dimension: {d}",)),
         {"items": [_cross_item(dimension=d, evidence_ids=["E1", "E2"])]})
        for d in ("features", "pricing", "positioning", "swot")
    ]
    fake = FakeLLM(by_match={"LLMClaimList": single_matches, "LLMCrossClaimList": cross_matches})
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, failures, stats = analyst.real_analyze(
        "RUN-abcdef", evidence, ["Cursor", "Windsurf"]
    )

    assert stats["cross_claims"] >= 1
    cross = [c for c in claims if c.competitor_name is None]
    assert all(c.competitor_name is None for c in cross)


def test_real_analyze_claim_ids_use_run_suffix(monkeypatch) -> None:
    evidence = [_ev("E1", "Cursor", "feature")]
    by_match = {
        "LLMClaimList": [
            (_has(("Cursor", f"dimension: {d}")),
             {"items": [_single_item(dimension=d)]})
            for d in ("features", "pricing", "positioning", "swot")
        ],
    }
    fake = FakeLLM(by_match=by_match)
    monkeypatch.setattr(analyst, "get_extractor_llm", lambda: fake)

    claims, _, _ = analyst.real_analyze("RUN-aabbcc112233", evidence, ["Cursor"])

    # run_suffix = "112233"
    assert len(claims) >= 1
    for c in claims:
        assert "112233" in c.claim_id


def test_mock_analyze_still_works() -> None:
    """保留 mock_analyze 兼容 M0/M2 测试。"""
    claim = analyst.mock_analyze("RUN-abc", "Cursor", "features", ["E1", "E2"])
    assert claim.competitor_name == "Cursor"
    assert claim.evidence_ids == ["E1"]
