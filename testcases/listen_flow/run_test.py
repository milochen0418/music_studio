"""The AI times the lyrics by listening: a take whose lines are said at known times over music (macOS
`say`), and one line that is never said. Opening Make Video, the AI listens by itself; each line
lands within a second of where it is said, the line never said is marked and left out of the
video, and the video shows each line while it is said.

Needs the speech model: run with MUSIC_STUDIO_WHISPER set to a downloaded model folder (the app's
data folder holds one after its first download, under models/). Skipped without it, or without say."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "testcases"), str(ROOT)]
import numpy as np  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BASE_URL, HEADLESS, OUTPUT_DIR, SLOWMO, finish, log, new_page, shot, wait_for  # noqa: E402
from music_studio import drafts  # noqa: E402
from music_studio.composer import Brief, compose  # noqa: E402

LINES = ["The lake lies quiet, white and wide", "No wind tonight, no other side", "Your laugh, the summer, one small boat"]
NEVER = "This line is never said at all"
SAID_AT = [4.0, 10.0, 16.0]

if not os.path.isdir(os.environ.get("MUSIC_STUDIO_WHISPER", "")) or shutil.which("say") is None:
    log("SKIP: needs MUSIC_STUDIO_WHISPER set to a model folder, and macOS say")
    raise SystemExit(0)

work = OUTPUT_DIR / "song"
work.mkdir(parents=True, exist_ok=True)
compose(Brief(style="lofi", key="C", bars=8, energy=0.4), 3).save(work / "music.wav")
inputs, mixes = ["-i", str(work / "music.wav")], []
for k, line in enumerate(LINES):
    subprocess.run(["say", "-v", "Samantha", "-o", str(work / f"line{k}.aiff"), line], check=True)
    inputs += ["-i", str(work / f"line{k}.aiff")]
    mixes.append(f"[{k + 1}:a]adelay={int(SAID_AT[k] * 1000)}|{int(SAID_AT[k] * 1000)},volume=2.5[v{k}]")
graph = ";".join(mixes) + ";[0:a]volume=0.35[m];[m][v0][v1][v2]amix=inputs=4:duration=first:normalize=0[out]"
subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[out]", "-t", "26", "-ac", "2", str(work / "song.mp3")], check=True)
words = "[Verse 1]\n" + "\n".join([LINES[0], LINES[1], NEVER]) + "\n\n[Chorus]\n" + LINES[2] + "\n"
take = drafts.take_engine((work / "song.mp3").read_bytes(), {"origin": "sung", "rights": "own", "title": "聽歌測試", "lyrics": words, "language": "en"})
log("take:", take["id"], take["seconds"])


def seconds_of(text: str) -> float:
    minutes, _, rest = text.strip().partition(":")
    return int(minutes) * 60 + float(rest)


errors: list[str] = []
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO)
    page = new_page(browser, errors, width=1440, height=1000)
    page.goto(BASE_URL + "/", wait_until="domcontentloaded")
    page.wait_for_selector("[data-testid=take]", timeout=120000)
    page.wait_for_timeout(1500)
    card = page.locator("[data-testid=take]").filter(has_text="聽歌測試").first
    card.locator("[data-testid=make-video]").click()
    page.wait_for_selector("[data-testid=video-dialog]")
    # The model is here, so the AI starts listening by itself.
    wait_for(lambda: page.locator("[data-testid=listen-stage]").count() == 1, "listening", 15)
    assert page.locator("[data-testid=video-make]").is_disabled(), "no video while the lines are being timed"
    shot(page, "01_listening")
    wait_for(lambda: page.locator("[data-testid=listen-stage]").count() == 0, "listened", 300)
    assert page.locator("[data-testid=video-error]").count() == 0, page.locator("[data-testid=video-error]").inner_text()
    timed = page.locator("[data-testid=timed]").inner_text()
    log("timed:", timed)
    assert "3／4" in timed, timed
    rows = page.locator("[data-testid=cue]")
    texts = [rows.nth(k).inner_text() for k in range(rows.count())]
    clocks = [seconds_of(t) for t in page.locator("[data-testid=cue-play]").all_inner_texts()]
    log("lines:", list(zip(clocks, [t.split("\n")[1] if "\n" in t else t for t in texts])))
    order = [LINES[0], LINES[1], NEVER, LINES[2]]
    for k, said in zip((0, 1, 3), SAID_AT):
        assert abs(clocks[k] - said) < 1.0, (order[k], clocks[k], said)
    assert rows.nth(2).locator("[data-testid=cue-unheard]").count() == 1, "the line never said is marked"
    assert sum(rows.nth(k).locator("[data-testid=cue-unheard]").count() for k in range(rows.count())) == 1
    page.locator("[data-testid=cues]").scroll_into_view_if_needed()
    shot(page, "02_heard")

    page.click("[data-testid=video-make]")
    wait_for(lambda: page.locator("[data-testid=video-player]").count() == 1, "the video", 300)
    browser.close()

folder = drafts.audio_path(take["id"]).parent
kept = json.loads((folder / "video.json").read_text())
assert [row[3] for row in kept["lines"]] == [True, True, False, True], kept["lines"]
assert json.loads((folder / "heard.json").read_text())["words"], "what was heard is kept with the take"


def lit(at: float, name: str) -> float:
    png = OUTPUT_DIR / f"{name}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at}", "-i", str(folder / "video.mp4"), "-frames:v", "1", str(png)], check=True)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    frame = np.frombuffer(raw, np.uint8).reshape(1080, 1920)
    return float((frame[860:945, 300:1620] > 200).mean())


# Each line is up while it is said; in the gap where the never-said line was written, nothing is.
during = [lit(at + 1.0, f"03_line{k}") for k, at in enumerate(SAID_AT)]
gap = lit(SAID_AT[1] + 3.6, "04_gap")
log("bright in the lyric strip while said:", during, "in the gap:", gap)
assert min(during) > 0.01 and gap < 0.005
log("output:", OUTPUT_DIR)
finish(errors)
