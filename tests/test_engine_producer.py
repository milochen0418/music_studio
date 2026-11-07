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
    assert spec["cover_strength"] in (0.75, 1.0), "the words must still fit the recording's tune: standard or close"
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
    assert "no words to sing" in producer._cover_asking("x", "s", "t", "keep", [], "zh")
    checked = producer._cover_asking("x", "s", "t", "keep", [], "zh", "[Verse 1]\n為何流浪", "free")
    assert "the person has checked" in checked and checked.endswith("[Verse 1]\n為何流浪") and "chose the closeness: free" in checked


def test_the_engine_sings_in_the_language_heard():
    assert producer.engine_language("zh") == "zh" and producer.engine_language("YUE") == "yue"
    assert producer.engine_language("haw") == "" and producer.engine_language("") == ""


class _Reply:
    def __init__(self, text):
        self.text, self.model, self.stop = text, "", ""

    def __aiter__(self):
        return self._run()

    async def _run(self):
        self.model = "Fake producer"
        yield self.text
        self.stop = "end_turn"


def _answer(monkeypatch, text):
    monkeypatch.setattr(producer.ai, "stream", lambda *a, **k: _Reply(text))


def test_closeness_is_one_of_three_levels_that_really_differ(monkeypatch):
    assert [producer.steps_of(v) for v in producer.LEVELS.values()] == [4, 6, 8], "free, standard, close: 4, 6 and 8 of 8 steps"
    assert producer.level_of(0.9) == "close" and producer.level_of(0.8) == "standard" and producer.level_of(0.55) == "free"
    assert producer.level_of("n/a") == ""
    _answer(monkeypatch, '{"title": "t", "caption": "jazz", "closeness": "free", "why": "w"}')
    free, *_ = asyncio.run(producer.cover_for("改成爵士", "s", "t", "instrument"))
    assert free["cover_strength"] == 0.5
    sung, *_ = asyncio.run(producer.cover_for("改成爵士", "s", "t", "keep", lyrics="為何流浪\n心碎的海洋"))
    assert sung["cover_strength"] == 0.75, "sung again: at least standard, whatever the producer says"
    chosen, *_ = asyncio.run(producer.cover_for("改成爵士", "s", "t", "keep", lyrics="為何流浪", closeness="free"))
    assert chosen["cover_strength"] == 0.5, "the person's own choice wins"
    _answer(monkeypatch, '{"title": "t", "caption": "jazz", "cover_strength": 0.93}')
    old, *_ = asyncio.run(producer.cover_for("x", "s", "t", "remove"))
    assert old["cover_strength"] == 1.0, "a number is read as the nearest level"


def test_lyrics_the_person_checked_are_sung_as_they_are(monkeypatch):
    _answer(monkeypatch, '{"title": "極速", "caption": "racing, synth rock", "lyrics": "[Verse 1]\\ncompletely different", "closeness": "close"}')
    spec, title, model, why = asyncio.run(producer.cover_for("改成賽車", "s", "Lydia", "keep", lyrics="Lydia 迷離的眼眶\n為何流浪\n\n他走了帶不走你的天堂"))
    assert spec["lyrics"] == "[Verse 1]\nLydia 迷離的眼眶\n為何流浪\n\n[Verse 2]\n他走了帶不走你的天堂", "tagged, otherwise untouched"
    assert "vocal" in spec["caption"] and spec["cover_strength"] == 1.0 and model == "Fake producer"
    cleared, *_ = asyncio.run(producer.cover_for("改成賽車", "s", "Lydia", "keep", lyrics="  "))
    assert cleared["lyrics"] == "[Instrumental]" and cleared["caption"].startswith("instrumental")
