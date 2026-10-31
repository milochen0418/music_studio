"""The studio from a person's side: say what a piece is for, get two takes that really play, keep one,
and find it in the shared library with its loop points; then change that piece into a new take."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BASE_URL, OUTPUT_DIR, finish, launch, log, new_page, shot, wait_for  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, width=1280, height=900)
    page.goto(BASE_URL + "/", wait_until="domcontentloaded")
    page.wait_for_selector("[data-testid=studio]", timeout=120000)
    page.wait_for_timeout(1500)
    assert page.locator("h2").first.inner_text() == "作好的版本"
    page.click("[data-testid=make]")
    wait_for(lambda: page.locator("[data-testid=error]").count() == 1, "asks what it is for")
    page.fill("[data-testid=words]", "夜間霓虹賽道的最後一圈")
    page.select_option("[data-testid=length]", "short")
    page.click("[data-testid=make]")
    wait_for(lambda: page.locator("[data-testid=take]").count() >= 2, "two takes", 120)
    wait_for(lambda: page.locator("[data-testid=stage]").count() == 0, "work finished", 30)
    shot(page, "01_takes")
    played = page.evaluate(
        """async () => { const a = document.querySelector('[data-testid=take] audio'); a.muted = true; a.preload = 'auto';
        await new Promise((ok, no) => { a.oncanplay = ok; a.onerror = () => no(new Error('no sound')); a.load(); });
        return { seconds: a.duration }; }"""
    )
    log("first take:", played)
    assert played["seconds"] > 40
    page.locator("[data-testid=keep]").first.click()
    wait_for(lambda: page.locator("[data-testid=keep]").count() == 1, "kept")

    root = Path(os.environ["DDNS_COLLECTIONS_ROOT"]) / "audio" / "by-app" / "music-studio"
    manifests = list(root.glob("*/.item/manifest.json"))
    assert len(manifests) == 1, manifests
    meta = json.loads(manifests[0].read_text())["meta"]
    log("kept:", {k: meta[k] for k in ("origin", "rights", "style", "bpm", "loop_start", "loop_end", "duration")})
    assert meta["rights"] == "own" and 0 < meta["loop_start"] < meta["loop_end"] < meta["duration"]

    page.click("[data-testid=tab-remake]")
    page.wait_for_selector("[data-testid=source]", timeout=15000)
    page.locator("[data-testid=source]").first.click()
    page.fill("[data-testid=how]", "改成賽車用的，更快更有衝勁")
    before = page.locator("[data-testid=take]").count()
    page.click("[data-testid=change]")
    wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the changed take", 120)
    shot(page, "02_changed")
    browser.close()
log("output:", OUTPUT_DIR)
finish(errors)
