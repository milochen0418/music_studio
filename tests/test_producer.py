import asyncio

import pytest

from music_studio import producer
from music_studio.composer import STYLES


def test_words_alone_choose_a_fitting_style():
    assert producer.guess("夜間霓虹賽道")["style"] == "synthwave"
    assert producer.guess("winner on the podium")["style"] == "victory" or producer.guess("victory")["style"] == "victory"
    assert producer.guess("放鬆的午後")["style"] == "lofi"
    assert producer.guess("沒有任何線索")["style"] in STYLES


def test_a_model_answer_is_read_however_it_is_wrapped():
    text = '<think>{"style": "x"}</think>Sure!\n```json\n{"style": "dnb", "bpm": 500, "key": "Bb", "mode": "minor", "verse": "i VI III VII", "chorus": "nonsense!!", "energy": 3, "lead": "kazoo", "title": "雨"}\n```'
    data = producer.read_json(text)
    brief = producer.brief_from(data, {"style": "synthwave"}, 32)
    assert brief.style == "dnb" and brief.bpm == 176, "held to the style's range"
    assert brief.key == "A#" and brief.energy == 1
    assert brief.verse == "i VI III VII" and brief.chorus == "", "bad chords: the style's own"
    assert brief.lead == "" and brief.title == "雨"


def test_no_json_is_no_decision():
    assert producer.read_json("I think something fast.") == {}
    assert producer.read_json("{broken") == {}


def test_without_a_hub_a_piece_still_gets_a_brief(monkeypatch):
    monkeypatch.delenv("DDNS_AI_HUB_URL", raising=False)
    monkeypatch.delenv("RE_DDNS_API_URL", raising=False)
    brief, model, why = asyncio.run(producer.brief_for("大雨中的競速", "zh", 16))
    assert brief.style == "dnb" and brief.bars == 16 and model == "" and why == ""
    forced, _, _ = asyncio.run(producer.brief_for("大雨中的競速", "zh", 16, "lofi"))
    assert forced.style == "lofi"


def test_a_plan_is_kept_within_what_can_be_done():
    plan = producer.plan_from({"speed": 9, "pitch": -20, "tone": "purple", "beat": "polka", "room": 2}, producer.plan_guess("改成賽車用的，更快"))
    assert plan.speed == 1.3 and plan.pitch == -4 and plan.room == 0.5
    assert plan.tone == "bright" and plan.beat in producer.BEATS
