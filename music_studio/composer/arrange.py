"""Writes the parts: from a brief and a seed, every note and drum hit of a piece.

A piece is an intro, the body twice and an outro. The body's two passes are the same notes, so a
game can jump from the end of the second back to the start of the second and never be heard to:
what comes before both places is the same music (``Score.loop``). Time is in sixteenths.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from music_studio.composer import theory
from music_studio.composer.styles import STYLES, Brief, Style
from music_studio.composer.synth import PATCHES

STEPS = 16  # to a bar
INTRO = 4  # bars
OUTRO = 4
BAR_ROOTS = 36  # the bass lives from here up an octave

# A melody's rhythm over two bars: (step, length).
RHYTHMS: dict[str, list[tuple[int, int]]] = {
    "driving": [(0, 3), (3, 3), (6, 2), (8, 4), (12, 2), (14, 2), (16, 3), (19, 3), (22, 2), (24, 8)],
    "long": [(0, 8), (8, 4), (12, 4), (16, 8), (24, 8)],
    "bouncy": [(0, 2), (2, 2), (4, 2), (6, 2), (8, 2), (10, 2), (12, 4), (16, 2), (18, 2), (20, 2), (22, 2), (24, 8)],
    "sparse": [(0, 6), (8, 2), (10, 6), (24, 8)],
}


ARP_ORDERS = ([0, 1, 2, 3], [0, 2, 1, 3], [0, 1, 2, 3, 4, 3, 2, 1], [0, 2, 4, 2, 1, 3, 5, 3])


@dataclasses.dataclass(frozen=True)
class Note:
    part: str  # bass, chords, arp, lead
    patch: str
    step: int
    length: int
    pitch: int
    velocity: float = 1.0


@dataclasses.dataclass(frozen=True)
class Hit:
    drum: str  # kick, snare, hat, open, crash, riser
    step: int
    velocity: float = 1.0


@dataclasses.dataclass
class Score:
    bpm: int
    key: str
    mode: str
    style: str
    notes: list[Note]
    hits: list[Hit]
    bars: int  # the whole piece
    loop: tuple[int, int]  # steps: from the end of the second pass, jump back to its start
    sections: list[tuple[str, int]]  # (name, first bar)


@dataclasses.dataclass(frozen=True)
class Section:
    name: str
    bars: int
    chords: list[tuple[int, bool]]
    hats: bool = True
    arp: bool = True
    lead: bool = True
    open_hats: bool = False
    crash: bool = False
    riser: bool = False


def _body(brief: Brief, style: Style, verse: list, chorus: list) -> list[Section]:
    """The part that repeats: quieter first, opening up to the chorus. Bars are whole eighths of it."""
    eighth = max(1, brief.bars // 8)
    calm = brief.energy < 0.45
    if brief.bars <= 16:
        half = brief.bars // 2
        return [Section("verse", half, verse, arp=not calm), Section("chorus", half, chorus, open_hats=True, crash=style.crash, riser=False)]
    return [
        Section("verse", eighth * 2, verse, arp=False, lead=False),
        Section("verse", eighth * 2, verse, arp=not calm),
        Section("chorus", eighth * 2, chorus, open_hats=True, crash=style.crash),
        Section("chorus", eighth * 2, chorus, open_hats=True, crash=style.crash),
    ][: max(1, brief.bars // (eighth * 2))]


def _pattern_steps(pattern: str) -> list[tuple[int, str]]:
    return [(i, c) for i, c in enumerate(pattern[:STEPS]) if c != "."]


def _bass(section: Section, offset: int, style: Style, root: int, mode: str) -> list[Note]:
    notes = []
    hits = _pattern_steps(style.bass)
    for bar in range(section.bars):
        step, _ = section.chords[bar % len(section.chords)]
        low = BAR_ROOTS + (theory.degree(root, mode, step) - BAR_ROOTS) % 12
        for k, (at, mark) in enumerate(hits):
            until = hits[k + 1][0] if k + 1 < len(hits) else STEPS
            pitch = low + (12 if mark == "o" else 7 if mark == "5" else 0)
            notes.append(Note("bass", style.bass_patch, offset + bar * STEPS + at, max(1, until - at), pitch, 1.0 if mark == "x" else 0.85))
    return notes


def _chords(section: Section, offset: int, style: Style, root: int, mode: str, last: list[int] | None) -> tuple[list[Note], list[int] | None]:
    notes = []
    for bar in range(section.bars):
        step, seventh = section.chords[bar % len(section.chords)]
        voiced = theory.voice(theory.chord_tones(root, mode, step, seventh), 62, last)
        last = voiced
        at = offset + bar * STEPS
        if style.chord_patch == "power":  # a root and its fifth, low and heavy
            low = BAR_ROOTS + 12 + (theory.degree(root, mode, step) - BAR_ROOTS) % 12
            voiced = [low, low + 7, low + 12]
        if style.chord_rhythm == "hold":
            notes += [Note("chords", style.chord_patch, at, STEPS, p, 0.9) for p in voiced]
            continue
        hits = _pattern_steps(style.chord_rhythm)
        for k, (hit, mark) in enumerate(hits):
            until = hits[k + 1][0] if k + 1 < len(hits) else STEPS
            notes += [Note("chords", style.chord_patch, at + hit, max(1, until - hit), p, 1.0 if mark == "x" else 0.75) for p in voiced]
    return notes, last


def _arp(section: Section, offset: int, style: Style, root: int, mode: str, order: list[int]) -> list[Note]:
    if not style.arp or style.arp_patch not in PATCHES:
        return []
    notes = []
    gate = _pattern_steps(style.arp)
    for bar in range(section.bars):
        step, seventh = section.chords[bar % len(section.chords)]
        tones = theory.voice(theory.chord_tones(root, mode, step, seventh), 74)
        ladder = tones + [t + 12 for t in tones]
        for k, (at, _) in enumerate(gate):
            notes.append(Note("arp", style.arp_patch, offset + bar * STEPS + at, 2, ladder[order[(bar * len(gate) + k) % len(order)] % len(ladder)], 0.8 + 0.2 * (at % 4 == 0)))
    return notes


def _nearest(tones: list[int], pitch: int) -> int:
    pcs = {t % 12 for t in tones}
    return min((p for p in range(pitch - 7, pitch + 8) if p % 12 in pcs), key=lambda p: (abs(p - pitch), p))


def _scale(root: int, mode: str) -> list[int]:
    return [theory.degree(root, mode, s) for s in range(-21, 56)]


def _phrase(rng: np.random.Generator, rhythm: list[tuple[int, int]], bars: list[tuple[int, bool]], root: int, mode: str, start: int, end_on_root: bool, seeds: list[int] | None) -> list[tuple[int, int, int]]:
    """A two-bar phrase over two bars' chords: (step, length, pitch). Strong beats land on the chord,
    the rest walks along the scale."""
    scale = _scale(root, mode)
    pitch = start
    out = []
    going = 1 if rng.random() < 0.5 else -1
    for i, (step, length) in enumerate(rhythm):
        chord = bars[step // STEPS]
        tones = theory.chord_tones(root, mode, chord[0], chord[1])
        if seeds and i < len(seeds):
            pitch = theory.degree(root, mode, seeds[i]) + 12 * round((start - root) / 12)
        elif step % 8 == 0:
            pitch = _nearest(tones, pitch + going)
        else:
            here = min(range(len(scale)), key=lambda k: abs(scale[k] - pitch))
            move = int(rng.choice([1, 1, 2, -1])) * going
            pitch = scale[max(0, min(len(scale) - 1, here + move))]
            if rng.random() < 0.3:
                going = -going
        # A tune stays where a voice could sing it.
        while pitch > start + 12:
            pitch -= 12
        while pitch < start - 9:
            pitch += 12
        if pitch >= start + 9:
            going = -1
        if pitch <= start - 6:
            going = 1
        out.append((step, length, pitch))
    if end_on_root:
        step, length, pitch = out[-1]
        chord = bars[1]
        tones = theory.chord_tones(root, mode, chord[0], False)
        out[-1] = (step, length, _nearest(tones[:1] + tones[2:], pitch))
    return out


def _tune(section: Section, offset: int, style: Style, patch: str, root: int, mode: str, rng: np.random.Generator, height: int, motif: tuple[int, ...]) -> list[Note]:
    """Question, answer, the question again, an ending: the shape most tunes have."""
    rhythm = RHYTHMS.get(style.lead_rhythm, RHYTHMS["driving"])
    notes: list[Note] = []
    chords = section.chords
    pair = lambda bar: [chords[bar % len(chords)], chords[(bar + 1) % len(chords)]]  # noqa: E731
    question = _phrase(rng, rhythm, pair(0), root, mode, height, False, list(motif) or None)
    bar = 0
    turn = 0
    while bar < section.bars:
        chord_pair = pair(bar)
        if turn % 4 == 0:
            phrase = question
        elif turn % 4 == 2:  # the same tune, its strong notes moved onto the chord that's here now
            phrase = []
            for step, length, pitch in question:
                c = chord_pair[step // STEPS]
                moved = _nearest(theory.chord_tones(root, mode, c[0], c[1]), pitch) if step % 8 == 0 else pitch
                phrase.append((step, length, moved))
        else:
            phrase = _phrase(rng, rhythm, chord_pair, root, mode, question[-1][2], turn % 4 == 3, None)
        for step, length, pitch in phrase:
            notes.append(Note("lead", patch, offset + bar * STEPS + step, length, int(pitch), 0.9 + 0.1 * (step % 8 == 0)))
        bar += 2
        turn += 1
    return [n for n in notes if n.step < offset + section.bars * STEPS]


def _drums(section: Section, offset: int, style: Style, brief: Brief) -> list[Hit]:
    hits: list[Hit] = []
    busy = brief.energy > 0.8
    for bar in range(section.bars):
        at = offset + bar * STEPS
        hits += [Hit("kick", at + s, 1.0 if m == "x" else 0.75) for s, m in _pattern_steps(style.kick)]
        last = bar == section.bars - 1
        snares = _pattern_steps(style.snare)
        if last and "x" in style.snare:  # a fill into what comes next
            snares = [(s, m) for s, m in snares if s < 12] + [(12, "x"), (13, "o"), (14, "x"), (15, "x")]
        hits += [Hit("snare", at + s, 1.0 if m == "x" else 0.6) for s, m in snares]
        if section.hats:
            for s, m in _pattern_steps(style.hats):
                hits.append(Hit("hat", at + s, (0.8 if s % 4 == 0 else 1.0) * (1.0 if m == "x" else 0.7)))
            if busy:
                hits += [Hit("hat", at + s, 0.45) for s in range(1, STEPS, 2)]
            if section.open_hats:
                hits.append(Hit("open", at + 14, 0.8))
    if section.crash:
        hits.append(Hit("crash", offset, 1.0))
    return hits


def write(brief: Brief, seed: int) -> Score:
    style = STYLES[brief.style]
    rng = np.random.default_rng(seed)
    mode = brief.mode or style.mode
    root = theory.key_root(brief.key)
    verse = theory.parse_progression(brief.verse or style.verses[int(rng.integers(len(style.verses)))])
    chorus = theory.parse_progression(brief.chorus or style.choruses[int(rng.integers(len(style.choruses)))])
    low, high = style.bpm
    bpm = int(brief.bpm or round(low + (high - low) * brief.energy))
    body = _body(brief, style, verse, chorus)
    lead_patch = brief.lead or style.lead
    order = ARP_ORDERS[int(rng.integers(len(ARP_ORDERS)))]

    # One pass of the body, from step 0.
    notes: list[Note] = []
    hits: list[Hit] = []
    place = 0
    last = None
    height = {}
    for section in body:
        chord_notes, last = _chords(section, place, style, root, mode, last)
        notes += chord_notes
        notes += _bass(section, place, style, root, mode)
        if section.arp:
            notes += _arp(section, place, style, root, mode, order)
        if section.lead and lead_patch in PATCHES:
            start = 64 + (root - 4) % 12 + (5 if section.name == "chorus" else 0)  # E4 to D#5, a fourth up
            if section.name not in height:
                height[section.name] = int(rng.integers(1 << 30))
            tune_rng = np.random.default_rng([seed, height[section.name]])
            notes += _tune(section, place, style, lead_patch, root, mode, tune_rng, start, brief.motif if section.name == "verse" else ())
        hits += _drums(section, place, style, brief)
        place += section.bars * STEPS
    body_steps = place

    # The intro: the first chords, thinly, and a rise into the first beat.
    intro = Section("intro", INTRO, verse, hats=False, arp=False, lead=False)
    start_notes, _ = _chords(intro, 0, style, root, mode, None)
    pass_at = INTRO * STEPS
    notes_all = list(start_notes)
    hits_all: list[Hit] = [Hit("riser", 0, 0.9)]
    if style.hats.count("x") and brief.energy >= 0.45:
        hits_all += [Hit("hat", s, 0.5) for s in range(STEPS * 2, pass_at, 4)]
    second = pass_at + body_steps
    for offset in (pass_at, second):
        notes_all += [dataclasses.replace(n, step=n.step + offset) for n in notes]
        hits_all += [dataclasses.replace(h, step=h.step + offset) for h in hits]
    outro_at = second + body_steps
    hits_all.append(Hit("crash", outro_at, 0.9))
    hits_all.append(Hit("kick", outro_at, 1.0))
    ending = Section("outro", OUTRO, verse[:1], hats=False, arp=False, lead=False)
    ending_notes, _ = _chords(ending, outro_at, dataclasses.replace(style, chord_rhythm="hold"), root, mode, None)
    notes_all += ending_notes
    notes_all += [Note("bass", style.bass_patch, outro_at, STEPS * 2, BAR_ROOTS + (root - BAR_ROOTS) % 12, 0.9)]
    sections = [("intro", 0)]
    bar = INTRO
    for _pass in range(2):
        for section in body:
            sections.append((section.name, bar))
            bar += section.bars
    sections.append(("outro", bar))
    return Score(bpm, theory.NAMES[root], mode, brief.style, notes_all, hits_all, bar + OUTRO, (second, outro_at), sections)
