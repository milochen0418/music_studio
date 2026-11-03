"""A take as a music video for YouTube: the cover blurred and drifting slowly behind the cover
itself, the title, bars or a wave that move with the music, and the lyrics at their times, as long
as the song. The MP4 is 1080p, H.264 High with AAC, its index at the front so it plays while it
downloads; it is kept in the take's folder as ``video.mp4``, and what it was made with as
``video.json``.

FFmpeg moves and joins the pictures and encodes. The still pictures and the lyric lines are drawn
here with Pillow, since an FFmpeg built without libass or freetype (Homebrew's) can't write text.
What moves with the music is measured here with numpy, one row of levels a frame (the bars'
heights, or the wave's outline), and FFmpeg turns each row into the picture by comparing it with a
ramp (``lut2``). Nothing but the song is needed: no model, no network.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import io
import json
import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from music_studio import art, drafts
from music_studio.lyrics import Line, shown
from music_studio.remake import decode

logger = logging.getLogger(__name__)

W, H, FPS = 1920, 1080, 30
LOOKS = ("bars", "wave")
RATE = 22050  # the levels are measured at this rate
BARS = 64
BOX = (960, 200)  # where the bars or the wave move
WAVE_SECONDS = 3.0  # the wave shows this much of the song, ending now
DRIFT = 1.12  # the background is this much bigger than the frame, to drift across it
COVER = 560
BAND = 250  # the lyrics' strip at the bottom
CRF = 18  # YouTube encodes it again: give it plenty to work from
VIDEO = "video.mp4"
SETTINGS = "video.json"
FAMILIES = ("Noto Sans CJK TC", "Noto Sans TC", "Source Han Sans TC", "PingFang TC", "Heiti TC", "Microsoft JhengHei")

_running: dict[str, asyncio.subprocess.Process | None] = {}
_stopped: set[str] = set()


class Stopped(Exception):
    """The person stopped it."""


@dataclasses.dataclass
class Spec:
    title: str
    artist: str
    about: str = ""  # the small line under the artist: style, tempo, key
    look: str = "bars"
    motion: bool = True
    lines: list[Line] = dataclasses.field(default_factory=list)
    lyrics: bool = True  # show the lines

    @property
    def sung(self) -> list[Line]:
        """The lines the video shows: not those the AI listened for and didn't hear sung."""
        return [line for line in self.lines if line.text and line.heard is not False] if self.lyrics else []


# ------------------------------------------------------------------ what moves with the music


def frames_for(seconds: float) -> int:
    return int(np.ceil(seconds * FPS))


def bars(mono: np.ndarray, frames: int) -> np.ndarray:
    """How high each of the ``BARS`` bars stands in each frame, 0 to 250: the sound's strength in
    bands from 40 Hz to 11 kHz, each band against its own loudest moments, so all of them move. A
    bar jumps up at once and falls back slowly, as on a hi-fi."""
    size = 2048
    bins = np.round(np.geomspace(40, RATE / 2, BARS + 1) / (RATE / size)).astype(int)
    for k in range(1, bins.size):
        bins[k] = max(bins[k], bins[k - 1] + 1)  # a bin at least to each band
    bins = np.minimum(bins, size // 2 + 1)
    window = np.hanning(size)
    padded = np.concatenate([np.zeros(size), mono, np.zeros(size)])
    centres = ((np.arange(frames) + 0.5) * RATE / FPS).astype(int) + size
    reach = np.arange(size) - size // 2
    power = np.zeros((frames, BARS))
    for first in range(0, frames, 512):
        chunk = padded[centres[first : first + 512, None] + reach[None, :]]
        spectrum = np.abs(np.fft.rfft(chunk * window, axis=1)) ** 2
        total = np.concatenate([np.zeros((chunk.shape[0], 1)), np.cumsum(spectrum, axis=1)], axis=1)
        power[first : first + chunk.shape[0]] = (total[:, bins[1:]] - total[:, bins[:-1]]) / (bins[1:] - bins[:-1])
    level = 10 * np.log10(power + 1e-12)
    top = np.percentile(level, 99, axis=0)
    top = np.maximum(top, top.max() - 30)  # a band that is nearly silent stays low
    height = np.clip((level - (top - 36)) / 36, 0, 1) ** 1.5
    height[:, 1:-1] = height[:, 1:-1] * 0.6 + (height[:, :-2] + height[:, 2:]) * 0.2
    fallen = np.empty_like(height)
    last = np.zeros(BARS)
    for k in range(frames):
        last = np.maximum(height[k], last - 0.045)
        fallen[k] = last
    return np.round(fallen * 250).astype(np.uint8)


def wave(mono: np.ndarray, frames: int) -> np.ndarray:
    """The outline of the last ``WAVE_SECONDS`` of sound, newest on the right: a value a column of
    the box, 0 to 250."""
    width = BOX[0]
    step = RATE * WAVE_SECONDS / width  # samples a column
    starts = np.unique(np.minimum((np.arange(int(mono.size / step) + 1) * step).astype(int), max(0, mono.size - 1)))
    counts = np.diff(np.append(starts, mono.size)).clip(1)
    strength = np.sqrt(np.add.reduceat(mono.astype(np.float64) ** 2, starts) / counts)
    strength = np.convolve(strength, np.ones(4) / 4, "same")  # an outline, not every wiggle
    strength /= np.percentile(strength, 99.5) or 1.0
    strength = np.concatenate([np.zeros(width), np.clip(strength, 0, 1) ** 0.8])
    ends = np.minimum(((np.arange(frames) + 1) / FPS * RATE / step).astype(int) + width, strength.size)
    return np.round(strength[ends[:, None] - width + np.arange(width)[None, :]] * 250).astype(np.uint8)


def levels(mono: np.ndarray, seconds: float, look: str) -> np.ndarray:
    """A row a frame, for ``look`` (``bars`` or ``wave``)."""
    frames = frames_for(seconds)
    return wave(mono, frames) if look == "wave" else bars(mono, frames)


# ------------------------------------------------------------------ fonts and words


@functools.cache
def _font_file(bold: bool) -> tuple[str, int] | None:
    """A font with Chinese in it, found through fontconfig (a Mac has PingFang, Debian Noto Sans CJK
    from ``fonts-noto-cjk``): its file and its index in a collection."""
    want = 200 if bold else 80
    try:
        listed = subprocess.run(["fc-list", "-f", "%{file}|%{index}|%{family}|%{weight}\n", ":lang=zh-tw"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        listed = ""
    best: tuple[Any, ...] | None = None
    for row in listed.splitlines():
        parts = row.split("|")
        if len(parts) != 4:
            continue
        path, index, family, weight = parts
        names = [name.strip() for name in family.split(",")]
        rank = min((FAMILIES.index(name) for name in names if name in FAMILIES), default=len(FAMILIES))
        if rank == len(FAMILIES) and not any(word in family for word in ("Sans", "Hei", "Gothic", "黑")):
            rank += 1
        weights = re.findall(r"\d+", weight)
        place = (rank, abs(int(weights[0]) - want) if weights else 99, path, int(index or 0))
        best = place if best is None or place < best else best
    if best is not None:
        return best[2], best[3]
    try:  # no Chinese anywhere: letters at least
        path, index = subprocess.run(["fc-match", "-f", "%{file}|%{index}", f"sans-serif:weight={want}"], capture_output=True, text=True, timeout=30).stdout.split("|")
        return path, int(index or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


@functools.cache
def font(size: int, bold: bool = False) -> Any:
    found = _font_file(bold)
    if found is not None:
        try:
            return ImageFont.truetype(found[0], size, index=found[1])
        except OSError:
            logger.warning("Can't read the font %s", found)
    return ImageFont.load_default(size)


def wrap(text: str, face: Any, width: int, most: int) -> list[str]:
    """``text`` in at most ``most`` lines of ``width`` pixels; what doesn't fit ends in …. Words in
    letters stay whole; Chinese may break after any character."""
    lines, now = [], ""
    for token in re.findall(r"[A-Za-zÀ-ÿ0-9'’\-]+\s*|\s+|.", " ".join(str(text or "").split())):
        if now and face.getlength(now + token.rstrip()) > width:
            lines.append(now.rstrip())
            now = token.lstrip()
        else:
            now += token
    if now.strip():
        lines.append(now.rstrip())
    if len(lines) > most:
        lines = lines[:most]
        last = lines[-1]
        while last and face.getlength(last + "…") > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _fitting(text: str, width: int, sizes: tuple[int, ...], bold: bool, most: int) -> tuple[Any, list[str]]:
    """The biggest of ``sizes`` that holds ``text`` in ``most`` lines (else the smallest, cut)."""
    for size in sizes:
        lines = wrap(text, font(size, bold), width, 99)
        if len(lines) <= most:
            return font(size, bold), lines
    return font(sizes[-1], bold), wrap(text, font(sizes[-1], bold), width, most)


def _shadowed(canvas: Image.Image, write: Callable[[ImageDraw.ImageDraw, tuple[int, int, int, int]], None], blur: float, strength: int) -> None:
    """Writes on ``canvas`` over a soft shadow of the same letters, so they read on any background."""
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    write(ImageDraw.Draw(shadow), (0, 0, 0, strength))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))
    write(ImageDraw.Draw(canvas), (255, 255, 255, 255))


# ------------------------------------------------------------------ the still pictures


def _rgb(colour: str) -> np.ndarray:
    return np.array([int(colour[k : k + 2], 16) for k in (1, 3, 5)], dtype=np.float32)


def _top(spec: Spec) -> int:
    """The cover's top edge: higher when the lyrics need the bottom."""
    return 140 if spec.sung else (H - COVER) // 2


def box_place(spec: Spec) -> tuple[int, int]:
    """Where the bars' or the wave's box goes: under the words, its foot level with the cover's."""
    return 800, _top(spec) + COVER - BOX[1]


def background(cover: Image.Image, motion: bool) -> Image.Image:
    """The cover filling the frame, blurred and darkened towards the edges, with a little grain so
    the encoder keeps the dark gradients smooth; bigger than the frame when it is to drift."""
    w, h = (int(W * DRIFT) // 2 * 2, int(H * DRIFT) // 2 * 2) if motion else (W, H)
    small = cover.convert("RGB").resize((240, 240), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(14))
    top = (w - h) // 2
    picture = np.asarray(small.resize((w, w), Image.Resampling.BICUBIC).crop((0, top, w, top + h)), dtype=np.float32)
    y = np.linspace(-1, 1, h)[:, None]
    x = np.linspace(-1, 1, w)[None, :]
    picture = picture * (0.62 - 0.3 * np.clip(x**2 * 0.55 + y**2 * 0.75, 0, 1))[:, :, None]
    picture += np.random.default_rng(7).normal(0, 1.2, (h, w))[:, :, None]
    return Image.fromarray(np.clip(picture, 0, 255).astype(np.uint8))


def layer(cover: Image.Image, spec: Spec) -> Image.Image:
    """What stays still in front of the background: the cover with its shadow, the title, who made
    it, the small line, a dark fade under the lyrics and the progress bar's track."""
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top = _top(spec)
    if spec.sung:
        start = H - BAND - 120
        alpha = np.zeros((H, W), dtype=np.uint8)
        alpha[start:] = (np.linspace(0, 1, H - start) ** 1.4 * 150).astype(np.uint8)[:, None]
        canvas.putalpha(Image.fromarray(alpha))
    left = 160
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((left, top + 22, left + COVER, top + COVER + 22), 30, fill=(0, 0, 0, 170))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(28)))
    mask = Image.new("L", (COVER, COVER), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, COVER - 1, COVER - 1), 28, fill=255)
    picture = cover.convert("RGBA").resize((COVER, COVER), Image.Resampling.LANCZOS)
    picture.putalpha(mask)
    canvas.alpha_composite(picture, (left, top))

    x, width = 800, W - 800 - 160
    title_face, title_lines = _fitting(spec.title or "—", width, (80, 72, 64, 56), True, 2)
    artist_face, about_face = font(40), font(30)

    def words(draw: ImageDraw.ImageDraw, colour: tuple[int, int, int, int]) -> None:
        at = top + 30
        for line in title_lines:
            draw.text((x, at), line, font=title_face, fill=colour)
            at += int(title_face.size * 1.22)
        at += 14
        if spec.artist:
            draw.text((x, at), wrap(spec.artist, artist_face, width, 1)[0], font=artist_face, fill=colour[:3] + (int(colour[3] * 0.86),))
            at += 58
        if spec.about:
            draw.text((x, at), wrap(spec.about, about_face, width, 1)[0], font=about_face, fill=colour[:3] + (int(colour[3] * 0.58),))

    _shadowed(canvas, words, 8, 150)
    ImageDraw.Draw(canvas).rectangle((0, H - 6, W, H), fill=(255, 255, 255, 38))
    return canvas


def ramp(look: str) -> Image.Image:
    """What each level is compared with, a pixel at a time: the height in the box for the bars (with
    gaps between them that no level reaches), the distance from the middle for the wave."""
    w, h = BOX
    if look == "wave":
        return Image.fromarray(np.repeat((np.abs(np.linspace(-1, 1, h)) * 250)[:, None], w, axis=1).astype(np.uint8), "L")
    picture = np.repeat(np.linspace(250, 0, h)[:, None], w, axis=1)
    column = w // BARS
    picture[:, np.arange(w) % column >= column - max(3, column // 4)] = 255
    return Image.fromarray(picture.astype(np.uint8), "L")


def paint(ink: str) -> Image.Image:
    """What the bars or the wave are filled with: the cover's ink, paler towards the top."""
    w, h = BOX
    base = _rgb(ink)
    rows = base + (255 - base) * 0.55 * np.linspace(1, 0, h)[:, None]
    return Image.fromarray(np.repeat(rows[:, None, :], w, axis=1).astype(np.uint8), "RGB")


def fade() -> Image.Image:
    """The wave fades in from the left, where it is oldest."""
    w, h = BOX
    return Image.fromarray(np.repeat((np.clip(np.linspace(0, 1, w) / 0.35, 0, 1) * 255)[None, :], h, axis=0).astype(np.uint8), "L")


def lyric_card(now: str, coming: str) -> Image.Image:
    """The bottom strip at one moment: the line being sung, and the next one, dimmed."""
    card = Image.new("RGBA", (W, BAND), (0, 0, 0, 0))
    width = W - 280
    face, lines = _fitting(now, width, (64, 58, 52, 46), True, 2) if now else (font(64, True), [])
    small = font(38)
    later = wrap(coming, small, width, 1) if coming else []
    step = int(face.size * 1.18)
    middle = 92 if len(lines) < 2 else 72

    def words(draw: ImageDraw.ImageDraw, colour: tuple[int, int, int, int]) -> None:
        for k, line in enumerate(lines):
            draw.text((W // 2, middle + (k - (len(lines) - 1) / 2) * step), line, font=face, fill=colour, anchor="mm")
        if later:
            draw.text((W // 2, 198), later[0], font=small, fill=colour[:3] + (int(colour[3] * 0.5),), anchor="mm")

    _shadowed(card, words, 7, 210)
    return card


def cover_picture(take: dict[str, Any], mono: np.ndarray | None) -> Image.Image:
    """The take's cover drawn again at the size the video shows it, so it stays sharp."""
    if mono is not None and mono.size:
        return Image.open(io.BytesIO(art.cover(mono[:, None], art.cover_style(take), COVER))).convert("RGB")
    path = drafts.cover_path(take.get("id") or "")
    return Image.open(path).convert("RGB") if path is not None else Image.new("RGB", (COVER, COVER))


# ------------------------------------------------------------------ the video


def cues(lines: list[Line], seconds: float, folder: Path) -> Path:
    """The lyric strips, as a list FFmpeg's concat reader plays: a picture and how long it stays."""
    timeline, at = [], 0.0
    for start, end, now, coming in shown(lines, seconds):
        if start > at + 0.01:
            timeline.append((at, start, "", ""))
        timeline.append((max(at, start), end, now, coming))
        at = max(at, end)
    if at < seconds:
        timeline.append((at, seconds, "", ""))
    made: dict[tuple[str, str], str] = {}
    rows = ["ffconcat version 1.0"]
    name = ""
    for start, end, now, coming in timeline:
        if end - start < 0.005:
            continue
        name = made.get((now, coming), "")
        if not name:
            name = made[(now, coming)] = f"cue{len(made):03d}.png"
            lyric_card(now, coming).save(folder / name, compress_level=1)
        rows += [f"file '{name}'", f"duration {end - start:.3f}"]
    rows.append(f"file '{name}'")  # the reader wants the last picture once more
    path = folder / "lyrics.ffconcat"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def prepare(take: dict[str, Any], audio: Path, spec: Spec, folder: Path) -> tuple[float, str]:
    """Everything FFmpeg reads, into ``folder``: (the song's seconds, the colour of its ink)."""
    mono = decode(audio, RATE, 1).ravel()
    seconds = mono.size / RATE
    if seconds < 1:
        raise ValueError("this take is too short for a video")
    picture = cover_picture(take, mono)
    ink = art.colours(art.cover_style(take))[1]
    # Stored, not compressed: FFmpeg reads the stills again for every frame.
    background(picture, spec.motion).save(folder / "background.png", compress_level=0)
    layer(picture, spec).save(folder / "layer.png", compress_level=0)
    levels(mono, seconds, spec.look).tofile(folder / "levels.raw")
    ramp(spec.look).save(folder / "ramp.png")
    paint(ink).save(folder / "paint.png")
    fade().save(folder / "fade.png")
    if spec.sung:
        cues(spec.sung, seconds, folder)
    return seconds, ink


def command(folder: Path, audio: Path, spec: Spec, seconds: float, ink: str, out: Path, frames: int = 0) -> list[str]:
    """FFmpeg's command for the video from the pictures in ``folder`` (``frames``: only that many)."""
    inputs: list[str] = []
    length = f"{seconds:.3f}"

    def add(*args: str) -> int:
        inputs.extend(args)
        return inputs.count("-i") - 1

    def still(name: str) -> int:
        # Every input ends with the song: Debian's FFmpeg 5.1 runs on for ever after the output's
        # -t when an input never ends.
        return add("-loop", "1", "-framerate", str(FPS), "-t", length, "-i", str(folder / name))

    back, front, ramp_in, paint_in, fade_in = still("background.png"), still("layer.png"), still("ramp.png"), still("paint.png"), still("fade.png")
    sound = add("-i", str(audio))
    data = add("-f", "rawvideo", "-pix_fmt", "gray", "-video_size", f"{BOX[0] if spec.look == 'wave' else BARS}x1", "-framerate", str(FPS), "-i", str(folder / "levels.raw"))
    bar = add("-f", "lavfi", "-i", f"color=c=0x{ink.lstrip('#')}:s={W}x6:r={FPS}:d={length}")
    x, y = box_place(spec)
    # A slow drift round the middle that never reaches the edges: a few pixels a second.
    drift = f"crop={W}:{H}:x='(iw-ow)/2*(1+sin(2*PI*t/47))':y='(ih-oh)/2*(1+sin(2*PI*t/31+1.3))'," if spec.motion else ""
    graph = [
        f"[{back}:v]{drift}format=gbrp[bg]",
        f"[{data}:v]scale={BOX[0]}:{BOX[1]}:flags=neighbor,format=gray[lv]",
        f"[{ramp_in}:v]format=gray[rp]",
        "[lv][rp]lut2=c0='if(gt(x,y),255,0)'[cut]",
    ]
    if spec.look == "wave":
        graph += [f"[{fade_in}:v]format=gray[fd]", "[cut][fd]blend=all_mode=multiply[mask]"]
    else:
        graph += ["[cut]null[mask]", f"[{fade_in}:v]nullsink"]
    graph += [
        f"[{paint_in}:v]format=rgba[pt]",
        "[pt][mask]alphamerge[vis]",
        f"[bg][{front}:v]overlay=0:0:format=gbrp[s1]",
        f"[s1][vis]overlay={x}:{y}:format=gbrp[s2]",
    ]
    last = "s2"
    if spec.sung:
        words = add("-f", "concat", "-safe", "0", "-i", str(folder / "lyrics.ffconcat"))
        graph.append(f"[s2][{words}:v]overlay=0:{H - BAND - 20}:format=gbrp[s3]")
        last = "s3"
    graph.append(f"[{last}][{bar}:v]overlay=x='-w+w*t/{seconds:.3f}':y=H-6:format=gbrp:eval=frame,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[v]")
    return [
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-v", "error", "-progress", "pipe:1",
        *inputs,
        "-filter_complex", ";".join(graph),
        "-map", "[v]", "-map", f"{sound}:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(CRF), "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-g", str(FPS // 2), "-bf", "2", "-flags", "+cgop",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
        "-c:a", "aac", "-b:a", "384k", "-ac", "2",
        *(["-frames:v", str(frames)] if frames else ["-t", length]),
        "-movflags", "+faststart",
        str(out),
    ]


# ------------------------------------------------------------------ making it


def path(draft: str) -> Path | None:
    """The take's finished video."""
    audio = drafts.audio_path(draft)
    found = audio.with_name(VIDEO) if audio is not None else None
    return found if found is not None and found.is_file() else None


def settings(draft: str) -> dict[str, Any] | None:
    """What the take's video was made with, and when."""
    audio = drafts.audio_path(draft)
    if audio is None or path(draft) is None:
        return None
    try:
        return json.loads(audio.with_name(SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def busy(draft: str) -> bool:
    return draft in _running


def stop(draft: str) -> None:
    """Stops the video being made for ``draft``."""
    if draft in _running:
        _stopped.add(draft)
        process = _running.get(draft)
        if process is not None and process.returncode is None:
            process.kill()


async def render(draft: str, spec: Spec, progress: Callable[[float], Awaitable[None]] | None = None) -> dict[str, Any]:
    """Makes the take's video and says what it was made with (``video.json``). ``progress`` hears
    how far it is, 0 to 1. Raises :class:`Stopped` when :func:`stop` was called."""
    take, audio = drafts.info(draft), drafts.audio_path(draft)
    if take is None or audio is None:
        raise FileNotFoundError("this take is gone")
    if draft in _running:
        raise RuntimeError("this video is being made already")
    _running[draft] = None
    _stopped.discard(draft)
    part = audio.with_name("video.part.mp4")
    process: asyncio.subprocess.Process | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="music-video-") as tmp:
            folder = Path(tmp)
            seconds, ink = await asyncio.to_thread(prepare, take, audio, spec, folder)
            if draft in _stopped:
                raise Stopped()
            process = await asyncio.create_subprocess_exec(
                *command(folder, audio, spec, seconds, ink, part), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _running[draft] = process
            errors = asyncio.create_task(process.stderr.read())  # type: ignore[union-attr]

            async def follow() -> int:
                told = 0.0
                async for raw in process.stdout:  # type: ignore[union-attr]
                    key, _, value = raw.decode(errors="replace").strip().partition("=")
                    if key == "out_time_us" and value.isdigit() and progress is not None and time.monotonic() - told > 0.5:
                        told = time.monotonic()
                        await progress(min(1.0, int(value) / 1e6 / seconds))
                return await process.wait()

            try:
                code = await asyncio.wait_for(follow(), timeout=max(600.0, seconds * 10))
            except TimeoutError:
                raise RuntimeError("FFmpeg took far too long and was stopped") from None
            problem = (await errors).decode(errors="replace").strip()
        if draft in _stopped:
            raise Stopped()
        if code != 0:
            raise RuntimeError("FFmpeg: " + (problem.splitlines() or ["stopped"])[-1][:300])
        made = {
            "title": spec.title,
            "artist": spec.artist,
            "about": spec.about,
            "look": spec.look,
            "motion": spec.motion,
            "lyrics": spec.lyrics,
            "lines": [[line.at, line.text, line.end, line.heard] for line in spec.lines],
            "seconds": round(seconds, 2),
            "bytes": part.stat().st_size,
            "made": int(time.time()),
        }
        part.replace(audio.with_name(VIDEO))
        audio.with_name(SETTINGS).write_text(json.dumps(made, ensure_ascii=False), encoding="utf-8")
        return made
    finally:
        if process is not None and process.returncode is None:
            process.kill()  # the page went away, or something above failed
        part.unlink(missing_ok=True)
        _running.pop(draft, None)
        _stopped.discard(draft)
