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
    assert 0.6 <= spec["cover_strength"] <= 1.0 and title == "錦繡夢"
    gone, *_ = asyncio.run(producer.cover_for("", "97 BPM", "x", "remove"))
    assert gone["lyrics"] == "[Instrumental]" and gone["cover_strength"] == 1.0, "nothing asked for: the song's own style, closely"


HEARD = [
    (23.9, 27.8, "为何流浪"),
    (27.8, 31.4, "心碎的海洋"),
    (31.4, 33.3, "受了伤"),
    (33.3, 37.0, "连微笑都彷徨"),
    (97.2, 103.1, "Lydia 幸福不在远方"),
    (103.1, 108.1, "可以选择 许下愿望"),
]


def test_keeping_the_singing_sends_the_words_heard_in_the_recording(monkeypatch):
    """The engine sings only what it is given: "[Instrumental]" for a song whose singing was to be
    kept made it silent (the bug this guards)."""
    _no_hub(monkeypatch)
    spec, title, model, why = asyncio.run(producer.cover_for("改成賽車遊戲", "236 s long, about 81 BPM", "Lydia", "keep", heard=HEARD))
    assert spec["lyrics"] != "[Instrumental]"
    assert spec["lyrics"].startswith("[Verse 1]\n为何流浪") and "[Verse 2]\nLydia 幸福不在远方" in spec["lyrics"]
    assert "instrumental" not in spec["caption"].lower() and "vocal" in spec["caption"], spec["caption"]
    assert spec["cover_strength"] >= 0.7, "the words must still fit the recording's tune"
    nothing, *_ = asyncio.run(producer.cover_for("改成賽車遊戲", "236 s", "Lydia", "keep", heard=[]))
    assert nothing["lyrics"] == "[Instrumental]", "nobody heard singing: there is none to keep"


def test_the_producers_lyrics_are_taken_only_when_they_are_the_lines_heard():
    tidy = "[Verse 1]\n為何流浪\n心碎的海洋\n受了傷\n連微笑都彷徨\n\n[Chorus]\nLydia 幸福不在遠方\n可以選擇 許下願望"
    assert producer._sung_again(tidy, HEARD) == tidy
    assert producer._sung_again("[Instrumental]", HEARD).startswith("[Verse 1]\n为何流浪")
    assert producer._sung_again("", HEARD).startswith("[Verse 1]")
    invented = "\n".join(f"line {k}" for k in range(40))
    assert producer._sung_again(invented, HEARD).startswith("[Verse 1]\n为何流浪"), "a whole new song is not the song"


def test_a_sung_remake_names_a_voice_and_never_says_nobody_sings():
    assert producer._voiced("racing game, instrumental, no vocals, synth bass") == "racing game, synth bass, lead vocal"
    assert producer._voiced("rock, female vocal, guitars") == "rock, female vocal, guitars"


def test_what_the_producer_is_told_about_the_singing():
    keep = producer._cover_asking("", "236 s long", "Lydia", "keep", HEARD, "zh")
    assert '"Lydia"' in keep and "[0:23.9] 为何流浪" in keep and "Traditional characters" in keep
    assert "nothing said" in keep, "an empty wish keeps the song's own style"
    assert "Traditional" not in producer._cover_asking("x", "s", "t", "keep", HEARD, "en")
    assert "[Instrumental]" in producer._cover_asking("x", "s", "t", "remove", HEARD, "zh")
    assert "heard nobody sing" in producer._cover_asking("x", "s", "t", "keep", [], "zh")


def test_the_engine_sings_in_the_language_heard():
    assert producer.engine_language("zh") == "zh" and producer.engine_language("YUE") == "yue"
    assert producer.engine_language("haw") == "" and producer.engine_language("") == ""
