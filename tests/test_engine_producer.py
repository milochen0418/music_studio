import asyncio

from music_studio import producer


def _no_hub(monkeypatch):
    monkeypatch.delenv("DDNS_AI_HUB_URL", raising=False)
    monkeypatch.delenv("RE_DDNS_API_URL", raising=False)


def test_without_a_songwriter_the_engine_still_gets_a_spec_without_singing(monkeypatch):
    _no_hub(monkeypatch)
    spec, title, model, why = asyncio.run(producer.song_for("夜間霓虹賽道", "zh", "zh", False, 90))
    assert spec["lyrics"] == "[Instrumental]" and spec["caption"].startswith("instrumental, synthwave")
    assert spec["language"] == "zh" and spec["duration"] == 90 and model == "" and title == "午夜霓虹"


def test_a_songwriters_answer_is_held_to_what_the_engine_takes():
    data = producer.read_json('{"title": "霓虹", "caption": "synthwave, female vocal", "lyrics": "[Verse 1]\\n夜色\\n[Chorus]\\n衝", "language": "zh", "bpm": 900, "duration": 5000, "why": "合"}')
    assert data["bpm"] == 900
    lyrics = producer._lyrics(data["lyrics"], False)
    assert lyrics.startswith("[Verse 1]")
    assert producer._lyrics(data["lyrics"], True) == "[Instrumental]"
    assert producer._lyrics("  ", False) == "[Instrumental]"


def test_a_remake_without_the_singing_says_so_to_the_engine(monkeypatch):
    _no_hub(monkeypatch)
    spec, title, model, why = asyncio.run(producer.cover_for("改成賽車用的", "97 BPM, G major", "錦繡夢", "instrument"))
    assert spec["task"] == "cover" and spec["lyrics"] == "[Instrumental]" and spec["caption"].startswith("instrumental, no vocals")
    assert 0.2 <= spec["cover_strength"] <= 1.0 and title == "錦繡夢"
    kept, *_ = asyncio.run(producer.cover_for("更快", "97 BPM", "x", "keep"))
    assert kept["lyrics"] == "[Instrumental]" or kept["lyrics"] == "", "no lyrics known: none sent"
