import asyncio
import json
import os
import shutil
import subprocess

import pytest

from music_studio import drafts, listen, lyrics
from music_studio.composer import Brief, compose

SAID_AT = [3.0, 9.0, 15.0]
SONGS = {
    "en": ["The lake lies quiet, white and wide", "No wind tonight, no other side", "Your laugh, the summer, one small boat"],
    "zh": ["午夜的霧爬上了山脊", "引擎在胸口低聲呼吸", "一條路纏著懸崖通往天際"],
}


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSIC_STUDIO_DATA_DIR", str(tmp_path / "data"))


def test_the_language_comes_from_the_engine_or_the_lyrics():
    assert listen.language_of({"language": "en"}, "夜色") == "en"
    assert listen.language_of({}, "夜色降臨") == "zh" and listen.language_of({}, "ハートの") == "ja"
    assert listen.language_of({}, "사랑") == "ko" and listen.language_of({}, "Corazón roto") == ""


def test_what_was_heard_is_kept_and_not_heard_again(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    take = drafts.take_composed(Brief(style="lofi", title="t", bars=8), 1, "", "", "")
    found = {"model": listen.MODEL, "language": "en", "seconds": 30.0, "words": [[3.0, 3.4, "The", 0.9]]}
    drafts.audio_path(take["id"]).with_name(listen.HEARD).write_text(json.dumps(found))
    assert asyncio.run(listen.hear(take["id"], "en")) == found, "no model is loaded for a song heard before"
    assert listen.heard("../nothing") is None
    if not os.path.isdir(listen.MODEL):
        assert not listen.present(), "nothing downloaded in a fresh data folder"


def _voice(language: str) -> str:
    listed = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout.splitlines()
    want, natural = ("en_US", "Samantha") if language == "en" else ("zh_TW", "Meijia")
    found = [row.split(want)[0].strip() for row in listed if f" {want} " in f" {row} "]
    return natural if natural in found else (found[0] if found else "")


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.skipif(not os.path.isdir(os.environ.get("MUSIC_STUDIO_WHISPER", "")) or shutil.which("say") is None, reason="needs MUSIC_STUDIO_WHISPER set to a model folder, and macOS say")
def test_the_ai_finds_each_line_where_it_is_sung(tmp_path, monkeypatch, language):
    """Lines said at known times over music: listening puts each one there, and a line never said
    is marked as not heard."""
    _env(tmp_path, monkeypatch)
    voice = _voice(language)
    if not voice:
        pytest.skip(f"no {language} voice for say")
    lines = SONGS[language]
    music = tmp_path / "music.wav"
    compose(Brief(style="lofi", key="C", bars=8, energy=0.4), 3).save(music)
    inputs, mixes = ["-i", str(music)], []
    for k, line in enumerate(lines):
        subprocess.run(["say", "-v", voice, "-o", str(tmp_path / f"line{k}.aiff"), line], check=True)
        inputs += ["-i", str(tmp_path / f"line{k}.aiff")]
        mixes.append(f"[{k + 1}:a]adelay={int(SAID_AT[k] * 1000)}|{int(SAID_AT[k] * 1000)},volume=2.5[v{k}]")
    voices = "".join(f"[v{k}]" for k in range(len(lines)))
    graph = ";".join(mixes) + f";[0:a]volume=0.35[m];[m]{voices}amix=inputs={len(lines) + 1}:duration=first:normalize=0[out]"
    song = tmp_path / "song.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[out]", "-t", "24", "-ac", "2", str(song)], check=True)
    texts = [*lines, "This line is never said at all" if language == "en" else "這一句從來沒有人唱過"]
    take = drafts.take_engine(song.read_bytes(), {"origin": "sung", "title": "t", "lyrics": "\n".join(texts)})
    found = asyncio.run(listen.hear(take["id"], language))
    timed = lyrics.align(texts, [(w[0], w[1], w[2]) for w in found["words"]], found["seconds"])
    assert [line.heard for line in timed] == [True, True, True, False], found["words"]
    for line, said in zip(timed, SAID_AT):
        assert abs(line.at - said) < 0.7, (line, said, found["words"])
    assert listen.heard(take["id"])["words"] == found["words"], "kept with the take"
