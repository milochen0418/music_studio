"""Lyrics somebody already wrote down: LRCLIB (https://lrclib.net), a free, open database of song
lyrics (most with their times), shared by its users. Before the AI listens to a recording for its
words, a remake looks the song up there by its title; what it finds is shown to the person to
check, as what the AI hears is. Only the cleaned-up title leaves this computer.

``MUSIC_STUDIO_LRCLIB=0`` turns it off.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
from typing import Any

import httpx

from music_studio import lyrics

logger = logging.getLogger(__name__)
URL = "https://lrclib.net/api/search"
AGENT = "MusicStudio/1.0 (Agentic App Store)"  # LRCLIB asks clients to say who they are
TIMEOUT = 8.0
TRIES = 6  # searches at most per song: LRCLIB finds nothing when one word is too many
# How far a found song's length may be from the recording's: a music video often has an intro or
# an ending the record doesn't.
NEAR = 3.0
FAR = 25.0
# What video titles add around a song's name (the name itself is often in 【】 or 《》).
BRACKETS = re.compile(r"[(\[【（《「『)\]】）》」』]")
NOISE = re.compile(
    r"(?i)\b(official|music|video|lyric[s]?|audio|visuali[sz]er|hd|hq|4k|mv|m/v|live|remaster(ed)?|full|version|ver\.?)\b"
    r"|官方|完整版|高清|動態歌詞|歌詞版|字幕|中字|首播|正式版|完整|版本"
)


@dataclasses.dataclass
class Found:
    lyrics: str  # plain lines, the song's parts split by blank lines
    track: str
    artist: str
    seconds: float
    id: int
    near: bool  # as long as the recording, give or take NEAR seconds: very likely the same version

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "track": self.track, "artist": self.artist, "seconds": self.seconds, "near": self.near}


def enabled() -> bool:
    return os.environ.get("MUSIC_STUDIO_LRCLIB", "1").strip().lower() not in ("0", "false", "no", "off")


def query_of(title: str) -> str:
    """A video or file title as a search: without brackets, "official MV" and the like."""
    return " ".join(chunks(title))[:120]


def chunks(title: str) -> list[str]:
    """The names in a title: runs of Chinese, Japanese or Korean, and runs of Latin words, so a
    singer's name written both ways ("周杰倫 Jay Chou") and the song's own name come apart."""
    text = re.sub(r"\.(mp3|wav|m4a|flac|ogg)$", "", title or "", flags=re.IGNORECASE)
    text = BRACKETS.sub(" ", text)
    for _ in range(2):  # "完整版MV": the second pass takes what the first one bared
        text = NOISE.sub(" ", text)
    text = re.sub(r"[\s\-–—_|/:,，、]+", " ", text)
    runs = re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+|[^\s\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+(?: [^\s\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+)*", text)
    return [run.strip() for run in runs if len(run.strip()) >= 2 or re.match(r"[\u3400-\u9fff]", run)]


def queries(title: str) -> list[str]:
    """What to search for, in order: the whole name, then two of its parts at a time."""
    parts = chunks(title)
    out = [" ".join(parts)] if parts else []
    pairs = [(i, i + 1) for i in range(len(parts) - 1)] + [(i, j) for i in range(len(parts)) for j in range(i + 2, len(parts))]
    for i, j in pairs:
        out.append(f"{parts[i]} {parts[j]}")
    seen: list[str] = []
    for q in out:
        if q and q not in seen:
            seen.append(q[:120])
    return seen[:TRIES]


def _key(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").casefold())


def _parts(text: str) -> int:
    return len([block for block in re.split(r"\n\s*\n", text) if block.strip()])


def _text_of(row: dict[str, Any]) -> str:
    """The lyrics as plain lines: from the timed ones when their pauses part the song better."""
    plain = str(row.get("plainLyrics") or "").strip()
    timed = lyrics.from_lrc_text(str(row.get("syncedLyrics") or ""))
    return timed if timed and _parts(timed) >= _parts(plain) else plain or timed


def pick(rows: list[dict[str, Any]], title: str, seconds: float) -> Found | None:
    """The row that is this song: its name in the title, and its singer's too (or the very same
    length); the one nearest in length wins, if it is near enough."""
    named = _key(title)
    best: tuple[float, dict[str, Any]] | None = None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("instrumental") or not _text_of(row):
            continue
        track, artist = _key(str(row.get("trackName") or "")), _key(str(row.get("artistName") or ""))
        try:
            off = abs(float(row.get("duration") or 0) - seconds) if seconds else 0.0
        except (TypeError, ValueError):
            continue
        if not track or track not in named or off > FAR:
            continue
        if not (artist and artist in named) and off > NEAR:
            continue  # a song of the same name by somebody else, unless it is the very same length
        if best is None or off < best[0] or (off == best[0] and row.get("syncedLyrics") and not best[1].get("syncedLyrics")):
            best = (off, row)
    if best is None:
        return None
    off, row = best
    return Found(
        lyrics=_text_of(row),
        track=str(row.get("trackName") or ""),
        artist=str(row.get("artistName") or ""),
        seconds=float(row.get("duration") or 0),
        id=int(row.get("id") or 0),
        near=off <= NEAR,
    )


async def find(title: str, seconds: float) -> Found | None:
    """The song's lyrics from LRCLIB, if it is there (None otherwise, or when it can't be asked)."""
    if not enabled():
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": AGENT}) as client:
            for query in queries(title):
                r = await client.get(URL, params={"q": query})
                rows = r.json() if r.status_code == 200 else []
                found = pick(rows, title, seconds)
                if found is not None:
                    logger.info("LRCLIB for %r: %s - %s (%s)", query, found.artist, found.track, found.id)
                    return found
    except (httpx.HTTPError, ValueError) as e:
        logger.info("LRCLIB didn't answer: %s", e)
        return None
    logger.info("LRCLIB has nothing for %r", title)
    return None
