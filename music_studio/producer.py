"""The producer: reads what a piece is for and decides what it should be. The AI Hub's model (role
``smart``) answers with a small JSON brief; the composer writes the notes. Without a hub, or with
an answer that doesn't read, keywords choose instead, so a piece always comes.

The same for changing a song: the model is told what was measured in it (tempo, key) and what the
person asked for, and answers with how to change it (``remake.Plan``).

With the music engine (ACE-Step through the hub, ``reflex_ddns_auth.ai.music``) the model writes
the song instead: a caption in the engine's words, the lyrics in the language asked for, and for
a remake the new version's caption and how far from the recording to go (``song_for``,
``cover_for``); the engine sings and plays it.
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
USES = {
    ROLE: "The producer: reads what a piece is for and decides its style, tempo, key and chords, or how to change a song; with the music engine, it writes the lyrics and the song's description",
    "music": "Songs with singing, and remaking a recording (new style, without the singing or with an instrument in its place)",
}
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

SONG_SYSTEM = """You are a songwriter and producer. A person says what a song is for; a music model (ACE-Step) will sing and play it from your words, so write for it.
Answer with one JSON object and nothing else:
{"title": "a short title in the person's language",
  "caption": "the music in English as comma-separated tags: genre, mood, tempo feel, main instruments, the singer's voice (e.g. 'female vocal', 'male vocal', 'duet') and production style; under 60 words",
  "lyrics": "the whole lyrics in the language asked for, with section tags on their own lines ([Verse 1], [Chorus], [Verse 2], [Bridge], [Outro]); about 8 lines per 30 seconds; no chords, no notes to the reader",
  "language": "the lyrics' language as a code: zh, en, ja, ko, es, fr, de, it, pt, ru",
  "bpm": whole number,
  "duration": whole seconds, 30 to 240,
  "why": "one sentence in the person's language on your choices"}
For a piece without singing, lyrics is exactly "[Instrumental]" and the caption says instrumental."""

COVER_SYSTEM = """You are a remix producer. A music model (ACE-Step) will remake an existing recording from your words: it keeps the recording's structure and melody as far as the cover strength allows, and plays and sings the new version.
Answer with one JSON object and nothing else:
{"title": "a short title in the person's language",
  "caption": "the new version's music in English as comma-separated tags: genre, mood, tempo feel, instruments, the voice (or 'instrumental, no vocals' when the singing must go; name the instrument that takes the melody when it is to be played instead of sung)",
  "lyrics": "exactly [Instrumental] when the singing must go or be played by an instrument; else the lyrics the person gave, or an empty string",
  "cover_strength": a number from 0.2 to 1.0 (0.2 to 0.4 keeps the recording and changes its sound, 0.5 to 0.7 changes the arrangement too, 0.8 to 1.0 keeps only the song's bones),
  "why": "one sentence in the person's language on your choices"}"""

# Each style's caption for the engine, when there is no model to write one.
CAPTIONS = {
    "synthwave": "synthwave, retro 80s, driving, pulsing synth bass, gated drums, neon night",
    "dnb": "drum and bass, fast breakbeats, deep sub bass, tense, energetic",
    "chiptune": "chiptune, 8-bit, bright, playful, arcade, fast",
    "rock": "rock, electric guitars, driving drums, energetic",
    "house": "house, four on the floor, warm chords, groovy, club",
    "techno": "techno, dark, hypnotic, hard kick, minimal",
    "orchestral": "epic orchestral, strings, brass, taiko drums, cinematic",
    "lofi": "lo-fi hip hop, warm, dusty drums, mellow electric piano, relaxed",
    "ambient": "ambient, calm, soft pads, slow, spacious",
    "tropical": "tropical house, bright, marimba, warm, beach sunset",
    "desert": "middle eastern, oud, driving percussion, cinematic, desert",
    "victory": "triumphant, fanfare, orchestral brass, uplifting, celebration",
}
LANGUAGES = ("zh", "en", "ja", "ko", "es", "fr", "de", "it", "pt", "ru")

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


# ------------------------------------------------------------ with the music engine


def _lyrics(text: Any, instrumental: bool) -> str:
    words = str(text or "").strip()
    if instrumental or not words or words.lower() in ("[instrumental]", "[inst]", "instrumental"):
        return "[Instrumental]"
    return words[:4000]


async def song_for(words: str, lang: str, lyrics_lang: str, instrumental: bool, seconds: int, user: str = "") -> tuple[dict[str, Any], str, str, str]:
    """What to ask the engine for: (spec, title, who decided, why). Without a model the words
    become the caption as they are, and the piece has no singing (nobody wrote lyrics)."""
    fallback = guess(words, lang)
    want = lyrics_lang if lyrics_lang in LANGUAGES else ("zh" if lang == "zh" else "en")
    data: dict[str, Any] = {}
    model = ""
    asking = f"{words}\n(Lyrics in: {want}. Length: about {seconds} seconds.{' No singing: an instrumental piece.' if instrumental else ''})"
    try:
        reply = ai.stream(ROLE, SONG_SYSTEM, [{"role": "user", "content": asking}], max_tokens=MAX_TOKENS, user=user)
        text = "".join([piece async for piece in reply])
        model = reply.model
        data = read_json(text)
        if not data:
            logger.warning("The songwriter gave no song (stop: %s): %r", reply.stop, text[:200])
    except ai.HubUnavailable as e:
        logger.info("No songwriter: %s", e)
    caption = str(data.get("caption") or f"{CAPTIONS.get(fallback['style'], '')}, {words}")[:600]
    lyrics = _lyrics(data.get("lyrics"), instrumental or not data)
    if lyrics == "[Instrumental]" and "instrumental" not in caption.lower():
        caption = "instrumental, " + caption
    spec = {
        "caption": caption,
        "lyrics": lyrics,
        "language": data.get("language") if data.get("language") in LANGUAGES else want,
        "duration": int(_number(data.get("duration"), 30, 240, seconds)),
    }
    bpm = _number(data.get("bpm"), 40, 220, 0)
    if bpm:
        spec["bpm"] = int(bpm)
    title = str(data.get("title") or fallback.get("title") or "")[:60]
    return spec, title, model if data else "", str(data.get("why") or "")[:200]


async def cover_for(words: str, facts: str, title: str, vocals: str, user: str = "") -> tuple[dict[str, Any], str, str, str]:
    """How the engine remakes a recording: (spec without the audio, title, who decided, why).
    ``vocals``: keep, remove or instrument (the melody played instead of sung)."""
    data: dict[str, Any] = {}
    model = ""
    wish = {"remove": " Take the singing out: an instrumental version.", "instrument": " Take the singing out and let an instrument play its melody."}.get(vocals, "")
    try:
        reply = ai.stream(ROLE, COVER_SYSTEM, [{"role": "user", "content": f"The recording: {facts}\nWhat the person wants: {words}{wish}"}], max_tokens=MAX_TOKENS, user=user)
        text = "".join([piece async for piece in reply])
        model = reply.model
        data = read_json(text)
        if not data:
            logger.warning("The remix producer gave no plan (stop: %s): %r", reply.stop, text[:200])
    except ai.HubUnavailable as e:
        logger.info("No remix producer: %s", e)
    caption = str(data.get("caption") or words)[:600]
    if vocals != "keep" and "instrumental" not in caption.lower():
        caption = "instrumental, no vocals, " + caption
    spec = {
        "task": "cover",
        "caption": caption,
        "lyrics": _lyrics(data.get("lyrics"), vocals != "keep"),
        "cover_strength": _number(data.get("cover_strength"), 0.2, 1.0, 0.6 if vocals == "keep" else 0.8),
    }
    return spec, str(data.get("title") or title)[:60], model if data else "", str(data.get("why") or "")[:200]
