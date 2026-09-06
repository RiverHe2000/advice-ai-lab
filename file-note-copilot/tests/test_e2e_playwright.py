"""Browser end-to-end tests (Playwright, chromium). The app runs on a random port with the
scripted backend in a background thread. Skipped with a clear message when chromium cannot
launch, unless ``REQUIRE_E2E=1`` (CI sets it after ``playwright install --with-deps chromium``).
Coverage of the Python app does not depend on these: ``tests/test_api.py`` covers the API."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from filenote.config import Settings
from filenote.corpus import Meeting, generate_corpus
from filenote.fake import GoldFakeChatModel
from filenote.web import create_app

pytestmark = pytest.mark.e2e

if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and Path("D:/ms-playwright").exists():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "D:/ms-playwright"

REQUIRE = os.environ.get("REQUIRE_E2E") == "1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    import uvicorn

    from filenote.fake import Corruption

    corpus = generate_corpus(12, 11)
    model = GoldFakeChatModel(
        {m.id: m for m in corpus},
        corruption=Corruption(p=1.0, seed=0, kinds=frozenset({"invented_decision", "repair_keep"})),
    )
    app = create_app(Settings(), model=model)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=1.0).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        pytest.fail("app did not start")
    yield url
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def page(base_url: str) -> Iterator[Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on the environment
        if REQUIRE:
            raise
        pytest.skip(f"playwright not installed: {exc}")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except PlaywrightError as exc:  # pragma: no cover - depends on the environment
            if REQUIRE:
                raise
            pytest.skip(
                f"chromium cannot launch ({str(exc).splitlines()[0]}); run `playwright install chromium`"
            )
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        pg = context.new_page()
        pg.set_default_timeout(20_000)
        yield pg
        browser.close()


def test_draft_streams_highlights_blocks_and_approves(
    page: Any, base_url: str, meeting: Meeting
) -> None:
    page.goto(base_url + "/")
    page.fill("#transcript", meeting.transcript.to_text())
    page.select_option("#strategy", "verified")
    page.click("#draft-button")
    page.wait_for_selector("#workspace:not([hidden])")
    page.wait_for_function("() => document.querySelectorAll('#progress li').length > 2")
    page.wait_for_function(
        "() => /Draft ready/.test(document.getElementById('status').textContent)"
    )
    progress = page.locator("#progress li").all_inner_texts()
    assert any(p.startswith("extracting") for p in progress)
    assert "done" in progress

    # evidence chip → the right segment is highlighted
    chip = page.locator(".claim:not(.unsupported) .chip").first
    sid = chip.get_attribute("data-target")
    chip.click()
    page.wait_for_selector(f"#seg-{sid}.highlight")
    assert page.locator(".segment.highlight").count() == 1
    assert page.locator(f"#seg-{sid}").inner_text().startswith(sid)

    # the unsupported claim is flagged with icon + text, and approval is blocked
    flagged = page.locator(".claim.unsupported")
    assert flagged.count() == 1
    assert "Unsupported" in flagged.first.inner_text()
    assert page.locator(".claim.unsupported .flag-icon").count() == 1
    assert page.locator(".claim.unsupported .reasons li").count() >= 1
    assert page.locator("#approve-button").is_disabled()
    assert "1 unsupported claim" in page.locator("#verdict").inner_text()

    # edit it → saved as a new version → approval enabled
    flagged.first.locator(".edit-button").click()
    page.fill(
        ".claim.unsupported .editor",
        "Client agreed to nothing further (adviser corrected this line).",
    )
    page.click(".save-edit")
    page.wait_for_function("() => document.querySelectorAll('.claim.unsupported').length === 0")
    page.wait_for_function("() => !document.getElementById('approve-button').disabled")
    assert page.locator(".claim.edited").count() == 1

    # approve → diff stored and shown
    page.fill("#approver", "alice@northshore")
    page.click("#approve-button")
    page.wait_for_selector("#approval:not([hidden])")
    meta = page.locator("#approval-meta").inner_text()
    assert "Approved by alice@northshore" in meta
    diff = page.locator("#approval-diff").inner_text()
    assert "- " in diff and "+ " in diff
    assert page.locator("#approve-button").is_disabled()

    # feedback
    page.click("#thumbs-down")
    page.locator(".claim .wrong-box").first.check()
    page.fill("#feedback-comment", "one decision was invented")
    page.click("#feedback-button")
    page.wait_for_function(
        "() => /Feedback recorded/.test(document.getElementById('status').textContent)"
    )

    draft_id = page.evaluate("() => window.filenote.state.draftId")
    stored = httpx.get(f"{base_url}/api/drafts/{draft_id}", timeout=5.0).json()
    assert stored["status"] == "approved"
    assert stored["approval"]["approver"] == "alice@northshore"
    assert stored["approval"]["changed_lines"] >= 1
    assert stored["feedback"][0]["thumbs"] == "down"
    assert stored["feedback"][0]["wrong_claims"]
    assert stored["version"] == 2


def test_pure_functions_in_browser(page: Any, base_url: str) -> None:
    page.goto(base_url + "/")
    diff = page.evaluate("() => window.filenote.diffLines(['a', 'b', 'c'], ['a', 'x', 'c'])")
    assert [d["type"] for d in diff] == ["same", "del", "add", "same"]
    count = page.evaluate(
        "() => window.filenote.unsupportedCount({decisions: [{text: 't', evidence: ['s001'], unsupported: true}, "
        "{text: 'u', evidence: ['s001'], unsupported: true, edited: true}], compliance: {vulnerability_indicators: []}, follow_up: null})"
    )
    assert count == 1
    deleted = page.evaluate(
        "() => { const n = {goals: [{text: 'a', evidence: ['s1']}], compliance: {vulnerability_indicators: []}, follow_up: {text: 'f', evidence: ['s2']}};"
        " window.filenote.deleteClaim(n, 'goals', 0); window.filenote.deleteClaim(n, 'follow_up', 0); return n; }"
    )
    assert deleted["goals"] == [] and deleted["follow_up"] is None
    edited = page.evaluate(
        "() => { const n = {action_items: [{description: 'd', owner: 'client', evidence: ['s1']}], compliance: {vulnerability_indicators: []}};"
        " window.filenote.setClaimText(n, 'action_items', 0, 'new'); return n.action_items[0]; }"
    )
    assert edited["description"] == "new" and edited["edited"] is True
    assert (
        page.evaluate("() => document.querySelectorAll('[onclick],[onsubmit],[onload]').length")
        == 0
    )
    page.click("#sample-button")
    assert page.input_value("#transcript").startswith("# meeting: sample")


def test_reload_by_draft_id_and_reconnect_handling(
    page: Any, base_url: str, meeting: Meeting
) -> None:
    created = httpx.post(
        f"{base_url}/api/drafts", json={"transcript": meeting.transcript.to_text()}, timeout=5.0
    ).json()
    draft_id = created["draft_id"]
    deadline = time.time() + 15
    while (
        time.time() < deadline
        and httpx.get(f"{base_url}/api/drafts/{draft_id}", timeout=5.0).json()["status"] != "done"
    ):
        time.sleep(0.05)
    page.goto(f"{base_url}/?draft={draft_id}")
    page.wait_for_selector("#workspace:not([hidden])")
    assert page.locator(".segment").count() == len(meeting.transcript.segments)
    assert page.locator(".claim").count() > 5
    # the SSE client resumes after an error on the source: simulate by subscribing late
    events = page.evaluate(
        "(id) => new Promise((resolve) => { const seen = []; window.filenote.subscribe(id, {"
        " stage: (d) => seen.push('stage'), partial: (d) => seen.push('partial'),"
        " done: (d) => resolve(seen.concat(['done'])), error: (d) => resolve(seen.concat(['error'])) }); })",
        draft_id,
    )
    assert events[-1] == "done" and "partial" in events
