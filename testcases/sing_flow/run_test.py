"""With the music engine (through an AI Hub that has one): a song sung by the AI from a few words,
the take playing with its lyrics shown, and a whole remake of a library song without its singing.
Skipped when the hub says there is no engine. Several minutes: the engine loads its models first.
``run_test.py sing`` or ``run_test.py remake`` runs one part."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BASE_URL, finish, launch, log, new_page, shot, wait_for  # noqa: E402

errors: list[str] = []
PARTS = sys.argv[1:] or ["sing", "remake"]


def stages(page) -> set[str]:
    """What the page says while it works, until it stops (the line may vanish between two looks)."""
    seen = set()
    while True:
        texts = page.locator("[data-testid=stage]").all_inner_texts()
        if not texts:
            return seen
        seen.add(texts[0].split("（")[0].split(" (")[0])
        page.wait_for_timeout(2000)


with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, width=1280, height=900)
    page.goto(BASE_URL + "/", wait_until="domcontentloaded")
    page.wait_for_selector("[data-testid=engine]", timeout=120000)
    page.wait_for_timeout(1500)
    if page.locator("[data-testid=voice-sing]").is_disabled():
        log("SKIP: no music engine here:", page.locator("[data-testid=engine]").inner_text())
        raise SystemExit(0)
    if "sing" in PARTS:
        page.fill("[data-testid=words]", "夜間霓虹賽道的最後一圈，緊張但帥氣")
        page.click("[data-testid=voice-sing]")
        page.select_option("[data-testid=lyrics-lang]", "zh")
        page.select_option("[data-testid=length]", "short")
        before = page.locator("[data-testid=take]").count()
        page.click("[data-testid=make]")
        wait_for(lambda: page.locator("[data-testid=stage]").count() == 1, "working")
        log("stages:", sorted(stages(page)))
        assert page.locator("[data-testid=error]").count() == 0, page.locator("[data-testid=error]").inner_text()
        wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the sung take")
        take = page.locator("[data-testid=take]").first
        text = take.inner_text()
        log("take:", text.replace("\n", " | ")[:300])
        assert "AI 演唱" in text, "marked as sung"
        assert take.locator("details").count() == 1, "the lyrics are there"
        assert "可無縫循環" not in text, "the engine's songs don't loop"
        played = page.evaluate(
            """async () => { const a = document.querySelector('[data-testid=take] audio'); a.muted = true; a.preload = 'auto';
            await new Promise((ok, no) => { a.oncanplay = ok; a.onerror = () => no(new Error('no sound')); a.load(); });
            return { seconds: a.duration }; }"""
        )
        log("plays:", played)
        assert played["seconds"] > 20
        shot(page, "01_sung")

    if "remake" not in PARTS:
        browser.close()
        finish(errors)
        raise SystemExit(0)
    page.click("[data-testid=tab-remake]")
    page.wait_for_selector("[data-testid=source]", timeout=15000)
    page.locator("[data-testid=source]").first.click()
    assert page.locator("[data-testid=method-remake]").is_enabled()
    page.click("[data-testid=method-remake]")
    page.click("[data-testid=vocals-instrument]")
    page.fill("[data-testid=how]", "改成輕快的爵士版本")
    before = page.locator("[data-testid=take]").count()
    page.click("[data-testid=change]")
    wait_for(lambda: page.locator("[data-testid=stage]").count() == 1, "working")
    log("stages:", sorted(stages(page)))
    assert page.locator("[data-testid=error]").count() == 0, page.locator("[data-testid=error]").inner_text()
    wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the remade take")
    text = page.locator("[data-testid=take]").first.inner_text()
    log("remade:", text.replace("\n", " | ")[:300])
    assert "AI 重做" in text
    shot(page, "02_remade")
    browser.close()
finish(errors)
