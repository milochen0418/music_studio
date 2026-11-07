"""How a take was made, kept beside it so a person can look back at each piece and learn from it:
who decided (the AI Hub's role and the model that answered), the rules and the message the
producer got, its whole answer as written, what was handed to the music engine (or to the studio's
own composer or remaker), and what the engine said when it was done.

A take keeps this as ``making.json`` in its draft folder (:mod:`music_studio.drafts`), and a kept
take carries it into its library item. Version 1:

    {"version": 1,
     "kind": "composed" | "sung" | "remake" | "cover" | "repaint" (one stretch of a take made again),
     "words": what the person wrote ("" when nothing),
     "producer": {"role", "model", "system", "asked", "answer", "stop", "seconds", "problem"},
                 or None when nobody was asked (a loop cut as the song sounds),
     "listening": {"model", "language", "lines"}: the speech model that heard the recording's
                  words, for a remake that sings them again,
     "lyrics_from": {"from": "lrclib" | "heard" | "typed", "edited", ...}: where the words sung
                  again came from (LRCLIB's song, what the AI heard, or the person's own) and
                  whether the person changed them before the remake,
     "again_of": {"id", "title"}: the take whose settings were used again (with a new seed),
     "compare": {"bpm": [recording, take], "key": [...], "seconds": [...], "lines": [heard, all]}:
                the take measured against what it was made from,
     "to": "engine" | "composer" | "remaker",
     "request": what was handed on: the engine's spec without the recording, the composer's
                brief and seed, the remaker's plan,
     "engine": {"models", "metas", "seconds", "id"}: what the engine said when it was done
               (``metas.seed`` makes the same song again from the same request),
     "id", "made_at"}

Takes made before records were kept get what their ``info.json`` still says (``old``).
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

VERSION = 1
# The engine's steps and the remake levels (as in producer: kept here so this module needs no model).
STEPS = 8
LEVELS = {"free": 0.5, "standard": 0.75, "close": 1.0}


def record(
    kind: str,
    words: str,
    talk: Any,
    to: str,
    request: dict[str, Any],
    *,
    engine: dict[str, Any] | None = None,
    listening: dict[str, Any] | None = None,
    **more: Any,
) -> dict[str, Any]:
    """A take's making record. ``talk`` is the producer's :class:`~music_studio.producer.Talk`
    (or its dict; None when it wasn't asked); ``more`` adds ``lyrics_from``, ``again_of``,
    ``compare``."""
    found: dict[str, Any] = {
        "version": VERSION,
        "kind": kind,
        "words": words,
        "producer": talk if isinstance(talk, dict) or talk is None else dataclasses.asdict(talk),
        "to": to,
        "request": request,
    }
    if listening:
        found["listening"] = listening
    if engine:
        found["engine"] = engine
    found.update({k: v for k, v in more.items() if v})
    return found


def engine_said(song: Any) -> dict[str, Any]:
    """What the engine said about a finished song (an ``ai.Song``)."""
    return {"models": dict(song.models or {}), "metas": dict(song.metas or {}), "seconds": round(float(song.secs or 0), 1), "id": song.id}


def of_take(info: dict[str, Any], saved: dict[str, Any] | None) -> dict[str, Any]:
    """The record of a take: as kept, or for a take from before records were kept, what its
    ``info.json`` still says."""
    if saved:
        return saved
    origin = str(info.get("origin") or "")
    engine = info.get("engine") if isinstance(info.get("engine"), dict) else None
    if engine:
        request = {k: info[k] for k in ("caption", "language", "lyrics") if info.get(k)}
        if isinstance(info.get("plan"), dict):
            request.update(info["plan"])
    elif isinstance(info.get("plan"), dict):
        request = dict(info["plan"])
    else:
        request = {k: info[k] for k in ("style", "bpm", "key", "mood", "seed") if info.get(k) not in (None, "")}
    model = str(info.get("model") or "")
    return {
        "version": VERSION,
        "old": True,
        "kind": origin,
        "words": str(info.get("words") or ""),
        "producer": {"role": "smart", "model": model} if model else None,
        "to": "engine" if engine else "remaker" if origin == "remake" else "composer",
        "request": request,
        **({"engine": {"models": engine}} if engine else {}),
        "id": info.get("id") or "",
        "made_at": info.get("at") or 0,
    }


# ------------------------------------------------------------------ shown


@dataclasses.dataclass
class Part:
    """One part of a record as the page shows it: a heading and its text."""

    head: str = ""
    body: str = ""
    fold: bool = False  # long and the same each time: folded until opened
    mono: bool = False  # written for a program: shown as it is


def _fill(text: str, **values: Any) -> str:
    return str(text or "").format(**values)


def _value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def handed(request: dict[str, Any]) -> str:
    """What was handed on, one field a line, leaving out the empty ones (left to the program);
    long texts (the lyrics) last, under their name."""
    given = {k: v for k, v in request.items() if v not in (None, "") and v != [] and v != {}}
    short = [f"{k}: {_value(v)}" for k, v in given.items() if not (isinstance(v, str) and "\n" in v)]
    long = [f"{k}:\n{v}" for k, v in given.items() if isinstance(v, str) and "\n" in v]
    return "\n".join(short + long)


def _engine_name(models: dict[str, Any]) -> str:
    names = [str(models[k]) for k in ("dit", "lm") if models.get(k)]
    return f"ACE-Step ({', '.join(names)})" if names else "ACE-Step"


def _level_line(request: dict[str, Any], t: dict[str, str]) -> str:
    try:
        strength = float(request["cover_strength"])
    except (KeyError, TypeError, ValueError):
        return ""
    name = min(LEVELS, key=lambda k: abs(LEVELS[k] - strength))
    return _fill(t["mk_level"], level=t.get(f"level_{name}", name), n=int(STEPS * strength), all=STEPS)


def _who(found: dict[str, Any], t: dict[str, str]) -> str:
    rows = []
    again = found.get("again_of") or {}
    if again:
        rows.append(_fill(t["mk_again"], title=again.get("title") or again.get("id") or ""))
    talk = found.get("producer")
    if not talk:
        rows.append(t["mk_by_you"] if found.get("kind") == "repaint" else t["mk_not_asked"])
    elif talk.get("model") and not talk.get("problem"):
        line = _fill(t["mk_producer"], role=talk.get("role") or "smart", model=talk["model"])
        if talk.get("seconds"):
            line += _fill(t["mk_took"], s=round(float(talk["seconds"])))
        rows.append(line)
    else:
        rows.append(_fill(t["mk_no_producer"], why=talk.get("problem") or "?"))
    heard = found.get("listening")
    if heard:
        rows.append(_fill(t["mk_listener"], model=heard.get("model") or "", language=heard.get("language") or "?", n=heard.get("lines") or 0))
    words = found.get("lyrics_from") or {}
    if words.get("from") in ("lrclib", "heard", "typed"):
        line = _fill(t[f"mk_words_{words['from']}"], artist=words.get("artist") or "", track=words.get("track") or "")
        rows.append(line + (t["mk_words_edited"] if words.get("edited") else ""))
    level = _level_line(found.get("request") or {}, t)
    if level:
        rows.append(level)
    to = found.get("to")
    if to == "engine":
        engine = found.get("engine") or {}
        line = _fill(t["mk_engine"], name=_engine_name(engine.get("models") or {}))
        if engine.get("seconds"):
            line += _fill(t["mk_took"], s=round(float(engine["seconds"])))
        seed = (engine.get("metas") or {}).get("seed")
        if seed not in (None, ""):
            line += _fill(t["mk_seed"], seed=seed)
        rows.append(line)
    elif to == "composer":
        rows.append(t["mk_composer"])
    elif to == "remaker":
        rows.append(t["mk_remaker"])
    return "\n".join(rows)


def parts(found: dict[str, Any], t: dict[str, str]) -> list[Part]:
    """The record as the page shows it, in the page's language."""
    if not found:
        return []
    out = [Part(t["mk_who"], _who(found, t)), Part(t["mk_words"], str(found.get("words") or "") or t["mk_nothing"])]
    talk = found.get("producer") or {}
    if talk.get("system"):
        out.append(Part(t["mk_rules"], talk["system"], fold=True, mono=True))
    if talk.get("asked"):
        out.append(Part(t["mk_asked"], talk["asked"], mono=True))
    if talk.get("answer"):
        stop = talk.get("stop") or ""
        out.append(Part(t["mk_answer"] + (_fill(t["mk_stop"], stop=stop) if stop and stop != "end_turn" else ""), talk["answer"], mono=True))
    request = found.get("request") or {}
    if request:
        head = {"engine": t["mk_to_engine"], "composer": t["mk_to_composer"], "remaker": t["mk_to_remaker"]}.get(str(found.get("to") or ""), t["mk_to_engine"])
        out.append(Part(head, handed(request), mono=True))
    metas = {k: v for k, v in ((found.get("engine") or {}).get("metas") or {}).items() if v not in (None, "", "N/A")}
    if metas:
        out.append(Part(t["mk_engine_said"], handed(metas), mono=True))
    compared = compare_text(found.get("compare") or {}, t)
    if compared:
        out.append(Part(t["mk_compare"], compared))
    return out


def _clock(seconds: Any) -> str:
    m, s = divmod(int(round(float(seconds or 0))), 60)
    return f"{m}:{s:02d}"


def compare_text(compare: dict[str, Any], t: dict[str, str]) -> str:
    """The take against what it was made from, a line each: tempo, key, length, lines sung."""
    rows = []
    for name, show in (("bpm", lambda v: f"{float(v):.0f} BPM"), ("key", str), ("seconds", _clock)):
        pair = compare.get(name)
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(v not in (None, "") for v in pair):
            rows.append(_fill(t[f"mk_cmp_{name}"], a=show(pair[0]), b=show(pair[1])))
    measured = bool(rows)
    lines = compare.get("lines")
    if isinstance(lines, (list, tuple)) and len(lines) == 2:
        rows.append(_fill(t["mk_cmp_lines"], n=lines[0], all=lines[1]))
    if measured:
        # Measured by a program: a tempo found at twice or half the speed, or a key a fifth away,
        # is often the same song as heard.
        rows.append(t["mk_cmp_rough"])
    return "\n".join(rows)


def _fence(body: str) -> str:
    """A code fence longer than any run of backticks in ``body`` (a model's answer may have its own)."""
    longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
    return "`" * max(3, longest + 1)


def as_text(title: str, shown: list[Part], old: str = "") -> str:
    """The record as plain text (Markdown), to copy into one's own notes."""
    blocks = [f"# {title}"] + ([old] if old else [])
    for part in shown:
        fence = _fence(part.body)
        blocks.append(f"## {part.head}\n\n{fence}\n{part.body}\n{fence}" if part.mono else f"## {part.head}\n\n{part.body}")
    return "\n\n".join(blocks) + "\n"
