from __future__ import annotations


def test_revision_tab_shows_controlled_loop(page, server_url: str, e2e_task_id: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{server_url}/runs/{e2e_task_id}", wait_until="networkidle")

    page.get_by_role("button", name="Revision").click()
    page.wait_for_timeout(200)
    body = page.locator("body").inner_text()

    assert "Revision History" in body
    assert "Qdrant is useful for vector workloads." in body
    assert "Qdrant highlights vector search and filtering." in body
    assert "accepted" in body
