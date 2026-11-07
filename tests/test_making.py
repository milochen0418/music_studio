import asyncio
import json

from reflex_ddns_auth.collections import Collection

from music_studio import drafts, library, making, producer
from music_studio.composer import Brief
from music_studio.i18n import TEXT

LABEL = "Claude Code (your computer, claude-opus-5-5)"
ANSWER = '```json\n{"title": "霓虹", "caption": "synthwave, female vocal", "lyrics": "[Verse 1]\\n夜色\\n[Chorus]\\n衝", "language": "zh", "bpm": 120, "duration": 60, "why": "合"}\n```'


class _Reply:
    def __init__(self, text: str, model: str = LABEL):
        self._text, self.model, self.stop = text, "", ""
        self._label = model

    def __aiter__(self):
        return self._run()

    async def _run(self):
        self.model = self._label
        yield self._text
        self.stop = "end_turn"


def _answers(monkeypatch, text: str) -> list[dict]:
    asked: list[dict] = []

    def stream(role, system, messages, max_tokens=0, user=""):
        asked.append({"role": role, "system": system, "messages": messages})
        return _Reply(text)

    monkeypatch.setattr(producer.ai, "stream", stream)
    return asked


def test_the_producers_talk_is_kept_word_for_word(monkeypatch):
    asked = _answers(monkeypatch, ANSWER)
    talk = producer.Talk()
    spec, title, model, why = asyncio.run(producer.song_for("夜間霓虹賽道", "zh", "zh", False, 60, talk=talk))
    assert model == LABEL and title == "霓虹" and spec["caption"] == "synthwave, female vocal"
    assert talk.role == "smart" and talk.model == LABEL and talk.stop == "end_turn" and talk.problem == ""
    assert talk.system == producer.SONG_SYSTEM == asked[0]["system"]
    assert talk.asked == asked[0]["messages"][0]["content"] and talk.asked.startswith("夜間霓虹賽道")
    assert talk.answer == ANSWER, "the whole answer, wrapping and all"


def test_an_answer_without_a_decision_says_so(monkeypatch):
    _answers(monkeypatch, "I'd go for synthwave.")
    talk = producer.Talk()
    brief, model, why = asyncio.run(producer.brief_for("夜間賽車", "zh", 16, talk=talk))
    assert model == "" and talk.model == LABEL and talk.problem == "no decision in the answer"
    assert talk.system == producer.COMPOSE_SYSTEM and talk.answer == "I'd go for synthwave."


def test_without_a_hub_the_record_says_why(monkeypatch):
    monkeypatch.delenv("DDNS_AI_HUB_URL", raising=False)
    monkeypatch.delenv("RE_DDNS_API_URL", raising=False)
    talk = producer.Talk()
    asyncio.run(producer.cover_for("改成賽車用的", "97 BPM", "錦繡夢", "remove", talk=talk))
    assert talk.model == "" and talk.answer == "" and talk.problem
    assert talk.system == producer.COVER_SYSTEM and "改成賽車用的" in talk.asked


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("DDNS_COLLECTIONS_ROOT", str(tmp_path / "collections"))
    monkeypatch.setenv("MUSIC_STUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DDNS_COLLECTIONS_NODE_URL", raising=False)


def test_a_take_keeps_its_record_and_the_library_item_carries_it(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    brief = Brief(style="house", title="夜行", key="C", bars=8, energy=0.7)
    talk = producer.Talk(model=LABEL, system="rules", asked="夜間賽車", answer='{"style": "house"}', stop="end_turn", seconds=12.3)
    record = making.record("composed", "夜間賽車", talk, "composer", {"style": "house", "seed": 3})
    made = drafts.take_composed(brief, 3, "夜間賽車", LABEL, "fits", record)
    kept = drafts.making(made["id"])
    assert kept["producer"]["asked"] == "夜間賽車" and kept["request"] == {"style": "house", "seed": 3}
    assert kept["id"] == made["id"] and kept["made_at"] > 0 and kept["version"] == making.VERSION
    ref = library.keep(made)
    item = Collection("audio", app_id="music-box").get(ref, remote=False)
    assert json.loads(item.file(drafts.MAKING).read_text(encoding="utf-8")) == kept
    assert item.primary.name == "piece.mp3", "the song stays the item's file"


def test_a_take_from_before_records_shows_what_it_still_has(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    made = drafts.take_composed(Brief(style="lofi", title="午後", bars=8), 5, "放鬆", "Claude Code (your computer)", "fits")
    assert drafts.making(made["id"]) is None
    found = making.of_take(made, None)
    assert found["old"] and found["producer"] == {"role": "smart", "model": "Claude Code (your computer)"} and found["to"] == "composer"
    assert found["request"]["style"] == "lofi" and found["request"]["seed"] == 5
    cover = making.of_take(
        {"origin": "cover", "model": "", "words": "賽車", "caption": "rock", "lyrics": "[Instrumental]", "plan": {"cover_strength": 0.85, "vocals": "remove"}, "engine": {"dit": "acestep-v15-turbo"}},
        None,
    )
    assert cover["producer"] is None and cover["to"] == "engine" and cover["request"]["cover_strength"] == 0.85
    assert cover["engine"]["models"]["dit"] == "acestep-v15-turbo"


def test_a_record_reads_from_who_made_it_to_what_the_engine_said():
    t = TEXT["zh"]
    talk = producer.Talk(model=LABEL, system=producer.COVER_SYSTEM, asked="The recording: ...", answer=ANSWER, stop="end_turn", seconds=41.6)
    request = {"task": "cover", "caption": "racing, female vocal", "lyrics": "[Verse 1]\n為何流浪\n心碎的海洋", "cover_strength": 0.85, "audio_format": "mp3", "language": "zh", "source": {"title": "Lydia", "bytes": 3900000}}
    engine = {"models": {"dit": "acestep-v15-turbo", "lm": "acestep-5Hz-lm-1.7B"}, "metas": {"bpm": 81, "keyscale": "A major", "genres": None}, "seconds": 182.4, "id": "j1"}
    found = making.record("cover", "改成賽車遊戲", talk, "engine", request, engine=engine, listening={"model": "large-v3-turbo", "language": "zh", "lines": 25})
    shown = making.parts(found, t)
    heads = [part.head for part in shown]
    assert heads == [t["mk_who"], t["mk_words"], t["mk_rules"], t["mk_asked"], t["mk_answer"], t["mk_to_engine"], t["mk_engine_said"]]
    who = shown[0].body
    assert f"（smart）：{LABEL}" in who and "花了 42 秒" in who and "Whisper large-v3-turbo" in who and "聽出 25 句" in who
    assert "ACE-Step (acestep-v15-turbo, acestep-5Hz-lm-1.7B)" in who and "花了 182 秒" in who
    rules = shown[2]
    assert rules.fold and rules.body == producer.COVER_SYSTEM
    handed = shown[5].body
    assert "cover_strength: 0.85" in handed and handed.endswith("lyrics:\n[Verse 1]\n為何流浪\n心碎的海洋"), "the lyrics last, as written"
    assert "audio_b64" not in handed and shown[6].body == "bpm: 81\nkeyscale: A major"
    text = making.as_text("Lydia 極速賽道版", shown)
    assert text.startswith("# Lydia 極速賽道版") and "````\n```json" in text, "a fence the answer's own can't close"


def test_a_loop_cut_as_it_sounds_says_nobody_was_asked():
    t = TEXT["en"]
    found = making.record("remake", "", None, "remaker", {"title": "Lydia", "speed": 1.0, "bars": 32})
    shown = making.parts(found, t)
    assert shown[0].body.splitlines() == [t["mk_not_asked"], t["mk_remaker"]]
    assert shown[1].body == t["mk_nothing"] and shown[-1].head == t["mk_to_remaker"]


def test_a_remake_record_says_where_its_words_came_from_how_close_it_stayed_and_how_it_came_out():
    t = TEXT["zh"]
    found = making.record(
        "cover",
        "改成賽車遊戲",
        producer.Talk(model=LABEL, system="rules", asked="msg", answer="{}", stop="end_turn", seconds=9.0),
        "engine",
        {"task": "cover", "caption": "racing", "lyrics": "[Verse 1]\nLydia", "cover_strength": 0.75},
        engine={"models": {"dit": "acestep-v15-turbo"}, "metas": {"bpm": 81, "seed": 4242}, "seconds": 200.0, "id": "j"},
        lyrics_from={"from": "lrclib", "artist": "F.I.R.", "track": "Lydia", "edited": True},
        compare={"bpm": [81, 82], "key": ["A major", "A major"], "seconds": [236.0, 236.4], "lines": [20, 25]},
    )
    shown = making.parts(found, t)
    who = shown[0].body
    assert "歌詞：LRCLIB 的 F.I.R.《Lydia》，你改過" in who
    assert "跟原曲多像：標準（8 步裡照著原曲 6 步）" in who and "seed 4242" in who
    compare = shown[-1]
    assert compare.head == t["mk_compare"] and compare.body.splitlines() == [
        "速度：81 BPM → 82 BPM",
        "調性：A major → A major",
        "長度：3:56 → 3:56",
        "AI 聽這一首：25 句歌詞裡聽到 20 句有唱",
        t["mk_cmp_rough"],
    ]


def test_a_take_made_again_or_in_part_says_so():
    t = TEXT["en"]
    again = making.record("sung", "night race", {"role": "smart", "model": LABEL, "seconds": 8}, "engine", {"caption": "x"}, again_of={"id": "d1", "title": "Last Lap"})
    assert making.parts(again, t)[0].body.splitlines()[0] == "Made again with the settings of “Last Lap”"
    part = making.record("repaint", "Remade 1:05–1:30 only", None, "engine", {"task": "repaint", "repaint_start": 65.0, "repaint_end": 90.0})
    assert making.parts(part, t)[0].body.splitlines()[0] == t["mk_by_you"]
