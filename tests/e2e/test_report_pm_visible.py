from __future__ import annotations


def test_pm_report_link_is_visible(page, server_url: str, e2e_task_id: str) -> None:
    page.goto(f"{server_url}/runs/{e2e_task_id}", wait_until="networkidle")
    page.get_by_role("button", name="Report").click()

    link = page.get_by_role("link", name="open PM report")

    assert link.is_visible()
    assert link.get_attribute("href") == f"/runs/{e2e_task_id}/report_pm.html"


def test_pm_report_page_loads(page, server_url: str, e2e_task_id: str) -> None:
    page.goto(f"{server_url}/runs/{e2e_task_id}/report_pm.html", wait_until="networkidle")

    body = page.locator("body").inner_text()
    assert "PM-readable vector database report" in body


def test_report_quality_summary_is_visible(page, server_url: str, e2e_task_id: str) -> None:
    page.goto(f"{server_url}/runs/{e2e_task_id}", wait_until="networkidle")
    page.get_by_role("button", name="Report").click()

    panel = page.locator("section[aria-label='Report quality summary']")

    assert panel.is_visible()
    assert page.get_by_role("link", name="style audit json").is_visible()
    assert page.get_by_role("link", name="style audit md").is_visible()
