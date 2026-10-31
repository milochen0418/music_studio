"""Plays a score: every note into its part's bus, the kick pushing the rest down, echoes and a room
on what wants them, and a master that brings the whole to a steady loudness. Everything here is the
same each time, and each operation looks only at what came before by less than a pass of the body,
so the two passes come out identical to the sample once their first moments are over."""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import numpy as np

from music_studio.composer import arrange, synth
from music_studio.composer.arrange import Score
from music_studio.composer.styles import STYLES, Brief
from music_studio.composer.synth import SR

ROOM_SECONDS = 2.4
TARGET_RMS = 10 ** (-13.5 / 20)  # about as loud as music is on a streaming service
MP3_RATE = "192k"
PART_GAIN = {"bass": 0.9, "chords": 0.8, "arp": 0.42, "lead": 0.55}


@dataclasses.dataclass
class Piece:
    audio: np.ndarray  # n × 2, float, -1 to 1
    score: Score
    brief: Brief
    seed: int

    @property
    def seconds(self) -> float:
        return self.audio.shape[0] / SR

    @property
    def step_samples(self) -> int:
        return _step_samples(self.score.bpm)

    @property
    def loop(self) -> tuple[float, float]:
        """Seconds: a player that reaches the second, jumps to the first."""
        a, b = self.score.loop
        return a * self.step_samples / SR, b * self.step_samples / SR

    def save(self, path: Path) -> Path:
        """As MP3 (or anything else ffmpeg knows from the file's name)."""
        pcm = (np.clip(self.audio, -1, 1) * 32767).astype("<i2").tobytes()
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0", "-b:a", MP3_RATE, str(path)]
        subprocess.run(cmd, input=pcm, check=True, capture_output=True)
        return path


def _step_samples(bpm: int) -> int:
    # A whole number of samples to a sixteenth: the two passes must lie exactly a whole body apart.
    return int(round(60 / bpm / 4 * SR))


def _riser(seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    noise = synth.band(np.random.default_rng(21).uniform(-1, 1, n), 800, 12000)
    t = np.linspace(0, 1, n)
    swell = t**3 * 0.32
    return noise * swell


def _room() -> np.ndarray:
    """A room's echo as a stereo noise that dies away and darkens."""
    n = int(ROOM_SECONDS * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(33)
    ir = rng.standard_normal((n, 2)) * np.exp(-t * 3.1)[:, None]
    spectrum = np.fft.rfft(ir, axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    spectrum *= (np.clip((f - 180) / 180, 0, 1) * np.exp(-f / 5200))[:, None]
    ir = np.fft.irfft(spectrum, n, axis=0)
    return ir / np.sqrt(np.sum(ir**2, axis=0, keepdims=True)) * 1.1


def _convolve(signal: np.ndarray, ir: np.ndarray) -> np.ndarray:
    n = signal.shape[0]
    size = int(2 ** np.ceil(np.log2(n + ir.shape[0])))
    wet = np.fft.irfft(np.fft.rfft(signal, size, axis=0) * np.fft.rfft(ir, size, axis=0), size, axis=0)
    return wet[:n]


def _echo(signal: np.ndarray, delay: int, feedback: float, repeats: int = 4) -> np.ndarray:
    """Quiet copies later, swapping ears each time."""
    out = np.zeros_like(signal)
    for k in range(1, repeats + 1):
        shift = delay * k
        if shift >= signal.shape[0]:
            break
        copy = signal[:-shift] * feedback**k
        if k % 2:
            copy = copy[:, ::-1]
        out[shift:] += copy
    return out


def _duck(n: int, kicks: list[int], depth: float, recover: float) -> np.ndarray:
    """A gain that drops at each kick and comes back: the pulse of dance music."""
    gain = np.ones(n)
    if not depth:
        return gain
    shape = 1 - depth * np.exp(-np.arange(int(recover * 5 * SR)) / (recover * SR))
    for at in kicks:
        end = min(n, at + shape.size)
        gain[at:end] = np.minimum(gain[at:end], shape[: end - at])
    return gain


def _high_pass(signal: np.ndarray, cutoff: float) -> np.ndarray:
    """Takes away the lowest rumble by subtracting a slow average of what came before. It looks only
    back: a filter that also looked ahead would let the outro's first beat leak in before it."""
    n = signal.shape[0]
    rate = 2 * np.pi * cutoff / SR
    kernel = rate * np.exp(-rate * np.arange(min(n, int(8 / rate))))
    size = int(2 ** np.ceil(np.log2(n + kernel.size)))
    slow = np.fft.irfft(np.fft.rfft(signal, size, axis=0) * np.fft.rfft(kernel, size)[:, None], size, axis=0)[:n]
    return signal - slow


def perform(score: Score) -> np.ndarray:
    style = STYLES[score.style]
    step = _step_samples(score.bpm)
    swing = int(style.swing * step)
    length = score.bars * arrange.STEPS * step + int(ROOM_SECONDS * SR)
    buses = {name: np.zeros((length, 2)) for name in PART_GAIN}
    drums = np.zeros((length, 2))
    room_send = np.zeros((length, 2))
    kit = synth.drum_kit(style.drum_kit)
    at_sample = lambda s: s * step + (swing if s % 2 else 0)  # noqa: E731

    cache: dict[tuple, np.ndarray] = {}
    for n in score.notes:
        key = (n.patch, n.pitch, n.length)
        sound = cache.get(key)
        if sound is None:
            sound = cache[key] = synth.note(n.patch, n.pitch, n.length * step / SR)
        at = at_sample(n.step)
        end = min(length, at + sound.shape[0])
        buses[n.part][at:end] += sound[: end - at] * n.velocity

    pans = {"kick": 0.0, "snare": 0.0, "hat": 0.18, "open": -0.14, "crash": 0.1}
    kicks = []
    riser_seconds = arrange.INTRO * arrange.STEPS * step / SR
    for hit in score.hits:
        at = at_sample(hit.step)
        if hit.drum == "riser":
            sound = _riser(riser_seconds)
        else:
            sound = kit[hit.drum]
        if hit.drum == "kick":
            kicks.append(at)
        pan = pans.get(hit.drum, 0.0)
        end = min(length, at + sound.size)
        mono = sound[: end - at] * hit.velocity
        drums[at:end, 0] += mono * (1 - pan)
        drums[at:end, 1] += mono * (1 + pan)
        if hit.drum in ("snare", "open"):
            room_send[at:end, 0] += mono * 0.5
            room_send[at:end, 1] += mono * 0.5

    duck = _duck(length, kicks, style.sidechain, 60 / score.bpm / 3.2)
    soft_duck = 1 - (1 - duck) * 0.55
    mix = drums * 0.9
    echo_time = step * 3
    for part, bus in buses.items():
        bus *= PART_GAIN[part]
        if part in ("arp", "lead"):
            bus = bus + _echo(bus, echo_time, 0.36)
        if part in ("chords", "arp", "lead"):
            room_send += bus * (0.8 if part == "chords" else 1.0)
        mix += bus * (duck if part in ("chords", "arp") else soft_duck)[:, None]
    mix += _convolve(room_send, _room()) * style.reverb
    return _high_pass(mix, 32)


def master(mix: np.ndarray, score: Score) -> np.ndarray:
    step = _step_samples(score.bpm)
    end = score.bars * arrange.STEPS * step
    fade_from = end - 2 * arrange.STEPS * step
    fade = np.ones(mix.shape[0])
    fade[fade_from:end] = np.linspace(1, 0, end - fade_from) ** 1.5
    fade[end:] = 0
    body = mix[score.loop[0] * step : score.loop[1] * step]
    loud = np.sqrt(np.mean(body**2)) or 1.0
    # A soft limiter: nothing in it remembers, so it keeps the passes equal.
    out = np.tanh(mix * TARGET_RMS / loud * 1.12)
    out *= (0.97 / max(np.abs(out).max(), 1e-6))
    return (out * fade[:, None])[:end]


def beat_layer(style_name: str, bpm: int, bars: int, energy: float) -> tuple[np.ndarray, list[int], int]:
    """A style's drums alone, ``bars`` long and wrapped round so it repeats exactly, for laying under
    a song: (stereo samples, where the kicks fall, samples to a sixteenth)."""
    style = STYLES[style_name]
    step = _step_samples(bpm)
    brief = Brief(style=style_name, energy=energy)
    section = arrange.Section("verse", bars, [(0, False)], open_hats=energy > 0.6)
    hits = arrange._drums(section, 0, style, brief)
    kit = synth.drum_kit(style.drum_kit)
    size = bars * arrange.STEPS * step
    out = np.zeros(size + SR)
    kicks = []
    for hit in hits:
        at = hit.step * step
        sound = kit[hit.drum]
        out[at : at + sound.size] += sound * hit.velocity
        if hit.drum == "kick":
            kicks.append(at)
    tail = out.size - size
    out[:tail] += out[size:]
    mono = out[:size] * 0.9
    return np.stack([mono, mono], axis=1), kicks, step


def compose(brief: Brief, seed: int = 1) -> Piece:
    """The piece for a brief. The same brief and seed give the same samples."""
    score = arrange.write(brief, seed)
    return Piece(master(perform(score), score), score, brief, seed)
