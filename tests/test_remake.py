from pathlib import Path

import numpy as np
import pytest

from music_studio import remake
from music_studio.composer import Brief, compose


@pytest.fixture(scope="module")
def song(tmp_path_factory) -> tuple[Path, int]:
    piece = compose(Brief(style="house", key="C", energy=0.8), 21)
    path = tmp_path_factory.mktemp("song") / "song.mp3"
    piece.save(path)
    return path, piece.score.bpm


def test_the_tempo_is_found(song):
    path, bpm = song
    found = remake.analyse(path)
    assert abs(found.bpm - bpm) < 0.5, found
    assert found.sure > 0.3


def test_a_changed_song_keeps_its_length_in_bars_and_its_ends_meet(song):
    path, bpm = song
    plan = remake.Plan(speed=1.1, pitch=2, tone="bright", room=0.15, beat="synthwave", energy=0.7)
    done = remake.remake(path, plan, 16)
    start, end = (int(s * 44100) for s in done.loop)
    assert abs((end - start) / 44100 - 16 * 240 / (bpm * 1.1)) < 0.2
    assert abs(done.bpm - bpm * 1.1) < 1
    assert abs(done.audio).max() <= 1.0
    # The file repeats round the loop: a player that jumps lands where it was.
    a = done.audio[start + 2000 : start + 12000]
    b = done.audio[end + 2000 : end + 12000]
    fade = np.linspace(1, 0, 44100)[2000:12000, None]
    assert np.abs(a * fade - b).max() < 0.02


def test_a_song_with_no_beat_gets_no_drums(tmp_path):
    t = np.arange(44100 * 20) / 44100
    tone = (np.sin(2 * np.pi * 220 * t) * 0.3).astype("<f4")
    path = tmp_path / "tone.wav"
    import subprocess

    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", "44100", "-ac", "1", "-i", "pipe:0", str(path)], input=tone.tobytes(), check=True)
    found = remake.analyse(path)
    done = remake.remake(path, remake.Plan(beat="house"), 8, found)
    assert done.plan.beat == "none" or found.sure >= 0.12
