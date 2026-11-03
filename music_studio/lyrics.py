"""Lyrics on a clock, for a song's video: the sung lines of a take's words (section tags such as
``[Chorus]`` left out), when each one starts, as LRC text a person can read and edit, and how to
find those times.

The music engine sends lyrics without times. :func:`align` finds them from what Whisper heard in the
song (``music_studio.listen``): the heard words are matched with the lyrics in order, sound by sound,
so a word heard wrong or a line not heard at all doesn't throw the rest off, and a line starts where
its first words were heard. Without listening, :func:`guess` spreads the lines over the part of the
song where the music plays, each by how many syllables it has. Either way the studio's page lets a
person tap along or nudge each line.
"""

from __future__ import annotations

import dataclasses
import difflib
import functools
import re
import unicodedata

import numpy as np
from pypinyin import lazy_pinyin

STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")
# A line that is only a section's name ([Verse 1], 【副歌】) or a direction such as (Instrumental);
# "(oh, oh)" is sung.
TAG = re.compile(r"^\s*(\[[^\]]*\]|【[^】]*】|[(（][^)）]*(instrumental|inst\b|solo|interlude|break|intro|outro|間奏|前奏|尾奏|獨奏)[^)）]*[)）])\s*$", re.IGNORECASE)
SECTION_GAP = 6  # a break between sections, in syllables' time
VOWELS = re.compile(r"[aeiouyàáâãäåæèéêëìíîïòóôõöøùúûüýœ]+")
SKIP = 0.45  # what matching costs for a sung sound left out, on either side (a match earns up to 1)
ALIKE = 0.6  # a lyric's sound and a heard one count as the same from this likeness


@dataclasses.dataclass(frozen=True)
class Line:
    at: float  # seconds
    text: str
    end: float = 0.0  # when its singing ends, if it was heard (0: not known)
    heard: bool | None = None  # found by listening to the song (None: nobody listened)


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


def units(text: str) -> list[str]:
    """What a line is matched by, sound by sound: each word in letters (lower case, no accents), and
    each Chinese character by its sound (pinyin), so simplified and traditional characters, and a
    wrong character with the right sound, still match. Kana and hangul stand for themselves."""
    out = []
    for piece in re.findall(r"[A-Za-z\u00c0-\u024f'’]+|\d+|[^\W\d_]", text or ""):
        if piece[0].isascii() or "\u00c0" <= piece[0] <= "\u024f":
            folded = "".join(c for c in unicodedata.normalize("NFKD", piece.lower()) if c.isalnum())
            if folded:
                out.append(folded)
        elif "\u3400" <= piece <= "\u9fff" or "\uf900" <= piece <= "\ufaff":
            out.append(lazy_pinyin(piece)[0])
        else:
            out.append(piece)
    return out


@functools.lru_cache(maxsize=1 << 16)
def _alike(a: str, b: str) -> float:
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def align(texts: list[str], words: list[tuple[float, float, str]], seconds: float) -> list[Line]:
    """When each line of ``texts`` is sung, from the ``words`` heard in the song (start, end, text).
    The heard sounds are matched with the lyrics' in order (Needleman-Wunsch, free at both ends of
    what was heard, so noise before or after the singing costs nothing); a line starts where its
    first matched sound was heard, less the time of any sounds of it that weren't. A line counts as
    heard only when enough of it was (a single common word isn't); the others (``heard`` False:
    the singer may have left them out) are spread over the time between their neighbours."""
    lyric = [(k, unit) for k, text in enumerate(texts) for unit in units(text)]
    order = [q for text in texts for q in range(len(units(text)))]  # each sound's place in its line
    sung: list[tuple[str, float, float]] = []
    for start, end, text in words:
        found = units(text)
        step = max(0.0, end - start) / max(1, len(found))
        sung += [(unit, start + i * step, start + (i + 1) * step) for i, unit in enumerate(found)]
    n, m = len(lyric), len(sung)
    if not n or not m:
        return [Line(0.0, text, heard=False) for text in texts]
    names = sorted({unit for _, unit in lyric}), sorted({unit for unit, _, _ in sung})
    alike = np.array([[_alike(a, b) for b in names[1]] for a in names[0]])
    place = [{unit: k for k, unit in enumerate(group)} for group in names]
    score = 2 * alike[np.ix_([place[0][u] for _, u in lyric], [place[1][u] for u, _, _ in sung])] - 1
    total = np.zeros((n + 1, m + 1))
    total[1:, 0] = -SKIP * np.arange(1, n + 1)
    reach = SKIP * np.arange(m + 1)
    for i in range(1, n + 1):
        best = np.empty(m + 1)
        best[0] = total[i, 0]
        best[1:] = np.maximum(total[i - 1, :-1] + score[i - 1], total[i - 1, 1:] - SKIP)
        total[i] = np.maximum.accumulate(best + reach) - reach  # or leave heard sounds out, each for SKIP
    hits: dict[int, list[tuple[int, float, float]]] = {}
    i, j = n, int(np.argmax(total[n]))
    while i > 0 and j > 0:
        if np.isclose(total[i, j], total[i - 1, j - 1] + score[i - 1, j - 1]):
            if score[i - 1, j - 1] >= 2 * ALIKE - 1:
                hits.setdefault(lyric[i - 1][0], []).append((order[i - 1], sung[j - 1][1], sung[j - 1][2]))
            i, j = i - 1, j - 1
        elif np.isclose(total[i, j], total[i - 1, j] - SKIP):
            i -= 1
        else:
            j -= 1
    lengths = [end - start for found in hits.values() for _, start, end in found]
    unit = float(np.clip(np.median(lengths), 0.15, 0.6)) if lengths else 0.3
    timed: list[Line | None] = []
    before = 0.0
    for k, text in enumerate(texts):
        found = sorted(hits.get(k, []))
        count = len(units(text))
        if len(found) < min(2, count) or len(found) < 0.3 * count:
            timed.append(None)
            continue
        at = max(before, found[0][1] - found[0][0] * unit)
        end = min(seconds, max(found[-1][2] + (count - 1 - found[-1][0]) * unit, at + unit))
        timed.append(Line(round(at, 2), text, round(end, 2), True))
        before = found[-1][2]
    return _between(timed, texts, seconds)


def _between(timed: list[Line | None], texts: list[str], seconds: float) -> list[Line]:
    """Lines nobody heard, spread by their syllables over the time between the heard ones."""
    out = list(timed)
    k = 0
    while k < len(out):
        if out[k] is not None:
            k += 1
            continue
        last = k
        while last < len(out) and out[last] is None:
            last += 1
        start = out[k - 1].end if k > 0 else 0.0  # type: ignore[union-attr]
        stop = out[last].at if last < len(out) else seconds  # type: ignore[union-attr]
        weights = [syllables(texts[q]) for q in range(k, last)]
        step = max(0.0, stop - start) / (sum(weights) + 1)
        at = start + step / 2
        for q, weight in zip(range(k, last), weights):
            out[q] = Line(round(at, 2), texts[q], heard=False)
            at += weight * step
        k = last
    return out  # type: ignore[return-value]


def shown(lines: list[Line], seconds: float) -> list[tuple[float, float, str, str]]:
    """What the video shows and when: (from, to, the line being sung, the line that comes next). A
    line stays until the next starts, or a while after it is sung when a long break follows; the
    next line shows dimmed a little before it comes."""
    out: list[tuple[float, float, str, str]] = []
    cues = sorted((line for line in lines if line.text and 0 <= line.at < seconds), key=lambda line: line.at)
    for k, line in enumerate(cues):
        following = cues[k + 1] if k + 1 < len(cues) else None
        until = following.at if following else seconds
        sung = line.end - line.at if line.end > line.at else min(9.0, max(3.0, 1.2 + 0.45 * syllables(line.text)))
        hold = min(until, line.at + max(1.5, sung + (1.0 if line.end > line.at else 0.0)))
        out.append((line.at, hold, line.text, following.text if following else ""))
        if following and hold < until:
            ahead = max(hold, until - 3.0)
            if ahead > hold:
                out.append((hold, ahead, "", ""))
            out.append((ahead, until, "", following.text))
    if cues and cues[0].at > 0:
        out.insert(0, (max(0.0, cues[0].at - 3.0), cues[0].at, "", cues[0].text))
    return [cue for cue in out if cue[1] - cue[0] > 0.01]
