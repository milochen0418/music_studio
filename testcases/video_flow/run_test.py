"""Make Video from a person's side: a take with lyrics but no times gets its lines guessed, tapped
along to, nudged and finally given by LRC; then a 1080p MP4 (H.264 High + AAC, as long as the
song) is made, plays in the page, downloads under its title and shows each line at its time.
Another take is started and stopped."""

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "testcases"), str(ROOT)]
import numpy as np  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BASE_URL, HEADLESS, OUTPUT_DIR, SLOWMO, finish, log, new_page, shot, wait_for  # noqa: E402
from music_studio import drafts  # noqa: E402
from music_studio.composer import Brief  # noqa: E402

WORDS = "[Verse 1]\n夜色降臨賽道亮起\n引擎聲劃破雨幕\n\n[Chorus]\nRacing through the night\nNever look behind\n"
LRC = "[00:02.00]夜色降臨賽道亮起\n[00:06.50]引擎聲劃破雨幕\n[00:11.00]Racing through the night\n[00:15.20]Never look behind"


def seconds_of(text: str) -> float:
    minutes, _, rest = text.strip().partition(":")
    return int(minutes) * 60 + float(rest)


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def frame(path: Path, at: float, name: str) -> np.ndarray:
    png = OUTPUT_DIR / f"{name}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at}", "-i", str(path), "-frames:v", "1", str(png)], check=True)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(1080, 1920)


# Takes of our own, as the music engine's songs come: lyrics with section tags and no times.
sung = drafts.take_composed(Brief(style="synthwave", title="夜行測試", bars=16, energy=0.8), 5, "test", "", "")
drafts.update(sung["id"], lyrics=WORDS, origin="sung")
plain = drafts.take_composed(Brief(style="lofi", title="午後測試", bars=8, energy=0.4), 6, "test", "", "")
log("takes:", sung["id"], sung["seconds"], plain["id"])

errors: list[str] = []
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO, args=["--autoplay-policy=no-user-gesture-required"])
    page = new_page(browser, errors, width=1440, height=1000)
    page.goto(BASE_URL + "/", wait_until="domcontentloaded")
    page.wait_for_selector("[data-testid=take]", timeout=120000)
    page.wait_for_timeout(1500)
    card = page.locator("[data-testid=take]").filter(has_text="夜行測試").first
    card.locator("[data-testid=make-video]").click()
    page.wait_for_selector("[data-testid=video-dialog]")
    wait_for(lambda: page.locator("[data-testid=cue]").count() == 4, "four sung lines, the tags left out")
    assert page.input_value("[data-testid=video-title]") == "夜行測試"
    assert "估計" in page.locator("[data-testid=timed]").inner_text()

    def clocks() -> list[float]:
        return [seconds_of(t) for t in page.locator("[data-testid=cue-play]").all_inner_texts()]

    guessed = clocks()
    log("guessed:", guessed)
    assert guessed == sorted(guessed) and 0 < guessed[0] < guessed[-1] < sung["seconds"]
    first = page.locator("[data-testid=cue]").first
    first.locator("[data-testid=cue-later]").click()
    first.locator("[data-testid=cue-later]").click()
    wait_for(lambda: abs(clocks()[0] - (guessed[0] + 0.5)) < 0.06, "the first line half a second later")
    page.click("[data-testid=shift-earlier]")
    wait_for(lambda: abs(clocks()[0] - guessed[0]) < 0.06 and abs(clocks()[1] - (guessed[1] - 0.5)) < 0.06, "all half a second earlier")
    shot(page, "01_guessed")

    # Tap along: the song plays from the start, the space bar times each line where the player is.
    page.click("[data-testid=tap-start]")
    page.wait_for_selector("[data-testid=tap]")
    wait_for(lambda: page.evaluate("document.getElementById('mv-audio').currentTime") > 1.2, "the song plays", 15)
    page.keyboard.press("Space")
    wait_for(lambda: "2" in page.locator("[data-testid=tap-line]").inner_text().split("：")[0], "on to the second line")
    wait_for(lambda: page.evaluate("document.getElementById('mv-audio').currentTime") > 2.6, "the song plays on", 15)
    page.locator("[data-testid=tap]").click()
    wait_for(lambda: clocks()[1] < 4.5, "the second line tapped")
    tapped = clocks()
    log("tapped:", tapped)
    assert 1.1 < tapped[0] < 2.6 and tapped[0] < tapped[1] < 4.5, tapped
    assert "點出來" in page.locator("[data-testid=timed]").inner_text()
    wait_for(lambda: page.locator("[data-testid=now]").inner_text() != "", "the line being sung shows while it plays")
    shot(page, "02_tapping")
    page.click("[data-testid=tap-stop]")
    wait_for(lambda: page.locator("[data-testid=tap]").count() == 0, "tapping stopped")

    # One line set to where the player is.
    page.evaluate("(() => { const a = document.getElementById('mv-audio'); a.pause(); a.currentTime = 9.0; })()")
    page.locator("[data-testid=cue]").nth(3).locator("[data-testid=cue-stamp]").click()
    wait_for(lambda: abs(clocks()[3] - 9.0) < 0.06, "the last line at the player's time")

    # Times given as LRC are kept as they are.
    page.click("[data-testid=edit-lrc]")
    page.wait_for_selector("[data-testid=lrc]")
    assert page.input_value("[data-testid=lrc]").startswith("[00:0"), page.input_value("[data-testid=lrc]")
    page.fill("[data-testid=lrc]", LRC)
    page.click("[data-testid=lrc-apply]")
    wait_for(lambda: clocks() == [2.0, 6.5, 11.0, 15.2], "the LRC's times")
    assert "LRC" in page.locator("[data-testid=timed]").inner_text()

    page.fill("[data-testid=video-title]", "夜行 MV")
    page.click("[data-testid=look-wave]")
    page.wait_for_timeout(500)
    page.click("[data-testid=video-make]")
    wait_for(lambda: page.locator("[data-testid=video-stage]").count() == 1, "making", 15)
    shot(page, "03_making")
    wait_for(lambda: page.locator("[data-testid=video-player]").count() == 1, "the video", 300)
    assert page.locator("[data-testid=video-error]").count() == 0
    played = page.evaluate(
        """async () => { const v = document.querySelector('[data-testid=video-player]'); v.muted = true;
        if (v.readyState < 1) await new Promise((ok, no) => { v.onloadedmetadata = ok; v.onerror = () => no(new Error('no video')); });
        return { seconds: v.duration, width: v.videoWidth, height: v.videoHeight }; }"""
    )
    log("plays:", played)
    assert played["width"] == 1920 and played["height"] == 1080
    assert abs(played["seconds"] - sung["seconds"]) < 0.1, (played, sung["seconds"])
    shot(page, "04_made")

    source = page.get_attribute("[data-testid=video-player]", "src")
    part = page.request.get(source, headers={"Range": "bytes=0-99"})
    assert part.status == 206 and len(part.body()) == 100, part.status
    link = page.get_attribute("[data-testid=video-download]", "href")
    got = page.request.get(link)
    disposition = got.headers.get("content-disposition", "")
    log("download:", got.status, got.headers.get("content-type"), disposition, len(got.body()))
    assert got.status == 200 and got.headers.get("content-type") == "video/mp4"
    assert disposition.startswith("attachment") and quote("夜行 MV.mp4") in disposition

    page.click("[data-testid=video-close]")
    wait_for(lambda: page.locator("[data-testid=video-dialog]").count() == 0, "closed")
    assert "有影片" in card.inner_text()

    # Somebody else opening it later finds the video and what it was made with.
    later = new_page(browser, errors, width=1440, height=1000)
    later.goto(BASE_URL + "/", wait_until="domcontentloaded")
    later.wait_for_selector("[data-testid=take]", timeout=60000)
    later.locator("[data-testid=take]").filter(has_text="夜行測試").first.locator("[data-testid=make-video]").click()
    later.wait_for_selector("[data-testid=video-player]")
    wait_for(lambda: [seconds_of(t) for t in later.locator("[data-testid=cue-play]").all_inner_texts()] == [2.0, 6.5, 11.0, 15.2], "the times it was made with")
    assert later.input_value("[data-testid=video-title]") == "夜行 MV" and "上次" in later.locator("[data-testid=timed]").inner_text()
    later.close()

    # Started and stopped: nothing is left, nothing is wrong.
    other = page.locator("[data-testid=take]").filter(has_text="午後測試").first
    other.locator("[data-testid=make-video]").click()
    page.wait_for_selector("[data-testid=video-dialog]")
    assert page.locator("[data-testid=cue]").count() == 0 and "沒有歌詞" in page.locator("[data-testid=timed]").inner_text()
    assert page.locator("[data-testid=lyrics-on]").is_disabled()
    page.click("[data-testid=video-make]")
    wait_for(lambda: page.locator("[data-testid=video-stage]").count() == 1, "making the other", 15)
    page.click("[data-testid=video-stop]")
    wait_for(lambda: page.locator("[data-testid=video-stage]").count() == 0, "stopped", 30)
    assert page.locator("[data-testid=video-player]").count() == 0 and page.locator("[data-testid=video-error]").count() == 0
    browser.close()

folder = drafts.audio_path(sung["id"]).parent
made = folder / "video.mp4"
info = probe(made)
streams = {s["codec_type"]: s for s in info["streams"]}
v, a = streams["video"], streams["audio"]
log("video:", v["codec_name"], v["profile"], v["width"], v["height"], v["pix_fmt"], v["r_frame_rate"], "audio:", a["codec_name"], a["sample_rate"], "seconds:", info["format"]["duration"])
assert (v["codec_name"], v["profile"], v["width"], v["height"], v["pix_fmt"], v["r_frame_rate"]) == ("h264", "High", 1920, 1080, "yuv420p", "30/1")
assert a["codec_name"] == "aac" and a["channels"] == 2
song = float(probe(folder / "take.mp3")["format"]["duration"])
assert abs(float(info["format"]["duration"]) - song) < 0.1, (info["format"]["duration"], song)
head = made.read_bytes()[:4 << 20]
assert 0 <= head.find(b"moov") < head.find(b"mdat"), "the index comes first (fast start)"
kept = json.loads((folder / "video.json").read_text())
assert kept["title"] == "夜行 MV" and kept["look"] == "wave" and [row[0] for row in kept["lines"]] == [2.0, 6.5, 11.0, 15.2]
# The first line is sung from 2.0 s: its words are in the strip at 3 s and not at 1 s.
strip = slice(860, 945)
before, during = frame(made, 1.0, "05_frame_1s"), frame(made, 3.0, "06_frame_3s")
lit = lambda f: float((f[strip, 300:1620] > 200).mean())  # noqa: E731
log("bright in the lyric strip:", lit(before), lit(during))
assert lit(during) > lit(before) + 0.01
assert not (drafts.audio_path(plain["id"]).parent / "video.mp4").exists()
log("output:", OUTPUT_DIR)
finish(errors)
