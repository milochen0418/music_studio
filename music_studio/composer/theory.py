"""Notes, scales and chords. A pitch is a MIDI number (60 is middle C)."""

from __future__ import annotations

import re

NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
SCALES = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "harmonic": (0, 2, 3, 5, 7, 8, 11),  # harmonic minor
    "hijaz": (0, 1, 4, 5, 7, 8, 10),  # the desert's scale: a flat second, a major third
}
ROMAN = {"i": 0, "ii": 1, "iii": 2, "iv": 3, "v": 4, "vi": 5, "vii": 6}


def key_root(name: str) -> int:
    """The pitch class of a key's name (0 to 11); C for anything else."""
    name = FLATS.get(name.strip().capitalize(), name.strip().capitalize())
    return NAMES.index(name) if name in NAMES else 0


def degree(root: int, mode: str, step: int) -> int:
    """The pitch of scale step ``step`` (0 is the root), any number of octaves away."""
    scale = SCALES[mode]
    return root + scale[step % 7] + 12 * (step // 7)


def parse_chord(symbol: str) -> tuple[int, bool]:
    """A roman numeral as (scale step, wants a seventh): ``VI`` -> (5, False), ``iv7`` -> (3, True).
    Which third a chord gets comes from the scale, so any numeral stays in the key."""
    m = re.fullmatch(r"([ivIV]+)(7?)", symbol.strip())
    if not m or m.group(1).lower() not in ROMAN:
        raise ValueError(f"not a chord: {symbol!r}")
    return ROMAN[m.group(1).lower()], bool(m.group(2))


def parse_progression(text: str) -> list[tuple[int, bool]]:
    return [parse_chord(s) for s in re.split(r"[\s,\-–]+", text.strip()) if s]


def chord_tones(root: int, mode: str, step: int, seventh: bool) -> list[int]:
    """The chord on scale step ``step``, in close position from the root's octave."""
    tones = [degree(root, mode, step), degree(root, mode, step + 2), degree(root, mode, step + 4)]
    if seventh:
        tones.append(degree(root, mode, step + 6))
    return tones


def voice(tones: list[int], around: int, last: list[int] | None = None) -> list[int]:
    """The chord's notes moved by octaves to lie round pitch ``around``, each near where the last
    chord's notes were (voice leading: chords that don't jump)."""
    best: list[int] = []
    best_cost = float("inf")
    for shift in range(len(tones)):
        voiced = sorted(t + 12 * (1 if i < shift else 0) for i, t in enumerate(sorted(tones)))
        for octave in range(-4, 5):
            candidate = [t + 12 * octave for t in voiced]
            middle = sum(candidate) / len(candidate)
            cost = abs(middle - around) * 0.6
            if last:
                cost += sum(min(abs(c - p) for p in last) for c in candidate)
            if cost < best_cost:
                best, best_cost = candidate, cost
    return best
