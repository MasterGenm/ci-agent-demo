from __future__ import annotations

import re
from datetime import datetime

from cs_mvp.models import AnalysisClaim, DiscardedClaim, EvidenceItem


_CHINESE_WINDOW_MIN = 2
_CHINESE_WINDOW_MAX = 4
_CROSS_CLAIM_PASS_THRESHOLD = 0.4
_SINGLE_CLAIM_PASS_THRESHOLD = 0.6


def _chinese_substrings(segment: str) -> set[str]:
    """\u5bf9\u4e00\u6bb5\u8fde\u7eed\u4e2d\u6587,\u7528 2-4 \u5b57\u6ed1\u52a8\u7a97\u53e3\u53d6\u6240\u6709 substring\u3002

    \u4f8b\u5982 "\u672a\u6388\u6743\u4efb\u4f55" \u4f1a\u5c55\u5f00\u4e3a
    {\u672a\u6388, \u672a\u6388\u6743, \u672a\u6388\u6743\u4efb, \u6388\u6743, \u6388\u6743\u4efb, \u6388\u6743\u4efb\u4f55, \u6743\u4efb, \u6743\u4efb\u4f55, \u4efb\u4f55}

    \u8fd9\u6837 claim \u91cc\u7684"\u672a\u6388\u6743\u4efb\u4f55"\u548c evidence \u91cc\u7684"\u672a\u6388\u6743"\u80fd\u5728 substring \u7ea7\u522b\u547d\u4e2d,
    \u800c\u4e0d\u662f\u8981\u6c42\u6574\u6bb5\u7cbe\u786e\u5339\u914d\u3002
    """
    result: set[str] = set()
    n = len(segment)
    for size in range(_CHINESE_WINDOW_MIN, _CHINESE_WINDOW_MAX + 1):
        for start in range(0, n - size + 1):
            result.add(segment[start : start + size])
    return result


def extract_keywords(text: str) -> set[str]:
    """Extract loose matching keywords from claim or evidence text.

    M3 \u8c03\u6574:\u4e2d\u6587 phrase \u7528 2-4 \u5b57\u6ed1\u52a8\u7a97\u53e3\u5c55\u5f00,\u907f\u514d"\u672a\u6388\u6743\u4efb\u4f55"\u8fd9\u79cd\u957f phrase
    \u5728\u53cc\u8bed claim/evidence \u4e4b\u95f4\u6c38\u8fdc\u5339\u914d\u4e0d\u4e0a\u3002
    \u6570\u5b57\u5fc5\u987b >= 2 \u4f4d,\u907f\u514d\u5355\u5b57\u7b26 "6"\u3001"019" \u8bef\u5339\u914d\u3002
    """
    keywords: set[str] = set()
    # \u7f8e\u5143\u91d1\u989d
    keywords.update(re.findall(r"\$[\d,]+(?:\.\d+)?", text))
    # \u591a\u4f4d\u6570\u5b57 / \u767e\u5206\u53f7(>=2 \u4f4d,\u6392\u9664\u5355\u5b57\u7b26\u566a\u97f3)
    keywords.update(re.findall(r"\d{2,}\.?\d*%?", text))
    # \u5927\u5199\u5f00\u5934\u82f1\u6587\u8bcd(\u4ea7\u54c1\u540d\u3001\u9996\u5b57\u6bcd\u5927\u5199\u6982\u5ff5)
    keywords.update(re.findall(r"[A-Z][a-zA-Z]{2,}", text))
    # \u4e2d\u6587 phrase:\u5bf9\u6bcf\u6bb5\u8fde\u7eed\u4e2d\u6587\u505a 2-4 \u5b57\u6ed1\u52a8\u7a97\u53e3
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        keywords.update(_chinese_substrings(segment))
    return {keyword.lower() for keyword in keywords if keyword}


def compute_support_score(
    claim: AnalysisClaim,
    evidence_map: dict[str, EvidenceItem],
) -> tuple[float, str]:
    """Return a loose string-match support score and a human-readable reason."""
    if not claim.evidence_ids:
        return 0.0, "claim 没有关联任何 evidence_id"

    claim_keywords = extract_keywords(claim.statement)
    if not claim_keywords:
        return 0.5, "claim 无可提取关键词，默认 uncertain"

    matched_keywords: set[str] = set()
    missing_evidence_ids: list[str] = []

    for evidence_id in claim.evidence_ids:
        evidence = evidence_map.get(evidence_id)
        if evidence is None:
            missing_evidence_ids.append(evidence_id)
            continue
        # M3 修复:同时读 quote(原文,多为英文)+ normalized_fact(M2 已中文标准化)
        # 双语 claim 才能在跨语言场景下被关键词匹配命中。
        evidence_text = (evidence.quote or "") + " " + (evidence.normalized_fact or "")
        evidence_keywords = extract_keywords(evidence_text)
        matched_keywords.update(claim_keywords & evidence_keywords)

    if missing_evidence_ids:
        reason_prefix = f"evidence_id {missing_evidence_ids} 不存在于证据库；"
    else:
        reason_prefix = ""

    score = len(matched_keywords) / len(claim_keywords)
    unmatched = claim_keywords - matched_keywords
    reason = reason_prefix + (
        f"关键词匹配 {len(matched_keywords)}/{len(claim_keywords)}，"
        f"未匹配：{list(unmatched)[:3]}"
    )
    return round(score, 3), reason


def verify_claim(
    claim: AnalysisClaim,
    evidence_map: dict[str, EvidenceItem],
) -> tuple[AnalysisClaim | None, DiscardedClaim | None]:
    """Return accepted claim and optional review finding."""
    score, reason = compute_support_score(claim, evidence_map)
    claim.support_score = score
    pass_threshold = (
        _CROSS_CLAIM_PASS_THRESHOLD
        if claim.competitor_name is None
        else _SINGLE_CLAIM_PASS_THRESHOLD
    )

    if score >= pass_threshold:
        claim.accepted = True
        return claim, None

    discarded = DiscardedClaim(
        claim_id=claim.claim_id,
        statement=claim.statement,
        evidence_ids=claim.evidence_ids,
        support_score=score,
        verdict="uncertain" if score >= 0.3 else "fail",
        reason=reason,
        dropped_at=datetime.utcnow(),
    )
    if score >= 0.3:
        claim.accepted = True
        return claim, discarded

    claim.accepted = False
    return None, discarded
