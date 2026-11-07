"""What has been made and not yet kept. Each take is a folder in ``MUSIC_STUDIO_DATA_DIR/drafts``:
``take.mp3``, ``cover.png``, ``info.json`` and ``making.json`` (how it was made: see
:mod:`music_studio.making`). Keeping one publishes it into the shared ``audio`` collection
(:mod:`music_studio.library`); only the newest ones stay here.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import time
from pathlib import Path
from typing import Any

from music_studio import art
from music_studio.composer import Brief, compose
from music_studio.remake import Analysis, Plan, decode, remake

KEEP = 24
MAKING = "making.json"


def data_dir() -> Path:
    return Path(os.environ.get("MUSIC_STUDIO_DATA_DIR") or Path.home() / ".local" / "share" / "music_studio")


def _root() -> Path:
    path = data_dir() / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save(piece: Any, info: dict[str, Any], style: str, making: dict[str, Any] | None = None) -> dict[str, Any]:
    draft = f"{int(time.time())}-{secrets.token_hex(3)}"
    folder = _root() / draft
    folder.mkdir()
    if making is not None:
        record = {**making, "id": draft, "made_at": time.time()}
        (folder / MAKING).write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    piece.save(folder / "take.mp3")
    (folder / "cover.png").write_bytes(art.cover(piece.audio, style))
    start, end = piece.loop
    full = {
        **info,
        "id": draft,
        "at": time.time(),
        "seconds": round(piece.seconds, 2),
        "loop_start": round(start, 4),
        "loop_end": round(end, 4),
        "wave": art.wave_path(piece.audio),
    }
    (folder / "info.json").write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
    _tidy()
    return full


def take_composed(brief: Brief, seed: int, words: str, model: str, why: str, making: dict[str, Any] | None = None) -> dict[str, Any]:
    piece = compose(brief, seed)
    return _save(
        piece,
        {
            "origin": "composed",
            "rights": "own",
            "title": brief.title,
            "style": brief.style,
            "bpm": piece.score.bpm,
            "key": f"{piece.score.key} {piece.score.mode}",
            "mood": brief.mood,
            "words": words,
            "model": model,
            "why": why,
            "seed": seed,
        },
        brief.style,
        making,
    )


def take_remade(
    path: Path, plan: Plan, bars: int, analysis: Analysis, source: dict[str, str], words: str, model: str, why: str, making: dict[str, Any] | None = None
) -> dict[str, Any]:
    piece = remake(path, plan, bars, analysis)
    return _save(
        piece,
        {
            "origin": "remake",
            "rights": source.get("rights") or "third-party",
            "title": plan.title or source.get("title") or "",
            "style": plan.beat,
            "bpm": round(piece.bpm),
            "key": f"{piece.key} {piece.mode}",
            "mood": "",
            "words": words,
            "model": model,
            "why": why,
            "from_ref": source.get("ref") or "",
            "from_title": source.get("title") or "",
            "plan": {"speed": round(plan.speed, 3), "pitch": plan.pitch, "tone": plan.tone, "room": round(plan.room, 2), "beat": plan.beat},
        },
        "remake",
        making,
    )


class _Made:
    """A finished song from the engine, as ``_save`` takes it."""

    def __init__(self, mp3: bytes):
        self.mp3 = mp3
        self.audio = None
        self.loop = (0.0, 0.0)  # the engine's songs end; a player starts them again

    @property
    def seconds(self) -> float:
        return self.audio.shape[0] / 44100

    def save(self, path: Path) -> Path:
        path.write_bytes(self.mp3)
        return path


def take_engine(mp3: bytes, info: dict[str, Any], making: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keeps what the engine made: ``info`` says what it is (origin sung or cover, rights, title,
    words, model, why, the spec it was made from, what it came from); ``making`` how it was made."""
    made = _Made(mp3)
    folder = _root() / "incoming"
    folder.mkdir(exist_ok=True)
    tmp = folder / f"{secrets.token_hex(4)}.mp3"
    tmp.write_bytes(mp3)
    try:
        made.audio = decode(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return _save(made, {"style": "", "bpm": 0, "key": "", "mood": "", "seed": 0, **info}, info.get("origin") or "sung", making)


def info(draft: str) -> dict[str, Any] | None:
    path = _folder(draft)
    if path is None:
        return None
    try:
        return json.loads((path / "info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _folder(draft: str) -> Path | None:
    if not draft or "/" in draft or "\\" in draft or draft.startswith("."):
        return None
    path = _root() / draft
    return path if path.is_dir() else None


def audio_path(draft: str) -> Path | None:
    path = _folder(draft)
    return path / "take.mp3" if path is not None and (path / "take.mp3").is_file() else None


def cover_path(draft: str) -> Path | None:
    path = _folder(draft)
    return path / "cover.png" if path is not None and (path / "cover.png").is_file() else None


def making_path(draft: str) -> Path | None:
    path = _folder(draft)
    return path / MAKING if path is not None and (path / MAKING).is_file() else None


def making(draft: str) -> dict[str, Any] | None:
    """How a take was made, as kept when it was (None for takes from before records were kept)."""
    path = making_path(draft)
    if path is None:
        return None
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def update(draft: str, **fields: Any) -> None:
    now = info(draft)
    path = _folder(draft)
    if now is not None and path is not None:
        (path / "info.json").write_text(json.dumps({**now, **fields}, ensure_ascii=False), encoding="utf-8")


def recent() -> list[dict[str, Any]]:
    """The takes, newest first."""
    out = []
    for folder in sorted(_root().iterdir(), reverse=True):
        found = info(folder.name)
        if found:
            out.append(found)
    return out[:KEEP]


def _tidy() -> None:
    folders = sorted((p for p in _root().iterdir() if p.is_dir()), reverse=True)
    for old in folders[KEEP:]:
        shutil.rmtree(old, ignore_errors=True)
