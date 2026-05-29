from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_interview_story_contains_required_sections() -> None:
    text = (ROOT / "docs" / "INTERVIEW_STORY.md").read_text(encoding="utf-8")

    assert "30-second intro" in text
    assert "3-minute walkthrough" in text
    assert "Demo route" in text
    assert "v1.5 -> v1.6 -> v1.7" in text
    assert "Why not rewrite the dashboard in Next.js?" in text
    assert "Why not implement ToolRegistry now?" in text
    assert text.count("### Q") >= 10


def test_readme_links_report_style_audit_and_interview_story() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "report_style_audit.json" in text
    assert "report_style_audit.md" in text
    assert "docs/INTERVIEW_STORY.md" in text
    assert "PM-readable Report v2" in text
