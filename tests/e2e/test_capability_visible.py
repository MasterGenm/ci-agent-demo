from __future__ import annotations


def test_capability_metadata_visible_in_dag_hover(page, server_url: str, e2e_task_id: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{server_url}/runs/{e2e_task_id}", wait_until="networkidle")

    node = page.locator(".node-line", has_text="Collector").first
    title = node.get_attribute("title") or ""

    assert "3 skills" in page.locator("body").inner_text()
    assert "3 skills:" in title
    assert "seed_url_priority_fetch" in title
