"""Lyrics on a clock, for a song's video: the sung lines of a take's words (section tags such as
``[Chorus]`` left out), when each one starts, as LRC text a person can read and edit, and a first
guess at those times when nobody has given any.

The music engine sends lyrics without times, so :func:`guess` spreads the lines over the part of the
song where the music plays, each by how many syllables it has, with a short break between sections.
It is only a start: the studio's page lets a person tap along or nudge each line.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata

import numpy as np

STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")
# A line that is only a section's name ([Verse 1], 【副歌】) or a direction such as (Instrumental);
# "(oh, oh)" is sung.
TAG = re.compile(r"^\s*(\[[^\]]*\]|【[^】]*】|[(（][^)）]*(instrumental|inst\b|solo|interlude|break|intro|outro|間奏|前奏|尾奏|獨奏)[^)）]*[)）])\s*$", re.IGNORECASE)
SECTION_GAP = 6  # a break between sections, in syllables' time
VOWELS = re.compile(r"[aeiouyàáâãäåæèéêëìíîïòóôõöøùúûüýœ]+")


@dataclasses.dataclass(frozen=True)
class Line:
    at: float  # seconds
    text: str


def clock(seconds: float) -> str:
    """``1:23.4``."""
    tenths = int(round(max(0.0, seconds) * 10))
    return f"{tenths // 600}:{tenths % 600 / 10:04.1f}"


def read_clock(text: str) -> float | None:
    """Seconds from ``1:23.4``, ``01:23.40`` or ``83.4``; None when it isn't a time."""
    parts = str(text or "").strip().replace("：", ":").split(":")
    try:
        if len(parts) == 1:
            value = float(parts[0])
        elif len(parts) == 2:
            value = int(parts[0]) * 60 + float(parts[1])
        else:
            return None
    except ValueError:
        return None
    return value if value >= 0 else None


def sections(lyrics: str) -> list[list[str]]:
    """The sung lines, in groups as the tags (or, without tags, the blank lines) part them."""
    groups: list[list[str]] = [[]]
    for raw in STAMP.sub("", lyrics or "").splitlines():
        text = raw.strip()
        if not text or TAG.match(text):
            if groups[-1]:
                groups.append([])
            continue
        groups[-1].append(text)
    return [g for g in groups if g]


def has_times(text: str) -> bool:
    return bool(STAMP.search(text or ""))


def from_lrc(text: str) -> list[Line]:
    """The lines of LRC text (``[01:23.40]words``), by time. A line with several stamps is sung
    several times; lines without one are left out."""
    out = []
    for raw in (text or "").splitlines():
        stamps = STAMP.findall(raw)
        words = STAMP.sub("", raw).strip()
        if not stamps or TAG.match(words):
            continue
        for minutes, seconds in stamps:
            out.append(Line(round(int(minutes) * 60 + float(seconds.replace(":", ".")), 2), words))
    return sorted(out, key=lambda line: line.at)


def to_lrc(lines: list[Line]) -> str:
    def stamp(at: float) -> str:
        hundredths = int(round(max(0.0, at) * 100))
        return f"[{hundredths // 6000:02d}:{hundredths % 6000 // 100:02d}.{hundredths % 100:02d}]"

    return "\n".join(f"{stamp(line.at)}{line.text}" for line in lines)


def syllables(text: str) -> int:
    """About how many syllables are sung: one per Chinese character, kana or hangul block, and the
    vowel groups of words in letters."""
    count = 0
    for run in re.findall(r"[^\W\d_]+", text or ""):
        if unicodedata.name(run[0], "").startswith("LATIN"):
            for word in re.findall(r"[^\W\d_]+", run):
                count += max(1, len(VOWELS.findall(word.lower())))
        else:
            count += len(run)
    return max(1, count)


def _span(seconds: float, loudness: np.ndarray | None, step: float) -> tuple[float, float]:
    """Where the singing probably is: after the intro and before the ending dies away."""
    edge = min(10.0, seconds * 0.08)
    start, end = edge, seconds - edge
    if loudness is not None and loudness.size > 8:
        playing = np.flatnonzero(loudness >= np.median(loudness) * 0.5)
        if playing.size:
            start = max(start, float(playing[0]) * step)
            end = min(end, float(playing[-1] + 1) * step)
    return start, max(end, start + 1.0)


def guess(lyrics: str, seconds: float, loudness: np.ndarray | None = None, step: float = 0.5) -> list[Line]:
    """When each line is probably sung. ``loudness``: the song's level every ``step`` seconds."""
    groups = sections(lyrics)
    if not groups or seconds <= 0:
        return []
    start, end = _span(seconds, loudness, step)
    plan = [(SECTION_GAP if g and k == 0 else 0, syllables(text), text) for g, group in enumerate(groups) for k, text in enumerate(group)]
    unit = (end - start) / sum(gap + n for gap, n, _ in plan)
    out, at = [], start
    for gap, n, text in plan:
        at += gap * unit
        out.append(Line(round(at, 2), text))
        at += n * unit
    return out


def shown(lines: list[Line], seconds: float) -> list[tuple[float, float, str, str]]:
    """What the video shows and when: (from, to, the line being sung, the line that comes next). A
    line stays until the next starts, or a while after it is sung when a long break follows; the
    next line shows dimmed a little before it comes."""
    out: list[tuple[float, float, str, str]] = []
    cues = sorted((line for line in lines if line.text and 0 <= line.at < seconds), key=lambda line: line.at)
    for k, line in enumerate(cues):
        following = cues[k + 1] if k + 1 < len(cues) else None
        until = following.at if following else seconds
        hold = min(until, line.at + min(9.0, max(3.0, 1.2 + 0.45 * syllables(line.text))))
        out.append((line.at, hold, line.text, following.text if following else ""))
        if following and hold < until:
            ahead = max(hold, until - 3.0)
            if ahead > hold:
                out.append((hold, ahead, "", ""))
            out.append((ahead, until, "", following.text))
    if cues and cues[0].at > 0:
        out.insert(0, (max(0.0, cues[0].at - 3.0), cues[0].at, "", cues[0].text))
    return [cue for cue in out if cue[1] - cue[0] > 0.01]
