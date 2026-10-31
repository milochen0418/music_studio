"""The producer: reads what a piece is for and decides what it should be. The AI Hub's model (role
``smart``) answers with a small JSON brief; the composer writes the notes. Without a hub, or with
an answer that doesn't read, keywords choose instead, so a piece always comes.

The same for changing a song: the model is told what was measured in it (tempo, key) and what the
person asked for, and answers with how to change it (``remake.Plan``).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from reflex_ddns_auth import ai

from music_studio.composer import STYLES, Brief
from music_studio.composer.synth import PATCHES
from music_studio.composer.theory import NAMES, SCALES, key_root, parse_progression
from music_studio.remake import BEATS, TONES, Plan

logger = logging.getLogger(__name__)
ROLE = "smart"
USES = {ROLE: "The producer: reads what a piece is for and decides its style, tempo, key and chords, or how to change a song"}
MAX_TOKENS = 12000  # thinking models spend most of these before they answer
LEADS = [p for p in PATCHES if p.startswith("lead_")]

COMPOSE_SYSTEM = f"""You are a music producer. A person says what a piece of music is for; you decide what it should be.
A composer program plays your decision, so answer with one JSON object and nothing else:
{{"title": "a short title in the person's language",
  "style": one of {sorted(STYLES)},
  "bpm": whole number,
  "key": one of {list(NAMES)},
  "mode": one of {sorted(SCALES)},
  "verse": "4 chords as roman numerals of the scale, e.g. i VI III VII",
  "chorus": "4 chords the same way",
  "energy": 0.0 (calm) to 1.0 (flat out),
  "lead": one of {LEADS} or "none",
  "mood": "a few words",
  "why": "one sentence in the person's language on why this fits"}}
Use the style's natural tempo: synthwave 100-126, dnb 168-176, chiptune 132-168, rock 136-168, house 122-128,
techno 128-136, orchestral 92-132, lofi 72-88, ambient 62-78, tropical 102-116, desert 108-128, victory 120-144."""

REMAKE_SYSTEM = f"""You are a remix producer. A person wants an existing recording changed. You don't touch its notes: you decide
how a program changes it, so answer with one JSON object and nothing else:
{{"title": "a short title in the person's language",
  "speed": 0.8 to 1.3 (1 keeps the tempo),
  "pitch": whole semitones, -4 to 4,
  "tone": one of {list(TONES)},
  "room": 0.0 (dry) to 0.5 (a big hall),
  "beat": one of {list(BEATS)} ("none" keeps the song's own drums alone),
  "energy": 0.0 to 1.0, how busy the new drums are,
  "why": "one sentence in the person's language on why this fits"}}"""

# When there is no model to ask: words to a style. The first that matches wins.
KEYWORDS: tuple[tuple[tuple[str, ...], dict[str, Any]], ...] = (
    (("勝", "贏", "冠軍", "victory", "win", "champion", "fanfare"), {"style": "victory", "energy": 0.75, "title": ("凱旋", "Victory Lap")}),
    (("夜", "霓虹", "night", "neon"), {"style": "synthwave", "energy": 0.75, "title": ("午夜霓虹", "Midnight Neon")}),
    (("雨", "rain", "storm"), {"style": "dnb", "energy": 0.7, "key": "D", "title": ("雨中疾行", "Running Through Rain")}),
    (("沙漠", "沙丘", "desert", "dune"), {"style": "desert", "energy": 0.7, "key": "E", "title": ("沙丘風", "Dune Wind")}),
    (("冰", "雪", "ice", "snow", "frozen"), {"style": "ambient", "energy": 0.4, "key": "F", "title": ("冰湖", "Frozen Lake")}),
    (("海", "夕陽", "coast", "sunset", "beach", "tropical"), {"style": "tropical", "energy": 0.65, "key": "G", "title": ("夕陽海岸", "Sunset Coast")}),
    (("山", "史詩", "mountain", "epic", "boss", "battle", "戰"), {"style": "orchestral", "energy": 0.8, "key": "D", "title": ("山巔", "The Summit")}),
    (("城市", "街", "city", "street", "club"), {"style": "house", "energy": 0.75, "key": "C", "title": ("城市脈動", "City Pulse")}),
    (("復古", "電玩", "8-bit", "retro", "chiptune", "arcade"), {"style": "chiptune", "energy": 0.8, "key": "C", "title": ("街機時光", "Arcade Days")}),
    (("搖滾", "rock", "guitar"), {"style": "rock", "energy": 0.85, "key": "E", "title": ("全油門", "Full Throttle")}),
    (("放鬆", "讀書", "專注", "咖啡", "relax", "study", "focus", "cafe", "chill", "lofi"), {"style": "lofi", "energy": 0.3, "key": "F", "title": ("午後", "Slow Afternoon")}),
    (("冥想", "安靜", "calm", "ambient", "sleep"), {"style": "ambient", "energy": 0.2, "key": "C", "title": ("靜", "Still")}),
    (("賽車", "比賽", "速度", "race", "racing", "speed", "fast"), {"style": "synthwave", "energy": 0.85, "key": "A", "title": ("極速", "Top Speed")}),
)


def guess(words: str, lang: str = "zh") -> dict[str, Any]:
    """What the words suggest, with no model: a dict of Brief's fields."""
    low = words.lower()
    for keys, choice in KEYWORDS:
        if any(k in low for k in keys):
            title = choice["title"][0 if lang == "zh" else 1]
            return {**{k: v for k, v in choice.items() if k != "title"}, "title": title}
    return {"style": "synthwave", "energy": 0.7, "title": "新曲" if lang == "zh" else "New Piece"}


def read_json(text: str) -> dict[str, Any]:
    """The JSON object in a model's answer, however it is wrapped ({} when there is none)."""
    clean = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(clean[start : end + 1])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _number(value: Any, low: float, high: float, fallback: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return fallback


def _chords(value: Any) -> str:
    try:
        return str(value) if value and parse_progression(str(value)) else ""
    except ValueError:
        return ""


def brief_from(data: dict[str, Any], fallback: dict[str, Any], bars: int) -> Brief:
    """A brief from a model's answer: anything it got wrong takes the fallback's or the style's."""
    style = data.get("style") if data.get("style") in STYLES else fallback.get("style", "synthwave")
    low, high = STYLES[style].bpm
    energy = _number(data.get("energy"), 0, 1, fallback.get("energy", 0.7))
    bpm = int(_number(data.get("bpm"), low, high, round(low + (high - low) * energy)))
    key = str(data.get("key") or fallback.get("key") or "A")
    key = NAMES[key_root(key)]
    lead = str(data.get("lead") or "")
    return Brief(
        style=style,
        title=str(data.get("title") or fallback.get("title") or "")[:60],
        bpm=bpm,
        key=key,
        mode=data.get("mode") if data.get("mode") in SCALES else "",
        verse=_chords(data.get("verse")),
        chorus=_chords(data.get("chorus")),
        energy=energy,
        lead=lead if lead in PATCHES or lead == "none" else "",
        bars=bars,
        mood=str(data.get("mood") or "")[:80],
    )


async def brief_for(words: str, lang: str, bars: int, style: str = "", user: str = "") -> tuple[Brief, str, str]:
    """What to compose: (brief, who decided, why). ``style`` forces a style when the person chose."""
    fallback = guess(words, lang)
    if style in STYLES:
        fallback = {**fallback, "style": style}
    data: dict[str, Any] = {}
    model = ""
    try:
        reply = ai.stream(ROLE, COMPOSE_SYSTEM, [{"role": "user", "content": _asking(words, style)}], max_tokens=MAX_TOKENS, user=user)
        text = "".join([piece async for piece in reply])
        model = reply.model
        data = read_json(text)
        if not data:
            logger.warning("The producer gave no decision (stop: %s): %r", reply.stop, text[:200])
    except ai.HubUnavailable as e:
        logger.info("No producer: %s", e)
    if style in STYLES:
        data["style"] = style
    return brief_from(data, fallback, bars), model if data else "", str(data.get("why") or "")[:200]


def _asking(words: str, style: str) -> str:
    return f"{words}\n(The person chose the style {style}.)" if style in STYLES else words


def plan_guess(words: str) -> Plan:
    low = words.lower()
    fast = any(k in low for k in ("快", "緊張", "賽車", "race", "fast", "tense", "speed"))
    slow = any(k in low for k in ("慢", "放鬆", "slow", "relax", "calm"))
    dark = any(k in low for k in ("暗", "夜", "dark", "night"))
    return Plan(
        speed=1.12 if fast else 0.9 if slow else 1.0,
        tone="dark" if dark else "bright" if fast else "warm" if slow else "none",
        room=0.25 if slow else 0.12,
        beat="dnb" if fast and "快" in low else "synthwave" if fast else "none" if slow else "house",
        energy=0.8 if fast else 0.4 if slow else 0.6,
    )


def plan_from(data: dict[str, Any], fallback: Plan, title: str = "") -> Plan:
    return Plan(
        title=str(data.get("title") or title or fallback.title)[:60],
        speed=_number(data.get("speed"), 0.8, 1.3, fallback.speed),
        pitch=int(_number(data.get("pitch"), -4, 4, fallback.pitch)),
        tone=data.get("tone") if data.get("tone") in TONES else fallback.tone,
        room=_number(data.get("room"), 0, 0.5, fallback.room),
        beat=data.get("beat") if data.get("beat") in BEATS else fallback.beat,
        energy=_number(data.get("energy"), 0, 1, fallback.energy),
    )


async def plan_for(words: str, facts: str, title: str, user: str = "") -> tuple[Plan, str, str]:
    """How to change a song: (plan, who decided, why)."""
    fallback = plan_guess(words)
    data: dict[str, Any] = {}
    model = ""
    try:
        reply = ai.stream(ROLE, REMAKE_SYSTEM, [{"role": "user", "content": f"The recording: {facts}\nWhat the person wants: {words}"}], max_tokens=MAX_TOKENS, user=user)
        text = "".join([piece async for piece in reply])
        model = reply.model
        data = read_json(text)
        if not data:
            logger.warning("The producer gave no plan (stop: %s): %r", reply.stop, text[:200])
    except ai.HubUnavailable as e:
        logger.info("No producer: %s", e)
    return plan_from(data, fallback, title), model if data else "", str(data.get("why") or "")[:200]
