"""With the music engine (through an AI Hub that has one): a song sung by the AI from a few words,
the take playing with its lyrics shown, a whole remake of a library song without its singing, and
one that keeps its singing: the AI hears the original's words and the engine sings them again, which
the AI then hears in the new take (Make Video's listening, so it needs the speech model). Each take's
record says who decided with which model, what the producer was told and answered, and what went
to the engine. Keeping the singing shows the words first (LRCLIB's, or what the AI heard) for the
person to check; then a take is made again with the same settings, and one part of it remade.
Skipped when the hub says there is no engine. Several minutes: the engine loads its models first.
``run_test.py sing``, ``remake``, ``keep`` or ``edit`` (after keep) runs one part;
``REMAKE_SOURCE`` (a pattern its row matches, e.g. ``Lydia.*YouTube``) picks the song to remake,
``REMAKE_HOW`` what it should become, ``REMAKE_CLOSENESS`` (close, standard, free) how close."""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BASE_URL, finish, launch, log, new_page, shot, wait_for  # noqa: E402

errors: list[str] = []
PARTS = sys.argv[1:] or ["sing", "remake", "keep", "edit"]


def stages(page) -> set[str]:
    """What the page says while it works, until it stops (the line may vanish between two looks)."""
    seen = set()
    while True:
        texts = page.locator("[data-testid=stage]").all_inner_texts()
        if not texts:
            return seen
        seen.add(texts[0].split("（")[0].split(" (")[0])
        page.wait_for_timeout(2000)


def read_record(take, name: str, asked: bool = True) -> str:
    """A take's making record, as the page shows it (the producer's rules stay folded); ``asked``:
    the AI producer was asked for it."""
    take.locator("[data-testid=making]").click()
    page.wait_for_selector("[data-testid=making-dialog]")
    record = page.inner_text("[data-testid=making-dialog]")
    log("record:", record.replace("\n", " | ")[:600])
    for part in ("誰做的", "音樂模型做完後回報", *(("AI 製作人收到的訊息", "AI 製作人的回答（原文）") if asked else ())):
        assert part in record, part
    shot(page, name)
    page.click("[data-testid=making-close]")
    return record


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
        record = read_record(take, "01_sung_record")
        assert "AI 製作人（smart）" in record and "交給音樂模型的內容" in record and "caption:" in record, "who wrote it, and what the engine got"

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
        closeness = os.environ.get("REMAKE_CLOSENESS", "")
        if closeness:
            page.click(f"[data-testid=closeness-{closeness}]")
            wait_for(lambda: "bg-slate-100" in (page.locator(f"[data-testid=closeness-{closeness}]").get_attribute("class") or ""), "the closeness chosen")
        page.fill("[data-testid=how]", how)
        before = page.locator("[data-testid=take]").count()
        page.click("[data-testid=change]")
        wait_for(lambda: page.locator("[data-testid=stage]").count() == 1, "working")
        seen = stages(page)
        if vocals == "keep":
            # The words come first, for the person to check (and here, to add a line to).
            wait_for(lambda: page.locator("[data-testid=confirm-words]").count() == 1, "the words to check", 600)
            note = page.inner_text("[data-testid=confirm-note]")
            words = page.input_value("[data-testid=confirm-lyrics]")
            log("words found:", note, "|", words[:200].replace("\n", " / "))
            assert words.startswith("["), "in parts, with section tags"
            shot(page, "03a_words_to_check")
            page.fill("[data-testid=confirm-lyrics]", words + "\n最後一句是我加的")
            wait_for(lambda: page.input_value("[data-testid=confirm-lyrics]").endswith("最後一句是我加的"), "a line added")
            page.wait_for_timeout(800)  # the change reaches the page's state
            page.click("[data-testid=confirm-go]")
            wait_for(lambda: page.locator("[data-testid=stage]").count() == 1, "working on it")
            seen |= stages(page)
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
        wait_for(lambda: "AI 的聲音" in page.inner_text("[data-testid=vocals-note]"), "says whose voice sings")
        seen, text = remake("keep", os.environ.get("REMAKE_HOW", "改成賽車遊戲"))
        assert any("歌詞" in stage for stage in seen), "the original's words were looked for"
        take = page.locator("[data-testid=take]").first
        assert take.locator("details").count() == 1, "sung again: the take has lyrics"
        sung = take.locator("details pre").text_content(timeout=5000) or ""
        log("lyrics:", sung[:300].replace("\n", " / "))
        assert "最後一句是我加的" in sung, "the words as the person left them"
        assert re.search(r"AI 重做 · (貼近原曲|標準|自由改編)", take.inner_text()), "the closeness on the card"
        shot(page, "03_kept_singing")
        record = read_record(take, "03_kept_singing_record")
        assert "the person has checked" in record and "你改過" in record, "the checked words went to the producer, changed"
        assert "跟原曲多像：" in record and "cover_strength:" in record and "audio_b64" not in record
        assert "和原曲比" in record and "速度：" in record, "measured against the recording"
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

    if "edit" in PARTS:
        takes = page.locator("[data-testid=take]")
        first = takes.first
        title = first.locator("div.truncate").first.inner_text()
        # The same settings again, with a new seed: the engine gets the recording anew.
        before = takes.count()
        first.locator("[data-testid=again]").click()
        wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the take made again", 900)
        again = page.locator("[data-testid=take]").first
        assert again.locator("div.truncate").first.inner_text() == f"{title} #2", again.inner_text()
        record = read_record(again, "05_again_record")
        assert f"同樣設定再做一次（來自「{title}」）" in record and "seed" in record
        # One part of it remade: a range too short is refused, then 0:05 to 0:15 is made anew.
        again.locator("[data-testid=patch]").click()
        page.wait_for_selector("[data-testid=patch-dialog]")
        page.fill("[data-testid=patch-start]", "0:05")
        page.fill("[data-testid=patch-end]", "0:06")
        page.wait_for_timeout(400)
        page.click("[data-testid=patch-make]")
        wait_for(lambda: page.locator("[data-testid=patch-error]").count() == 1, "a part too short is refused")
        page.fill("[data-testid=patch-end]", "0:15")
        page.click("[data-testid=patch-mode-aggressive]")
        page.wait_for_timeout(600)
        shot(page, "05a_part_dialog")
        before = page.locator("[data-testid=take]").count()
        page.click("[data-testid=patch-make]")
        wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the part remade", 900)
        part = page.locator("[data-testid=take]").first
        assert "重做 0:05–0:15" in part.inner_text(), part.inner_text()
        record = read_record(part, "06_part_record", asked=False)
        assert "沒有問 AI 製作人" in record and "repaint_start: 5" in record and "repaint_mode: aggressive" in record
    browser.close()
finish(errors)
