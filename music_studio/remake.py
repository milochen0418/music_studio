"""Changing a recording that exists. What can be done without knowing its notes: find its tempo and
key, take its strongest stretch on whole bars, change speed, pitch and tone, put it in a room, lay new
drums under it, and make the ends meet so a game can loop it. The AI Hub's model decides how
(``producer.plan_for``); this does it, with numpy and ffmpeg.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from pathlib import Path

import numpy as np

from music_studio.composer import STYLES
from music_studio.composer import render
from music_studio.composer.render import MP3_RATE
from music_studio.composer.synth import SR
from music_studio.composer.theory import NAMES

MAX_SECONDS = 15 * 60  # read of a recording at most
ANALYSE_RATE = 11025
HOP = 256
LEAD = 1.0  # seconds kept each side of the loop in the file, so a decoder's padding can't reach it
BEATS = ("none", "synthwave", "dnb", "house", "techno", "rock", "lofi")
TONES = {
    "none": "",
    "bright": "bass=g=2:f=90,treble=g=4:f=5000",
    "dark": "lowpass=f=3200,bass=g=3:f=100",
    "warm": "treble=g=-3:f=4000,bass=g=3:f=120",
    "radio": "highpass=f=350,lowpass=f=3400",
}
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclasses.dataclass(frozen=True)
class Plan:
    title: str = ""
    speed: float = 1.0
    pitch: int = 0
    tone: str = "none"
    room: float = 0.1
    beat: str = "none"
    energy: float = 0.6


@dataclasses.dataclass(frozen=True)
class Analysis:
    seconds: float
    bpm: float
    sure: float  # 0 to 1: how clear the beat is
    beat: float  # seconds: a beat falls here
    key: str
    mode: str

    def facts(self) -> str:
        return f"{self.seconds:.0f} s long, about {self.bpm:.0f} BPM (beat {'clear' if self.sure > 0.3 else 'unclear'}), in {self.key} {self.mode}"


@dataclasses.dataclass
class Remade:
    audio: np.ndarray
    bpm: float
    key: str
    mode: str
    loop: tuple[float, float]
    plan: Plan

    @property
    def seconds(self) -> float:
        return self.audio.shape[0] / SR

    def save(self, path: Path) -> Path:
        pcm = (np.clip(self.audio, -1, 1) * 32767).astype("<i2").tobytes()
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0", "-b:a", MP3_RATE, str(path)]
        subprocess.run(cmd, input=pcm, check=True, capture_output=True)
        return path


def decode(path: Path, rate: int = SR, channels: int = 2, start: float = 0.0, seconds: float = MAX_SECONDS, filters: str = "") -> np.ndarray:
    """A recording as floats (``n × channels``)."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(path)]
    if filters:
        cmd += ["-af", filters]
    cmd += ["-f", "f32le", "-ar", str(rate), "-ac", str(channels), "pipe:1"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, "<f4").reshape(-1, channels).astype(np.float64)


def _onsets(mono: np.ndarray) -> np.ndarray:
    """How much new sound starts in each hop: the rise of the spectrum's bands."""
    window = np.hanning(HOP * 4)
    frames = (mono.size - window.size) // HOP
    if frames < 8:
        return np.zeros(8)
    index = np.arange(frames)[:, None] * HOP + np.arange(window.size)
    power = np.log1p(np.abs(np.fft.rfft(mono[index] * window, axis=1)) * 10)
    flux = np.maximum(0.0, np.diff(power, axis=0)).sum(axis=1)
    return flux - np.convolve(flux, np.ones(32) / 32, "same")


def analyse(path: Path) -> Analysis:
    mono = decode(path, ANALYSE_RATE, 1).ravel()
    seconds = mono.size / ANALYSE_RATE
    flux = np.maximum(0.0, _onsets(mono))
    frames_per_second = ANALYSE_RATE / HOP
    spectrum = np.abs(np.fft.rfft(flux - flux.mean(), flux.size * 2)) ** 2
    acf = np.fft.irfft(spectrum)[: flux.size]
    acf /= acf[0] or 1.0
    best, bpm = 0.0, 120.0
    for candidate in np.arange(70.0, 190.0, 0.25):
        lag = frames_per_second * 60 / candidate
        score = 0.0
        for multiple, weight in ((1, 1.0), (2, 0.6), (4, 0.4)):
            at = lag * multiple
            low = int(at)
            if low + 1 >= acf.size:
                continue
            score += weight * (acf[low] + (acf[low + 1] - acf[low]) * (at - low))
        score *= np.exp(-0.5 * (np.log2(candidate / 125) / 0.9) ** 2)  # most music lies near here
        if score > best:
            best, bpm = score, float(candidate)
    # The peaks far out pin the tempo down much finer than the first one can.
    fine, top = bpm, -1.0
    for candidate in np.arange(bpm - 2.0, bpm + 2.0, 0.02):
        lag = frames_per_second * 60 / candidate
        at = lag * np.arange(4, 65, 4)
        at = at[at < acf.size - 1]
        low = at.astype(int)
        score = float(np.sum(acf[low] + (acf[low + 1] - acf[low]) * (at - low)))
        if score > top:
            fine, top = float(candidate), score
    bpm = fine
    period = frames_per_second * 60 / bpm
    grid = np.arange(0, flux.size - 1, period)
    phases = np.linspace(0, period, 48, endpoint=False)
    strengths = [flux[(grid + p).astype(int).clip(0, flux.size - 1)].sum() for p in phases]
    beat = phases[int(np.argmax(strengths))] / frames_per_second

    size = 8192
    hop = ANALYSE_RATE
    chroma = np.zeros(12)
    freqs = np.fft.rfftfreq(size, 1 / ANALYSE_RATE)
    usable = (freqs > 80) & (freqs < 2000)
    classes = (np.round(12 * np.log2(freqs[usable] / 440)).astype(int) + 9) % 12
    for at in range(0, max(1, mono.size - size), hop):
        frame = mono[at : at + size]
        if frame.size < size:
            break
        np.add.at(chroma, classes, np.abs(np.fft.rfft(frame * np.hanning(size)))[usable])
    fits = [(float(np.corrcoef(chroma, np.roll(MAJOR, k))[0, 1]), k, "major") for k in range(12)]
    fits += [(float(np.corrcoef(chroma, np.roll(MINOR, k))[0, 1]), k, "minor") for k in range(12)]
    _, tonic, mode = max(fits)
    return Analysis(seconds, bpm, float(np.clip(best / 1.2, 0, 1)), float(beat), NAMES[tonic], mode)


def _strongest(path: Path, a: Analysis, bar: float, bars: int) -> float:
    """Where the loudest ``bars`` bars start, on a bar line."""
    mono = decode(path, ANALYSE_RATE, 1).ravel()
    per_bar = int(bar * ANALYSE_RATE)
    first = int(a.beat * ANALYSE_RATE)
    if per_bar <= 0 or mono.size < per_bar * 2:
        return a.beat
    count = (mono.size - first) // per_bar
    energy = np.array([np.mean(mono[first + k * per_bar : first + (k + 1) * per_bar] ** 2) for k in range(count)])
    if count <= bars:
        return a.beat
    totals = np.convolve(energy, np.ones(bars), "valid")
    return a.beat + bar * int(np.argmax(totals))


def _stretch_filter(plan: Plan) -> str:
    """Speed and pitch as ffmpeg filters: Rubber Band if this ffmpeg has it."""
    if plan.speed == 1 and plan.pitch == 0:
        return ""
    try:
        listed = subprocess.run(["ffmpeg", "-v", "error", "-filters"], capture_output=True, text=True).stdout
    except OSError:
        listed = ""
    ratio = 2 ** (plan.pitch / 12)
    if " rubberband " in listed:
        return f"rubberband=tempo={plan.speed:.4f}:pitch={ratio:.5f}"
    # Without it: a resample shifts pitch and speed together, and atempo puts the speed right.
    tempo = plan.speed / ratio
    return f"asetrate={SR * ratio:.0f},aresample={SR},atempo={max(0.5, min(2.0, tempo)):.4f}"


def remake(path: Path, plan: Plan, bars: int, analysis: Analysis | None = None) -> Remade:
    a = analysis or analyse(path)
    if a.sure < 0.12:  # no steady beat to lay drums on
        plan = dataclasses.replace(plan, beat="none")
    bar = 240.0 / a.bpm
    bars = min(bars, max(4, int((a.seconds - a.beat) / bar) // 4 * 4))
    start = _strongest(path, a, bar, bars)
    filters = ",".join(f for f in (_stretch_filter(plan), TONES.get(plan.tone, "")) if f)
    new_bpm = a.bpm * plan.speed
    audio = decode(path, SR, 2, start, (bars + 2) * bar, filters)
    if audio.shape[0] < SR:
        raise ValueError("the recording is too short")
    size = min(audio.shape[0] - 1, int(bars * 240.0 / new_bpm * SR))
    join = min(int(240.0 / new_bpm * SR), audio.shape[0] - size)  # a bar, if there is one left
    head = audio[:size].copy()
    # The end flows into the start: the bar after the end fades out over the first bar.
    t = np.linspace(0, 1, join)[:, None]
    head[:join] = head[:join] * np.sin(t * np.pi / 2) + audio[size : size + join] * np.cos(t * np.pi / 2)
    if plan.room > 0:
        wet = render._convolve(np.concatenate([head, head[: int(render.ROOM_SECONDS * SR)]]), render._room())
        spill = wet[size:]
        wet = wet[:size]
        wet[: spill.shape[0]] += spill
        head = head + wet * plan.room
    if plan.beat != "none" and plan.beat in STYLES:
        # A fast style over a song heard at half its speed: twice the bars at twice the tempo.
        times = 2 if new_bpm * 1.5 < STYLES[plan.beat].bpm[0] else 1
        layer, kicks, _ = render.beat_layer(plan.beat, int(round(new_bpm * times)), bars * times, plan.energy)
        fit = np.linspace(0, layer.shape[0] - 1, size)
        grid = np.arange(layer.shape[0])
        drums = np.stack([np.interp(fit, grid, layer[:, c]) for c in (0, 1)], axis=1)
        scale = size / layer.shape[0]
        duck = render._duck(size, [int(k * scale) for k in kicks if k * scale < size], 0.3, 0.12)
        drums *= 10 ** (-3.0 / 20) * (np.sqrt(np.mean(head**2)) / max(np.sqrt(np.mean(drums**2)), 1e-6))
        head = head * duck[:, None] + drums
    loud = np.sqrt(np.mean(head**2)) or 1.0
    head = np.tanh(head * render.TARGET_RMS / loud * 1.12)
    head *= 0.97 / max(np.abs(head).max(), 1e-6)
    lead = int(LEAD * SR)
    fade = np.linspace(0, 1, lead)[:, None]
    out = np.concatenate([head[-lead:] * fade, head, head[:lead] * fade[::-1]])
    return Remade(out, new_bpm, _shifted(a.key, plan.pitch), a.mode, (LEAD, LEAD + size / SR), plan)


def _shifted(key: str, semitones: int) -> str:
    return NAMES[(NAMES.index(key) + semitones) % 12]


def can_run() -> bool:
    return shutil.which("ffmpeg") is not None


__all__ = ["Analysis", "BEATS", "Plan", "Remade", "TONES", "analyse", "can_run", "decode", "remake"]
