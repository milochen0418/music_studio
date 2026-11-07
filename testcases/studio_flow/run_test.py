"""The studio from a person's side: say what a piece is for, get two takes that really play, keep one,
and find it in the shared library with its loop points and how it was made; read that record (who
decided, what went to the composer) and copy it; make it again with the same settings; then
change that piece into a new take."""

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
    page.locator("[data-testid=words] ~ div button").first.click()
    wait_for(lambda: page.input_value("[data-testid=words]") != "", "a scene fills the box")
    page.fill("[data-testid=words]", "")
    page.click("[data-testid=words]")
    ime = page.context.new_cdp_session(page)
    for typed in ("ㄋ", "ㄋㄧ", "ㄋㄧˇ"):
        ime.send("Input.imeSetComposition", {"text": typed, "selectionStart": len(typed), "selectionEnd": len(typed)})
        page.wait_for_timeout(350)
    assert page.input_value("[data-testid=words]") == "ㄋㄧˇ", page.input_value("[data-testid=words]")
    ime.send("Input.insertText", {"text": "你"})
    wait_for(lambda: page.input_value("[data-testid=words]") == "你", "Chinese typed through the IME")
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
    kept_record = json.loads((manifests[0].parent.parent / "making.json").read_text())
    assert kept_record["to"] == "composer" and kept_record["words"] == "夜間霓虹賽道的最後一圈", "the kept piece carries how it was made"

    # How the kept take was made: who decided, and what the composer was given.
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.locator("[data-testid=take]").first.locator("[data-testid=making]").click()
    page.wait_for_selector("[data-testid=making-dialog]")
    record = page.inner_text("[data-testid=making-dialog]")
    log("record:", record.replace("\n", " | ")[:400])
    assert "誰做的" in record and "交給作曲程式的內容" in record and "seed:" in record and "style:" in record
    assert "AI 製作人收到的訊息" in record or "沒有可用的回答" in record, "the producer's words, or why there are none"
    page.click("[data-testid=making-copy]")
    wait_for(lambda: "## 誰做的" in page.evaluate("navigator.clipboard.readText()"), "the record copied")
    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied.startswith("# ") and "## 交給作曲程式的內容" in copied, copied[:200]
    shot(page, "02_record")
    page.click("[data-testid=making-close]")
    wait_for(lambda: page.locator("[data-testid=making-dialog]").count() == 0, "the record closes")

    # The same piece again: the same brief, a new seed (the composer needs no engine).
    first = page.locator("[data-testid=take]").first
    title = first.locator("div.truncate").first.inner_text()
    before = page.locator("[data-testid=take]").count()
    first.locator("[data-testid=again]").click()
    wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the piece made again", 120)
    again = page.locator("[data-testid=take]").first
    assert again.locator("div.truncate").first.inner_text() == f"{title} #2"
    again.locator("[data-testid=making]").click()
    page.wait_for_selector("[data-testid=making-dialog]")
    record = page.inner_text("[data-testid=making-dialog]")
    assert f"同樣設定再做一次（來自「{title}」）" in record and "seed:" in record, record[:300]
    page.click("[data-testid=making-close]")
    assert again.locator("[data-testid=patch]").count() == 0, "the composer's pieces have no part to remake"

    page.click("[data-testid=tab-remake]")
    page.wait_for_selector("[data-testid=source]", timeout=15000)
    page.locator("[data-testid=source]").first.click()
    if page.locator("[data-testid=method-remake]").is_enabled():
        page.click("[data-testid=method-tweak]")  # a hub with the engine picks the whole remake first
    assert "原唱的聲音會留著" in page.inner_text("[data-testid=method-note]"), "says what adjusting keeps"
    assert page.locator("[data-testid=vocals-keep]").count() == 0 and page.locator("[data-testid=length]").count() == 1
    # Nothing written in the box: the strongest stretch as a loop, as it sounds (no error asks for words).
    before = page.locator("[data-testid=take]").count()
    page.click("[data-testid=change]")
    wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the take as it was", 120)
    assert page.locator("[data-testid=error]").count() == 0
    assert "聲音不變" in page.locator("[data-testid=take]").first.inner_text(), "says nothing was changed"
    page.locator("[data-testid=take]").first.locator("[data-testid=making]").click()
    page.wait_for_selector("[data-testid=making-dialog]")
    record = page.inner_text("[data-testid=making-dialog]")
    assert "沒有問 AI 製作人" in record and "交給改編程式的內容" in record, record[:300]
    page.click("[data-testid=making-close]")
    page.fill("[data-testid=how]", "改成賽車用的，更快更有衝勁")
    before = page.locator("[data-testid=take]").count()
    page.click("[data-testid=change]")
    wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the changed take", 120)
    shot(page, "03_changed")

    # A recording of one's own: somebody else's unless the person says it is theirs.
    page.fill("[data-testid=how]", "")
    page.locator("#song input[type=file]").set_input_files(str(manifests[0].parent.parent / "piece.mp3"))  # the piece kept above
    wait_for(lambda: page.locator("[data-testid=upload-own]").count() == 1, "asked whether it is one's own")
    for own in (False, True):
        if own:
            page.click("[data-testid=upload-own]")
            wait_for(lambda: page.locator("[data-testid=upload-own]").get_attribute("data-state") == "checked", "ticked")
        before = page.locator("[data-testid=take]").count()
        page.click("[data-testid=change]")
        wait_for(lambda: page.locator("[data-testid=take]").count() > before, "the uploaded song changed", 120)
        marked = "僅限自用" in page.locator("[data-testid=take]").first.inner_text()
        assert marked != own, f"own={own}: marked as somebody else's={marked}"
    browser.close()
log("output:", OUTPUT_DIR)
finish(errors)
