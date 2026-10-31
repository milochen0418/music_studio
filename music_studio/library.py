"""The shared ``audio`` collection: what can be changed, and where a kept take goes.

A take becomes an ``audio.file`` item, ``audio:music-studio/<id>``, with these in its ``meta`` beside
the usual ``duration`` and ``format``:

- ``origin``: ``composed`` (written here) or ``remake`` (made from another recording);
- ``rights``: ``own`` (nothing of anyone else's in it) or ``third-party`` (made from a recording
  somebody else may hold the rights to: for your own listening unless you have permission);
- ``loop_start``, ``loop_end`` (s): a player that reaches the second may jump to the first and
  nobody hears it;
- ``bpm``, ``key``, ``style``, ``mood``, ``words`` (what was asked for), ``model`` (who decided);
- ``artist``: this studio, which is what Music Box and the mixer show.

The item's ``source`` is the studio's page. A remake says what it came from with ``derived_from``.
"""

from __future__ import annotations

import dataclasses
import re
import secrets
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from reflex_ddns_auth.collections import Collection, CollectionError
from reflex_ddns_auth.intent.protocol import app_url

from music_studio import drafts

COLLECTION = "audio"
KIND = "audio.file"
APP_ID = "music-studio"
MAKER = "Music Studio 音樂工坊"  # what other apps show as who made it


def audio() -> Collection:
    return Collection(COLLECTION, app_id=APP_ID)


def _clock(seconds: float) -> str:
    m, s = divmod(int(round(seconds or 0)), 60)
    return f"{m}:{s:02d}"


@dataclasses.dataclass
class Source:
    ref: str
    title: str
    clock: str
    origin: str  # who brought it: the app's name


def sources() -> list[Source]:
    """What is in the library here, newest first, for changing."""
    try:
        items = audio().items(kind=KIND, remote=False)
    except CollectionError:
        return []
    items.sort(key=lambda i: i.created_at, reverse=True)
    rows = []
    for item in items:
        path = item.primary
        if path is None or not path.is_file():
            continue
        try:
            seconds = float(item.meta.get("duration") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        rows.append(Source(item.ref, item.title or item.id, _clock(seconds), item.owner))
    return rows


def source_file(ref: str) -> tuple[Path | None, dict[str, str]]:
    """A library item's file, and what a remake must say about it."""
    try:
        item = audio().get(ref, remote=False)
    except CollectionError:
        return None, {}
    if item is None or item.kind != KIND:
        return None, {}
    # What this app composed stays free to use; anything else may be somebody's.
    own = item.meta.get("rights") == "own"
    return item.primary, {"ref": ref, "title": item.title, "rights": "own" if own else "third-party"}


def _item_id(title: str) -> str:
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40]
    return f"{slug or 'piece'}-{secrets.token_hex(3)}"


def publish_piece(item_id: str, title: str, audio_file: Path, cover: Path | None, meta: dict[str, Any], derived: Iterable[str] = ()) -> str:
    """A finished piece into the library, signed by this studio; its ref."""
    collection = audio()
    signed = {**meta, "artist": MAKER}
    with collection.publish(item_id, kind=KIND, title=title, meta=signed, source=f"{app_url(APP_ID)}/", derived_from=derived, primary="piece.mp3") as item:
        item.add_file(audio_file, "piece.mp3")
        if cover is not None:
            item.set_thumbnail(cover)
    return collection.ref(item_id)


def keep(take: dict[str, Any]) -> str:
    """Publishes a take; its ref."""
    path = drafts.audio_path(take["id"])
    if path is None:
        raise FileNotFoundError("this take is gone")
    meta = {
        "duration": take["seconds"],
        "format": "mp3",
        **{k: take.get(k, "") for k in ("origin", "rights", "bpm", "key", "style", "mood", "words", "model", "why", "loop_start", "loop_end")},
    }
    title = take.get("title") or "New piece"
    derived = [take["from_ref"]] if take.get("from_ref") else []
    return publish_piece(_item_id(title), title, path, drafts.cover_path(take["id"]), meta, derived)
