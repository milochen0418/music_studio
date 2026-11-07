"""With the music engine (through an AI Hub that has one): a song sung by the AI from a few words,
the take playing with its lyrics shown, a whole remake of a library song without its singing, and
one that keeps its singing: the AI hears the original's words and the engine sings them again, which
the AI then hears in the new take (Make Video's listening, so it needs the speech model).
Skipped when the hub says there is no engine. Several minutes: the engine loads its models first.
``run_test.py sing``, ``run_test.py remake`` or ``run_test.py keep`` runs one part;
``REMAKE_SOURCE`` (a pattern its row matches, e.g. ``Lydia.*YouTube``) picks the song to remake,
``REMAKE_HOW`` what it should become."""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BASE_URL, finish, launch, log, new_page, shot, wait_for  # noqa: E402

errors: list[str] = []
PARTS = sys.argv[1:] or ["sing", "remake", "keep"]


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

    def remake(vocals: str, how: str) -> tuple[set[str], str]:
        """A whole remake of the chosen library song; what the page said while it worked, and the take."""
        page.click("[data-testid=tab-remake]")
        page.wait_for_selector("[data-testid=source]", timeout=15000)
        rows = page.locator("[data-testid=source]")
        pick = os.environ.get("REMAKE_SOURCE", "")
        (rows.filter(has_text=re.compile(pick)).first if pick else rows.first).click()
        assert page.locator("[data-testid=method-remake]").is_enabled()
        page.click("[data-testid=method-remake]")
        page.click(f"[data-testid=vocals-{vocals}]")
        assert page.locator("[data-testid=length]").count() == 0, "a remake is as long as the song"
        page.fill("[data-testid=how]", how)
        before = page.locator("[data-testid=take]").count()
        page.click("[data-testid=change]")
        wait_for(lambda: page.locator("[data-testid=stage]").count() == 1, "working")
        seen = stages(page)
        log("stages:", sorted(seen))
        assert page.locator("[data-testid=error]").count() == 0, page.locator("[data-testid=error]").inner_text()
        wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the remade take")
        text = page.locator("[data-testid=take]").first.inner_text()
        log("remade:", text.replace("\n", " | ")[:400])
        assert "AI 重做" in text
        return seen, text

    if "remake" in PARTS:
        remake("instrument", "改成輕快的爵士版本")
        shot(page, "02_remade")

    if "keep" in PARTS:
        page.click("[data-testid=tab-remake]")
        page.click("[data-testid=method-remake]")
        page.click("[data-testid=vocals-keep]")
        assert "AI 的聲音" in page.inner_text("[data-testid=vocals-note]"), "says whose voice sings"
        seen, text = remake("keep", os.environ.get("REMAKE_HOW", "改成賽車遊戲"))
        assert any("聽原曲的歌詞" in stage for stage in seen), "the AI listened for the original's words"
        take = page.locator("[data-testid=take]").first
        assert take.locator("details").count() == 1, "sung again: the take has lyrics"
        log("lyrics:", (take.locator("details pre").text_content(timeout=5000) or "")[:300].replace("\n", " / "))
        shot(page, "03_kept_singing")
        # The engine really sang them: the AI listens to the new take and finds the lines in it.
        take.locator("[data-testid=make-video]").click()
        page.wait_for_selector("[data-testid=video-dialog]")
        wait_for(lambda: "AI 聽過了" in page.inner_text("[data-testid=timed]"), "the AI heard the new take", 600)
        timed = page.inner_text("[data-testid=timed]")
        log("heard in the new take:", timed)
        n, of = (int(x) for x in re.search(r"(\d+)／(\d+)", timed).groups())
        assert n >= max(3, 0.3 * of), f"the engine sang the words ({n} of {of} lines heard)"
        shot(page, "04_heard_in_new_take")
        page.click("[data-testid=video-close]")
    browser.close()
finish(errors)
