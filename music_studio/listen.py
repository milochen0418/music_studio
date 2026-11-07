"""The studio listens to a take: Whisper hears the words sung in it and when, and
:func:`music_studio.lyrics.align` matches them with the lyrics, so each line shows when it is sung.

Whisper runs in this app on the CPU (faster-whisper, int8), as English Chat's subtitles do: no
network but for the model's first download, no hub, no key. The model (``MUSIC_STUDIO_WHISPER``,
by default large-v3-turbo, about 1.6 GB) is downloaded into the app's data folder the first time it
is needed and loaded only while a song is heard, so its memory is given back. What was heard is
kept with the take (``heard.json``): lyrics changed later are matched again without listening.

A recording about to be remade is listened to the same way (:func:`hear_recording`), so the music
engine can sing its words again; what was heard is kept in the data folder by the file
(``heard/``), and :func:`sung` tells whether anybody sings in it at all.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import io
import json
import logging
import os
import re
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
PHANTOMS = (
    "优优独播剧场", "YoYo Television", "字幕由", "字幕志愿者", "请不吝点赞", "明镜与点点", "Amara.org", "Thanks for watching", "Thank you for watching",
    "Suscríbete al canal", "Subtítulos realizados", "ご視聴ありがとうございました", "시청해 주셔서 감사합니다",
    "詞曲", "词曲", "作詞", "作词", "編曲", "编曲",  # credits, as on a song's subtitles
)
# Where in a song its language is told, as parts of its length: its first half minute (all that
# Whisper's own guess hears) is often music alone, and then it guesses wildly.
LANGUAGE_AT = (0.3, 0.5, 0.7)
MIN_LINE = 1.0  # seconds: shorter "lines" heard in music are mostly Whisper's own inventions
# Seconds with no line heard, in a recording where singing was heard, that are listened to once more:
# when unsure, Whisper samples, and each listen misses different lines (a whole verse at times).
GAP = 12.0
FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
SIZE_MB = 1600  # what the default model downloads, said before it starts

_turn = threading.Lock()  # one song at a time: it takes the cores it is given
_stopped: set[str] = set()
_busy: set[str] = set()


class Stopped(Exception):
    """The person stopped it."""


@dataclasses.dataclass
class Progress:
    phase: str = "wait"  # wait (for another song), download, load, language, listen, again (the gaps)
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


def _language(model: Any, samples: np.ndarray) -> str:
    """The language sung: the one most likely over half-minute windows across the song."""
    window = 30 * RATE
    total: dict[str, float] = {}
    for part in LANGUAGE_AT:
        start = int(max(0, min(samples.size - window, part * samples.size - window / 2)))
        _, _, likely = model.detect_language(audio=samples[start : start + window])
        for name, chance in likely:
            total[name] = total.get(name, 0.0) + chance
    return max(total, key=lambda name: total[name]) if total else ""


def _take_in(segments: Any, key: str, job: Progress, place: Callable[[float], float], words: list, lines: list) -> Any:
    """The words and lines of what Whisper heard, as it hears them; its info."""
    for segment in segments:
        if key in _stopped:
            raise Stopped()
        job.done = min(1.0, place(segment.end))
        if any(phantom.replace(" ", "").lower() in segment.text.replace(" ", "").lower() for phantom in PHANTOMS):
            continue
        words += [[round(w.start, 2), round(w.end, 2), w.word.strip(), round(w.probability, 3)] for w in segment.words or [] if w.word.strip()]
        if segment.text.strip():
            lines.append([round(segment.start, 2), round(segment.end, 2), segment.text.strip()])


def gaps(lines: list, seconds: float) -> list[tuple[float, float]]:
    """The stretches of at least ``GAP`` seconds where no line was heard."""
    edges = [0.0] + [t for row in sorted(lines, key=lambda row: row[0]) for t in (float(row[0]), float(row[1]))] + [seconds]
    return [(edges[k], edges[k + 1]) for k in range(0, len(edges) - 1, 2) if edges[k + 1] - edges[k] >= GAP]


def _merged(words: list, lines: list, more_words: list, more: list) -> tuple[list, list]:
    """The lines heard a second time put in where nothing was heard the first, with their words."""
    added = [row for row in more if all(min(row[1], b) - max(row[0], a) <= 0.5 * (row[1] - row[0]) for a, b, _ in lines)]
    inside = [w for w in more_words if any(a <= (w[0] + w[1]) / 2 <= b for a, b, _ in added)]
    return sorted(words + inside, key=lambda w: w[0]), sorted(lines + added, key=lambda row: row[0])


def _listen(key: str, audio: Path, language: str, job: Progress, again: bool = False) -> dict[str, Any]:
    with _turn:
        path = _fetch(job)
        if key in _stopped:
            raise Stopped()
        from faster_whisper import WhisperModel

        job.phase, job.done, job.note = "load", 0.0, ""
        model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=THREADS)
        samples = decode(audio, RATE, 1).ravel().astype(np.float32)
        seconds = samples.size / RATE
        if not language:
            job.phase = "language"
            language = _language(model, samples)
        job.phase = "listen"
        options: dict[str, Any] = {
            "language": language or None,
            "beam_size": 5,
            "word_timestamps": True,
            # Each part heard on its own: a line heard wrong isn't carried into the next.
            "condition_on_previous_text": False,
            # Singing over music is not what a speech detector expects: it would cut words off.
            "vad_filter": False,
            # Words "heard" in a long instrumental part are dropped.
            "hallucination_silence_threshold": 2.0,
        }
        segments, info = model.transcribe(samples, **options)
        words: list = []
        lines: list = []
        _take_in(segments, key, job, lambda at: at / max(seconds, 1e-6), words, lines)
        missed = gaps(lines, seconds) if again and sung({"lines": lines, "seconds": seconds}) else []
        if missed:
            job.phase, job.done = "again", 0.0
            total = sum(b - a for a, b in missed)

            def place(at: float) -> float:
                return sum(min(b, max(a, at)) - a for a, b in missed) / total

            more_words: list = []
            more: list = []
            segments, _ = model.transcribe(samples, clip_timestamps=[t for gap in missed for t in gap], **options)
            _take_in(segments, key, job, place, more_words, more)
            words, lines = _merged(words, lines, more_words, more)
        del model
        return {"model": MODEL, "language": info.language, "seconds": round(seconds, 2), "words": words, "lines": lines, "at": int(time.time())}


async def _hear(
    key: str, audio: Path, kept: Path, language: str, told: Callable[[Progress], Awaitable[None]] | None, again: bool, gaps_again: bool = False
) -> dict[str, Any]:
    """What was heard in ``audio`` (kept in ``kept``), listening to it if nobody has yet (``again``:
    even so); ``gaps_again`` listens once more where a song's first listen heard nothing."""
    if not again:
        try:
            before = json.loads(kept.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            before = None
        if before and before.get("model") == MODEL:
            return before
    if key in _busy:
        raise RuntimeError("this song is being listened to already")
    _busy.add(key)
    _stopped.discard(key)
    job = Progress()
    try:
        work = asyncio.ensure_future(asyncio.to_thread(_listen, key, audio, language, job, gaps_again))
        while not work.done():
            await asyncio.wait({work}, timeout=0.5)
            if told is not None and not work.done():
                await told(job)
        found = work.result()
    finally:
        _busy.discard(key)
        _stopped.discard(key)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    return found


async def hear(draft: str, language: str = "", told: Callable[[Progress], Awaitable[None]] | None = None, again: bool = False) -> dict[str, Any]:
    """Listens to the take (or gives back what was heard before); ``told`` hears how far it is."""
    audio = drafts.audio_path(draft)
    if audio is None:
        raise FileNotFoundError("this take is gone")
    return await _hear(draft, audio, audio.with_name(HEARD), language, told, again)


async def hear_recording(path: Path, language: str = "", told: Callable[[Progress], Awaitable[None]] | None = None) -> dict[str, Any]:
    """Listens to a recording about to be remade (or gives back what was heard in it before), for
    the words sung in it: ``lines`` of [start, end, text] beside the words. ``language`` is the
    one it is sung in, if known ("" lets Whisper tell)."""
    stat = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()[:20]
    return await _hear(f"recording-{key}", path, drafts.data_dir() / "heard" / f"{key}.json", language, told, False, gaps_again=True)


def sung(found: dict[str, Any] | None) -> list[tuple[float, float, str]]:
    """The lines sung in what was heard, as (start, end, text); none when nobody sings in it. In
    music without singing Whisper still "hears" a short phrase now and then ("Thank you.", "Let's
    go."), so it counts as sung only with several different lines over a fair part of it."""
    lines = []
    for row in (found or {}).get("lines") or []:
        start, end, text = float(row[0]), float(row[1]), str(row[2]).strip()
        if end - start >= MIN_LINE and text:
            lines.append((start, end, text))
    different = {re.sub(r"\W+", "", text.lower()) for _, _, text in lines}
    singing = sum(end - start for start, end, _ in lines)
    if len(different) < 4 or singing < max(15.0, 0.08 * float((found or {}).get("seconds") or 0)):
        return []
    return lines
