from __future__ import annotations


def test_run_detail_loads_progress_bar(page, server_url: str, e2e_task_id: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{server_url}/runs/{e2e_task_id}", wait_until="networkidle")

    body = page.locator("body").inner_text()
    assert e2e_task_id.lower() in body.lower()
    assert "Run Status" in body
    assert "9 / 9 nodes" in body
    assert page.locator("#run-progress").get_attribute("data-status") == "completed"


def test_run_detail_switches_core_tabs(page, server_url: str, e2e_task_id: str) -> None:
    page.goto(f"{server_url}/runs/{e2e_task_id}", wait_until="networkidle")

    for tab_name in ["DAG", "QA Critic", "Report", "Schema", "Evidence", "Trace"]:
        page.get_by_role("button", name=tab_name).click()
        page.wait_for_timeout(150)
        assert tab_name.split()[0] in page.locator("body").inner_text()
