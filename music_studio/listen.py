"""The studio listens to a take: Whisper hears the words sung in it and when, and
:func:`music_studio.lyrics.align` matches them with the lyrics, so each line shows when it is sung.

Whisper runs in this app on the CPU (faster-whisper, int8), as English Chat's subtitles do: no
network but for the model's first download, no hub, no key. The model (``MUSIC_STUDIO_WHISPER``,
by default large-v3-turbo, about 1.6 GB) is downloaded into the app's data folder the first time it
is needed and loaded only while a song is heard, so its memory is given back. What was heard is
kept with the take (``heard.json``): lyrics changed later are matched again without listening.
"""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import numpy as np
from tqdm import tqdm

from music_studio import drafts
from music_studio.remake import decode

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # Xet downloads stall at 0 bytes on a slow line

logger = logging.getLogger(__name__)
MODEL = os.environ.get("MUSIC_STUDIO_WHISPER", "").strip() or "large-v3-turbo"
THREADS = int(os.environ.get("MUSIC_STUDIO_WHISPER_THREADS", "") or min(8, os.cpu_count() or 4))
RATE = 16000
HEARD = "heard.json"
# What Whisper is known to "hear" in music where nobody sings (subtitle credits from its training).
PHANTOMS = ("优优独播剧场", "YoYo Television", "字幕由", "字幕志愿者", "请不吝点赞", "明镜与点点", "Amara.org", "Thanks for watching", "Thank you for watching")
FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
SIZE_MB = 1600  # what the default model downloads, said before it starts

_turn = threading.Lock()  # one song at a time: it takes the cores it is given
_stopped: set[str] = set()
_busy: set[str] = set()


class Stopped(Exception):
    """The person stopped it."""


@dataclasses.dataclass
class Progress:
    phase: str = "wait"  # wait (for another song), download, load, listen
    done: float = 0.0  # 0 to 1, of this phase
    note: str = ""  # "230 / 1600 MB" while downloading


class _Quiet(io.TextIOBase):
    def write(self, text: str) -> int:
        return len(text)


class _Bar(tqdm):
    """huggingface_hub's progress bars, kept off the logs, counted for the page (as English Chat
    does: a plain tqdm, since huggingface_hub's own turns itself off without a terminal)."""

    bars: list["_Bar"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["file"] = _Quiet()
        super().__init__(*args, **kwargs)
        self.received = 0
        if self.unit == "B":
            _Bar.bars.append(self)

    def update_transfer(self, n: int = 1) -> None:
        self.received += n

    def set_transfer_postfix_str(self, *args: Any, **kwargs: Any) -> None:
        pass

    @property
    def done(self) -> int:
        return max(self.n, self.received)


def _repo() -> str:
    from faster_whisper.utils import _MODELS

    return MODEL if "/" in MODEL else _MODELS.get(MODEL, MODEL)


def _files(**more: Any) -> dict[str, Any]:
    return {"repo_id": _repo(), "cache_dir": str(drafts.data_dir() / "models"), "allow_patterns": FILES, **more}


def present() -> bool:
    """Whether the model is here, so listening needs no download."""
    import huggingface_hub

    if os.path.isdir(MODEL):
        return True
    try:
        huggingface_hub.snapshot_download(**_files(local_files_only=True))
    except Exception:  # noqa: BLE001 - not downloaded (or not all of it)
        return False
    return True


def _fetch(job: Progress) -> str:
    import huggingface_hub

    if os.path.isdir(MODEL):
        return MODEL
    try:
        return huggingface_hub.snapshot_download(**_files(local_files_only=True))
    except Exception:  # noqa: BLE001 - not downloaded yet
        pass
    job.phase = "download"
    _Bar.bars = []
    logger.info("Downloading the speech model %s", _repo())
    stop = threading.Event()

    def count() -> None:
        while not stop.wait(1.0):
            bars = [bar for bar in _Bar.bars if bar.total]
            if bars:
                total = max(bar.total for bar in bars)
                done = max(min(bar.done, bar.total) / bar.total for bar in bars if bar.total >= total / 2)
                job.done, job.note = done, f"{done * total / 1e6:.0f} / {total / 1e6:.0f} MB"

    threading.Thread(target=count, daemon=True).start()
    try:
        return huggingface_hub.snapshot_download(**_files(tqdm_class=_Bar))
    finally:
        stop.set()


def heard(draft: str) -> dict[str, Any] | None:
    """What was heard in the take, if it was listened to: model, language, seconds and the words as
    [start, end, text, how sure]."""
    audio = drafts.audio_path(draft)
    try:
        return json.loads(audio.with_name(HEARD).read_text(encoding="utf-8")) if audio is not None else None
    except (OSError, ValueError):
        return None


def busy(draft: str) -> bool:
    return draft in _busy


def stop(draft: str) -> None:
    if draft in _busy:
        _stopped.add(draft)


def language_of(take: dict[str, Any], text: str) -> str:
    """What language the song is sung in: the engine's word for it, else what the lyrics are
    written in ("" lets Whisper tell)."""
    said = str(take.get("language") or "")
    if said in ("zh", "en", "ja", "ko", "es", "fr", "de", "it", "pt", "ru"):
        return said
    if any("぀" <= c <= "ヿ" for c in text):
        return "ja"
    if any("가" <= c <= "힯" for c in text):
        return "ko"
    if any("一" <= c <= "鿿" for c in text):
        return "zh"
    return ""


def _listen(draft: str, audio: Path, language: str, job: Progress) -> dict[str, Any]:
    with _turn:
        path = _fetch(job)
        if draft in _stopped:
            raise Stopped()
        from faster_whisper import WhisperModel

        job.phase, job.done, job.note = "load", 0.0, ""
        model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=THREADS)
        samples = decode(audio, RATE, 1).ravel().astype(np.float32)
        seconds = samples.size / RATE
        job.phase = "listen"
        segments, info = model.transcribe(
            samples,
            language=language or None,
            beam_size=5,
            word_timestamps=True,
            # Each part heard on its own: a line heard wrong isn't carried into the next.
            condition_on_previous_text=False,
            # Singing over music is not what a speech detector expects: it would cut words off.
            vad_filter=False,
            # Words "heard" in a long instrumental part are dropped.
            hallucination_silence_threshold=2.0,
        )
        words = []
        for segment in segments:
            if draft in _stopped:
                raise Stopped()
            job.done = min(1.0, segment.end / max(seconds, 1e-6))
            if any(phantom.replace(" ", "").lower() in segment.text.replace(" ", "").lower() for phantom in PHANTOMS):
                continue
            words += [[round(w.start, 2), round(w.end, 2), w.word.strip(), round(w.probability, 3)] for w in segment.words or [] if w.word.strip()]
        del model
        return {"model": MODEL, "language": info.language, "seconds": round(seconds, 2), "words": words, "at": int(time.time())}


async def hear(draft: str, language: str = "", told: Callable[[Progress], Awaitable[None]] | None = None, again: bool = False) -> dict[str, Any]:
    """Listens to the take (or gives back what was heard before); ``told`` hears how far it is."""
    before = None if again else heard(draft)
    if before and before.get("model") == MODEL:
        return before
    audio = drafts.audio_path(draft)
    if audio is None:
        raise FileNotFoundError("this take is gone")
    if draft in _busy:
        raise RuntimeError("this song is being listened to already")
    _busy.add(draft)
    _stopped.discard(draft)
    job = Progress()
    try:
        work = asyncio.ensure_future(asyncio.to_thread(_listen, draft, audio, language, job))
        while not work.done():
            await asyncio.wait({work}, timeout=0.5)
            if told is not None and not work.done():
                await told(job)
        found = work.result()
    finally:
        _busy.discard(draft)
        _stopped.discard(draft)
    audio.with_name(HEARD).write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    return found
