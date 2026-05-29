from __future__ import annotations


def test_home_renders_hero_and_capabilities(page, server_url: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{server_url}/", wait_until="networkidle")

    body = page.locator("body").inner_text()
    assert "AI-powered competitive intelligence agent system" in body
    assert "Multi-Agent DAG" in body
    assert "Evidence-Backed Claims" in body
    assert page.locator(".capability-card").count() >= 4


def test_home_has_runs_section_and_lucide_bootstrap(page, server_url: str) -> None:
    page.goto(f"{server_url}/", wait_until="networkidle")

    assert "Historical Runs" in page.locator("body").inner_text()
    assert page.locator("[data-lucide]").count() >= 4 or page.locator("svg.lucide").count() >= 4
