"""The instruments, made from sums of sine waves. A sawtooth built from its harmonics has none above
what a sample can hold, so nothing folds back as a whistle, and making a note a little duller over
time is just fading its upper harmonics. Every note is a short numpy array, kept and reused.

The drums are a falling sine (kicks), noise cut to a band (hats, snares) or both.
"""

from __future__ import annotations

import dataclasses
from typing import Callable

import numpy as np

SR = 44100
TWO_PI = 2 * np.pi


def hz(pitch: float) -> float:
    return 440.0 * 2 ** ((pitch - 69) / 12)


saw = lambda k: 1.0 / k  # noqa: E731
square = lambda k: (1.0 / k) if k % 2 else 0.0  # noqa: E731
triangle = lambda k: (1.0 / (k * k)) if k % 2 else 0.0  # noqa: E731
sine = lambda k: 1.0 if k == 1 else 0.0  # noqa: E731


def pulse(width: float) -> Callable[[int], float]:
    return lambda k: abs(np.sin(np.pi * k * width)) / k


@dataclasses.dataclass(frozen=True)
class Patch:
    shape: Callable[[int], float] = saw
    top: int = 40  # harmonics at most
    voices: tuple[float, ...] = (0.0,)  # detunes in cents, each voice one more wave per ear
    spread: float = 0.0  # 0 centre .. 1 the voices wide apart
    attack: float = 0.005
    decay: float = 0.1
    sustain: float = 0.8
    release: float = 0.08
    dull: float = 0.0  # upper harmonics fade by this, per harmonic, per second
    tilt: float = 0.0  # and start this much lower, per harmonic (a low-pass)
    sub: float = 0.0  # a sine an octave under
    drive: float = 0.0  # 0 clean .. overdriven
    vibrato: float = 0.0  # cents, after a moment
    fm: tuple[float, float, float] = ()  # type: ignore[assignment]  # ratio, depth, depth's fade per second
    gain: float = 1.0


UNISON = (-11.0, -4.0, 5.0, 12.0)

PATCHES: dict[str, Patch] = {
    "lead_saw": Patch(saw, 28, (-6.0, 6.0), 0.5, 0.008, 0.2, 0.75, 0.14, dull=0.35, tilt=0.03, vibrato=9, gain=0.62),
    "lead_square": Patch(pulse(0.25), 18, (0.0,), 0, 0.002, 0.05, 0.75, 0.03, vibrato=12, gain=0.5),
    "lead_brass": Patch(saw, 22, (-5.0, 5.0), 0.3, 0.05, 0.25, 0.8, 0.14, tilt=0.09, vibrato=7, gain=0.7),
    "lead_pluck": Patch(saw, 24, (-4.0, 4.0), 0.3, 0.002, 0.35, 0.08, 0.16, dull=1.6, gain=0.9),
    "lead_soft": Patch(triangle, 9, (-3.0, 3.0), 0.3, 0.02, 0.4, 0.55, 0.28, vibrato=6, gain=0.9),
    "lead_reed": Patch(square, 21, (-4.0, 4.0), 0.2, 0.03, 0.2, 0.8, 0.1, tilt=0.07, vibrato=20, gain=0.6),
    "pad_warm": Patch(saw, 18, UNISON, 1.0, 0.09, 0.4, 0.8, 0.45, tilt=0.14, gain=0.26),
    "pad_air": Patch(saw, 14, UNISON, 1.0, 0.7, 0.8, 0.8, 1.0, tilt=0.22, gain=0.3),
    "strings": Patch(saw, 20, UNISON, 1.0, 0.22, 0.5, 0.85, 0.4, tilt=0.13, vibrato=8, gain=0.27),
    "strings_short": Patch(saw, 16, (-6.0, 6.0), 0.7, 0.012, 0.12, 0.25, 0.09, tilt=0.12, gain=0.5),
    "stab": Patch(saw, 26, UNISON, 0.9, 0.002, 0.16, 0.0, 0.12, dull=2.2, gain=0.42),
    "power": Patch(saw, 24, (-7.0, 7.0), 0.8, 0.003, 0.2, 0.7, 0.05, tilt=0.03, drive=3.2, gain=0.3),
    "chip_chord": Patch(pulse(0.5), 13, (0.0,), 0, 0.002, 0.06, 0.4, 0.02, gain=0.2),
    "epiano": Patch(lambda k: 1.0 / k**1.7, 10, (-2.0, 2.0), 0.4, 0.003, 1.0, 0.0, 0.35, dull=0.9, gain=0.5),
    "arp_pluck": Patch(saw, 22, (-5.0, 5.0), 0.6, 0.002, 0.18, 0.0, 0.1, dull=2.8, gain=0.5),
    "arp_bell": Patch(sine, 1, (-3.0, 3.0), 0.5, 0.002, 0.45, 0.0, 0.3, fm=(3.5, 2.2, 7.0), gain=0.34),
    "chip_arp": Patch(pulse(0.125), 16, (0.0,), 0, 0.001, 0.05, 0.3, 0.015, gain=0.26),
    "marimba": Patch(sine, 1, (0.0,), 0, 0.001, 0.26, 0.0, 0.1, fm=(4.0, 1.6, 22.0), gain=0.75),
    "oud": Patch(saw, 20, (-3.0, 3.0), 0.4, 0.001, 0.32, 0.0, 0.12, dull=1.5, tilt=0.03, gain=0.6),
    "bass_saw": Patch(saw, 14, (-3.0, 3.0), 0.0, 0.003, 0.12, 0.55, 0.05, tilt=0.11, sub=0.6, drive=0.8, gain=0.62),
    "bass_reese": Patch(saw, 12, (-16.0, 16.0), 0.0, 0.01, 0.3, 0.9, 0.08, tilt=0.15, sub=0.9, drive=1.2, gain=0.6),
    "bass_tri": Patch(triangle, 9, (0.0,), 0, 0.001, 0.05, 0.85, 0.02, gain=0.62),
    "bass_pick": Patch(saw, 12, (0.0,), 0, 0.002, 0.16, 0.45, 0.05, tilt=0.13, sub=0.4, drive=0.5, gain=0.72),
    "bass_rumble": Patch(sine, 1, (0.0,), 0, 0.004, 0.12, 0.3, 0.05, drive=1.4, sub=0.0, gain=0.8),
    "bass_soft": Patch(triangle, 7, (0.0,), 0, 0.012, 0.3, 0.55, 0.1, gain=0.8),
    "bass_cello": Patch(saw, 14, (-4.0, 4.0), 0.2, 0.05, 0.4, 0.75, 0.25, tilt=0.16, sub=0.3, gain=0.6),
}


def _envelope(p: Patch, held: int, total: int) -> np.ndarray:
    t = np.arange(total) / SR
    env = np.minimum(1.0, t / max(p.attack, 1e-4))
    falling = p.sustain + (1 - p.sustain) * np.exp(-np.maximum(0.0, t - p.attack) / max(p.decay, 1e-3))
    env = env * falling
    level = env[min(held, total - 1)]
    after = t[held:] - t[held] if held < total else np.empty(0)
    if after.size:
        env[held:] = level * np.exp(-after * 5.0 / max(p.release, 1e-3))
    return env


def _voice(p: Patch, freq: float, total: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(total) / SR
    wobble = 0.0
    if p.vibrato:
        depth = np.minimum(1.0, t / 0.35) * p.vibrato / 1200 * np.log(2)
        wobble = np.cumsum(depth * np.sin(TWO_PI * 5.3 * t)) * freq / SR
    if p.fm:
        ratio, depth, fade = p.fm
        index = depth * np.exp(-fade * t)
        return np.sin(TWO_PI * freq * t + index * np.sin(TWO_PI * freq * ratio * t) + rng.uniform(0, TWO_PI))
    out = np.zeros(total)
    for k in range(1, min(p.top, int(SR * 0.45 / freq)) + 1):
        a = p.shape(k)
        if a < 1e-4:
            continue
        a *= np.exp(-p.tilt * (k - 1))
        wave = np.sin(TWO_PI * k * (freq * t + wobble) + rng.uniform(0, TWO_PI))
        out += a * (wave * np.exp(-p.dull * (k - 1) * t) if p.dull else wave)
    return out


def note(patch: str, pitch: int, held_seconds: float, velocity: float = 1.0) -> np.ndarray:
    """One note as stereo samples (``n × 2``), its release included."""
    p = PATCHES[patch]
    held = int(held_seconds * SR)
    total = held + int(p.release * SR) + 16
    freq = hz(pitch)
    # The same note always sounds the same: a loop must repeat to the sample.
    rng = np.random.default_rng([sum(map(ord, patch)), pitch])
    left = np.zeros(total)
    right = np.zeros(total)
    voices = p.voices
    for i, cents in enumerate(voices):
        wave = _voice(p, freq * 2 ** (cents / 1200), total, rng)
        side = (i / (len(voices) - 1) * 2 - 1) * p.spread if len(voices) > 1 else 0.0
        left += wave * (1 - side) * 0.5
        right += wave * (1 + side) * 0.5
    scale = 1.0 / np.sqrt(len(voices))
    left *= scale
    right *= scale
    if p.sub:
        sub = np.sin(TWO_PI * freq * 0.5 * np.arange(total) / SR) * p.sub * 0.5
        left += sub
        right += sub
    env = _envelope(p, held, total)
    stereo = np.stack([left, right], axis=1) * env[:, None]
    if p.drive:
        stereo = np.tanh(stereo * (1 + p.drive)) / np.tanh(1 + p.drive)
    return stereo * p.gain * velocity


# ------------------------------------------------------------ drums


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-1, 1, n)


def band(signal: np.ndarray, low: float, high: float) -> np.ndarray:
    """Only what lies between two frequencies (by Fourier transform: one-shots are short)."""
    spectrum = np.fft.rfft(signal)
    f = np.fft.rfftfreq(signal.size, 1 / SR)
    gain = np.clip((f - low * 0.7) / max(low * 0.3, 1), 0, 1) * np.clip((high * 1.3 - f) / (high * 0.3), 0, 1)
    return np.fft.irfft(spectrum * gain, signal.size)


def _sweep(start: float, end: float, fall: float, n: int) -> np.ndarray:
    t = np.arange(n) / SR
    return np.sin(TWO_PI * np.cumsum(end + (start - end) * np.exp(-t * fall)) / SR)


def _kick(start: float, end: float, fall: float, seconds: float, decay: float, click: float, drive: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    body = _sweep(start, end, fall, n) * np.exp(-t * decay)
    hit = band(_noise(n, 1), 1500, 7000) * np.exp(-t * 320) * click
    return np.tanh((body + hit) * (1 + drive)) * 0.92


def _snare(tone: float, noise: float, seconds: float, low: float, high: float, decay: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    body = (_sweep(tone * 1.5, tone, 60, n) + 0.5 * _sweep(tone * 2.2, tone * 1.6, 60, n)) * np.exp(-t * 26)
    hiss = band(_noise(n, 2), low, high) * np.exp(-t * decay)
    return (body * 0.5 + hiss * noise) * 0.7


def _hat(seed: int, seconds: float, decay: float, low: float = 7000) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    return band(_noise(n, seed), low, 16000) * np.exp(-t * decay) * 0.55


def _taiko(pitch: float, seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    body = _sweep(pitch * 1.7, pitch, 26, n) * np.exp(-t * 7)
    skin = band(_noise(n, 3), 200, 1500) * np.exp(-t * 55) * 0.5
    return np.tanh((body + skin) * 1.6) * 0.9


def _chip(seconds: float, decay: float, seed: int) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    # An old sound chip's noise: the same value held for a while.
    held = np.repeat(_noise(n // 12 + 2, seed), 12)[:n]
    return held * np.exp(-t * decay) * 0.4


def _crash() -> np.ndarray:
    n = int(2.4 * SR)
    t = np.arange(n) / SR
    return band(_noise(n, 5), 3000, 15000) * np.exp(-t * 2.2) * 0.34


KITS = {
    "punch": lambda: {"kick": _kick(170, 49, 34, 0.42, 7.5, 0.5, 1.1), "snare": _snare(190, 0.85, 0.32, 1200, 9000, 17), "hat": _hat(7, 0.09, 62), "open": _hat(8, 0.34, 11)},
    "break": lambda: {"kick": _kick(210, 56, 46, 0.3, 11, 0.8, 1.4), "snare": _snare(215, 1.05, 0.26, 1500, 10000, 21), "hat": _hat(9, 0.06, 90, 8000), "open": _hat(10, 0.24, 16)},
    "rock": lambda: {"kick": _kick(150, 58, 40, 0.3, 11, 0.9, 0.7), "snare": _snare(180, 1.0, 0.36, 900, 8000, 13), "hat": _hat(11, 0.1, 42, 5500), "open": _hat(12, 0.5, 6, 4500)},
    "soft": lambda: {"kick": _kick(120, 52, 30, 0.3, 11, 0.12, 0.15), "snare": _snare(170, 0.45, 0.22, 900, 5000, 26), "hat": _hat(13, 0.05, 95, 6000) * 0.6, "open": _hat(14, 0.2, 18, 6000) * 0.6},
    "chip": lambda: {"kick": _kick(190, 70, 70, 0.1, 30, 0, 0) * 0.7 + _chip(0.1, 45, 15), "snare": _chip(0.14, 26, 16) * 1.5, "hat": _chip(0.03, 150, 17), "open": _chip(0.12, 26, 18)},
    "taiko": lambda: {"kick": _taiko(62, 1.0), "snare": _taiko(118, 0.6) * 0.75, "hat": _hat(19, 0.05, 80, 4000) * 0.5, "open": _hat(20, 0.3, 12, 4000) * 0.5},
}


def drum_kit(name: str) -> dict[str, np.ndarray]:
    """The kit's one-shots, mono."""
    return {**KITS[name](), "crash": _crash()}
