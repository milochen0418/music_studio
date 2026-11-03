import asyncio
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from starlette.testclient import TestClient

from music_studio import drafts, video
from music_studio.api import api
from music_studio.lyrics import Line

RATE = video.RATE


def _probe(path: Path) -> dict:
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout)


def _frame(path: Path, at: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(video.H, video.W)


def _song(seconds: float) -> bytes:
    """A sung take stands in: a chord that swells, as MP3."""
    t = np.arange(int(44100 * seconds)) / 44100
    wave = sum(np.sin(2 * np.pi * f * t) for f in (220, 277.2, 329.6)) * 0.2 * np.minimum(1, t / 2)
    return subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", "44100", "-ac", "1", "-i", "pipe:0", "-f", "mp3", "-"], input=wave.astype("<f4").tobytes(), capture_output=True, check=True).stdout


@pytest.fixture()
def take(tmp_path, monkeypatch) -> dict:
    monkeypatch.setenv("MUSIC_STUDIO_DATA_DIR", str(tmp_path / "data"))
    return drafts.take_engine(_song(6.0), {"origin": "sung", "rights": "own", "title": "影片測試", "lyrics": "[Verse]\n第一句\nsecond line"})


def test_the_bars_follow_the_music():
    tone = np.sin(2 * np.pi * 440 * np.arange(RATE * 4) / RATE) * 0.5
    mono = np.r_[np.zeros(RATE * 2), tone]  # two seconds of nothing, then an A
    rows = video.bars(mono, video.frames_for(mono.size / RATE))
    assert rows.shape == (180, video.BARS) and rows.dtype == np.uint8 and rows.max() <= 250
    assert rows[:50].max() == 0, "nothing stands while it is silent"
    playing = rows[80:170]
    loudest = int(np.argmax(playing.mean(axis=0)))
    edges = np.geomspace(40, RATE / 2, video.BARS + 1)
    assert edges[loudest - 1] < 440 < edges[loudest + 2], "the bar of the A stands highest"
    assert playing[:, loudest].min() > 150 and playing[:, :5].max() < 30 and playing[:, -5:].max() < 30


def test_a_bar_falls_back_slowly():
    mono = np.r_[np.sin(2 * np.pi * 440 * np.arange(RATE) / RATE) * 0.5, np.zeros(RATE)]
    rows = video.bars(mono, 60).max(axis=1).astype(int)
    after = rows[31:45]
    assert (np.diff(after) <= 0).all() and after[0] > after[-1] > 0, "down a step a frame, not at once"


def test_the_wave_moves_left_as_the_song_goes_on():
    mono = np.zeros(RATE * 5)
    mono[RATE * 2 : RATE * 2 + RATE // 20] = 0.8  # a click at 2 s
    rows = video.wave(mono, video.frames_for(5))
    assert rows.shape == (150, video.BOX[0])
    assert rows[int(1.5 * video.FPS)].max() == 0, "not heard yet"
    one, two = int(np.argmax(rows[int(2.5 * video.FPS)])), int(np.argmax(rows[int(3.5 * video.FPS)]))
    assert abs((one - two) - video.BOX[0] / video.WAVE_SECONDS) < 12, "a second later, a second's width further left"


def test_the_ramp_leaves_gaps_between_bars():
    ramp = np.asarray(video.ramp("bars"))
    column = video.BOX[0] // video.BARS
    assert ramp.shape == (video.BOX[1], video.BOX[0])
    assert (ramp[:, column - 1] == 255).all(), "no level reaches a gap"
    assert ramp[-1, 0] == 0 and ramp[0, 0] == 250
    middle = np.asarray(video.ramp("wave"))[:, 0]
    assert middle[video.BOX[1] // 2] < 5 and middle[0] == 250


def test_long_words_are_wrapped_and_cut():
    face = video.font(40)
    lines = video.wrap("這是一句很長很長的歌詞 " * 10, face, 600, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert all(face.getlength(line) <= 600 for line in lines)
    assert video.wrap("Racing through the night", face, 10_000, 1) == ["Racing through the night"]
    words = "Racing through the night again and again"
    assert " ".join(video.wrap(words, face, 300, 9)) == words, "words in letters stay whole"


def test_every_input_ends_with_the_song(tmp_path):
    """Debian's FFmpeg 5.1 never stops when an input never ends, whatever the output's -t says."""
    for spec in (video.Spec(title="t", artist="a", look="wave"), video.Spec(title="t", artist="a", lines=[Line(1, "x")])):
        args = video.command(tmp_path, tmp_path / "take.mp3", spec, 12.5, "#ff8fcf", tmp_path / "out.mp4")
        inputs = args[: args.index("-filter_complex")]
        looped = sources = 0
        options: list[str] = []
        k = 0
        while k < len(inputs):
            if inputs[k] != "-i":
                options.append(inputs[k])
                k += 1
                continue
            source = inputs[k + 1]
            if "-loop" in options:
                looped += 1
                assert options[options.index("-t") + 1] == "12.500", source
            if "lavfi" in options:
                assert source.endswith(":d=12.500"), source
            sources += 1
            options, k = [], k + 2
        assert looped == 5 and sources == (9 if spec.lines else 8)


def test_a_video_as_long_as_the_song_with_each_line_at_its_time(take):
    heard: list[float] = []

    async def progress(fraction: float) -> None:
        heard.append(fraction)

    spec = video.Spec(title="影片測試", artist="Music Studio 音樂工坊", about="AI 演唱", lines=[Line(1.5, "第一句"), Line(3.5, "second line")])
    made = asyncio.run(video.render(take["id"], spec, progress))
    path = video.path(take["id"])
    assert path is not None and made["bytes"] == path.stat().st_size and not path.with_name("video.part.mp4").exists()
    assert all(0 <= f <= 1 for f in heard)
    info = _probe(path)
    streams = {s["codec_type"]: s for s in info["streams"]}
    v, a = streams["video"], streams["audio"]
    assert (v["codec_name"], v["profile"], v["width"], v["height"], v["pix_fmt"], v["r_frame_rate"]) == ("h264", "High", 1920, 1080, "yuv420p", "30/1")
    assert v.get("color_space") == "bt709" and a["codec_name"] == "aac" and a["channels"] == 2
    song = float(_probe(drafts.audio_path(take["id"]))["format"]["duration"])
    assert abs(float(info["format"]["duration"]) - song) < 0.1
    head = path.read_bytes()[: 1 << 20]
    assert 0 <= head.find(b"moov") < head.find(b"mdat"), "the index first, so it plays while it downloads"
    strip = (slice(860, 945), slice(300, 1620))
    lit = lambda at: float((_frame(path, at)[strip] > 200).mean())  # noqa: E731
    assert lit(2.5) > lit(0.7) + 0.01, "the first line is up while it is sung"
    kept = video.settings(take["id"])
    assert kept["title"] == "影片測試" and kept["lines"] == [[1.5, "第一句"], [3.5, "second line"]]


def test_stopped_leaves_nothing(take):
    async def go():
        job = asyncio.create_task(video.render(take["id"], video.Spec(title="x", artist="y")))
        await asyncio.sleep(0.05)
        assert video.busy(take["id"])
        video.stop(take["id"])
        with pytest.raises(video.Stopped):
            await job

    asyncio.run(go())
    assert video.path(take["id"]) is None and not video.busy(take["id"])
    assert not drafts.audio_path(take["id"]).with_name("video.part.mp4").exists()


def test_without_lyrics_the_cover_sits_in_the_middle():
    picture = video.layer(video.Image.new("RGB", (256, 256), (200, 50, 50)), video.Spec(title="t", artist="a"))
    alpha = np.asarray(picture)[:, :, 3]
    middle = (video.H - video.COVER) // 2
    assert alpha[middle + 10, 300] == 255 and alpha[140 + 5, 300] < 255
    assert alpha[video.H - 100, 1200] == 0, "no dark strip where no lyrics go"


def test_the_video_is_served_a_range_at_a_time_and_downloads_under_its_title(take):
    asyncio.run(video.render(take["id"], video.Spec(title="夜/行 MV", artist="a")))
    with TestClient(api) as client:
        part = client.get(f"/_studio/video/{take['id']}.mp4", headers={"Range": "bytes=0-99"})
        assert part.status_code == 206 and len(part.content) == 100 and part.headers["content-type"] == "video/mp4"
        whole = client.get(f"/_studio/video/{take['id']}.mp4?download=1")
        assert whole.status_code == 200 and whole.headers["content-disposition"] == "attachment; filename*=utf-8''%E5%A4%9C%20%E8%A1%8C%20MV.mp4"
        assert client.get("/_studio/video/nothing-here.mp4").status_code == 404
        assert client.get("/_studio/video/..%2F..%2Fetc.mp4").status_code == 404
