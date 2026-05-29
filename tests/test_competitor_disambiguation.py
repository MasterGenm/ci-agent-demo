from __future__ import annotations

from cs_mvp.cli import _is_niche_name, _parse_competitors
from cs_mvp.tools.search import _exclude_clause, _hit_exclusion


def test_parse_competitors_simple_syntax() -> None:
    competitors = _parse_competitors("Cursor,Windsurf,Copilot")
    assert [c.name for c in competitors] == ["Cursor", "Windsurf", "Copilot"]
    assert all(c.exclude_keywords == [] for c in competitors)


def test_parse_competitors_with_exclude_keywords() -> None:
    competitors = _parse_competitors(
        "Cursor,GitHub Copilot|microsoft 365;copilot studio"
    )
    assert competitors[0].name == "Cursor"
    assert competitors[0].exclude_keywords == []
    assert competitors[1].name == "GitHub Copilot"
    assert competitors[1].exclude_keywords == ["microsoft 365", "copilot studio"]


def test_exclude_clause_quotes_phrases_with_spaces() -> None:
    clause = _exclude_clause(["microsoft 365", "studio", "copilot money"])
    assert '-"microsoft 365"' in clause
    assert "-studio" in clause
    assert '-"copilot money"' in clause


def test_hit_exclusion_case_insensitive() -> None:
    assert _hit_exclusion(
        "Microsoft 365 Copilot pricing", ["microsoft 365"]
    ) is True
    assert _hit_exclusion(
        "GitHub Copilot for VSCode", ["microsoft 365"]
    ) is False


def test_hit_exclusion_empty_keywords_returns_false() -> None:
    assert _hit_exclusion("anything", []) is False


# ============ M5 v0.2: niche 名检测 ============


def test_is_niche_name_detects_short_english_words() -> None:
    assert _is_niche_name("Mem") is True
    assert _is_niche_name("Box") is True
    assert _is_niche_name("Loop") is True
    assert _is_niche_name("Tana") is True


def test_is_niche_name_excludes_long_names() -> None:
    assert _is_niche_name("Notion") is False
    assert _is_niche_name("Cursor") is False
    assert _is_niche_name("Evernote") is False


def test_is_niche_name_excludes_names_with_dot_or_space() -> None:
    # 用户已表示已知歧义(加域名后缀或多词品牌)
    assert _is_niche_name("Mem.ai") is False
    assert _is_niche_name("GitHub Copilot") is False
    assert _is_niche_name("Notion AI") is False


def test_is_niche_name_excludes_chinese_or_mixed() -> None:
    assert _is_niche_name("飞书") is False
    assert _is_niche_name("Mem飞书") is False


def test_parse_competitors_with_niche_name_emits_warning(capsys) -> None:
    """niche 名应触发 stderr 警告但不拒绝。"""
    competitors = _parse_competitors("Notion,Evernote,Mem")
    assert [c.name for c in competitors] == ["Notion", "Evernote", "Mem"]
    err = capsys.readouterr().err
    assert "Niche competitor warning" in err
    assert "Mem" in err


def test_parse_competitors_niche_with_exclude_skips_warning(capsys) -> None:
    """带 exclude_keywords 视为用户已知,不警告。"""
    competitors = _parse_competitors("Mem|memory foam;memory card")
    assert competitors[0].name == "Mem"
    err = capsys.readouterr().err
    assert "Niche competitor warning" not in err
