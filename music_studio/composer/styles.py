"""How each kind of music is played. A drum pattern is 16 steps a bar, a character a step:
``x`` a full hit, ``o`` a softer one, ``.`` none. A bass or arp pattern is the same steps."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Brief:
    """What a piece should be. ``composer.compose`` turns this into music; anything left empty
    takes the style's own choice."""

    style: str = "synthwave"
    title: str = ""
    bpm: int = 0
    key: str = "A"
    mode: str = ""
    verse: str = ""  # chords of the first part, e.g. "i VI III VII"
    chorus: str = ""  # of the second part
    energy: float = 0.7  # 0 calm .. 1 flat out
    lead: str = ""  # which instrument sings: see synth.PATCHES ("none": no melody)
    motif: tuple[int, ...] = ()  # the tune's first notes, as scale steps (0 the root)
    bars: int = 32  # bars of the part that repeats; 8 to 64, whole eights
    mood: str = ""  # free words, kept with the piece


@dataclasses.dataclass(frozen=True)
class Style:
    bpm: tuple[int, int]
    mode: str
    verses: tuple[str, ...]
    choruses: tuple[str, ...]
    kick: str
    snare: str
    hats: str
    bass: str  # pattern; 'x' the root, 'o' the octave up, '5' the fifth
    bass_patch: str
    chord_patch: str
    chord_rhythm: str  # "hold": a chord a bar; else a 16-step pattern of stabs
    arp: str  # 16-step gate; "" none
    arp_patch: str
    lead: str
    drum_kit: str = "punch"
    swing: float = 0.0  # of a sixteenth, the late offbeats
    sidechain: float = 0.5  # how far the kick pushes the rest down
    reverb: float = 0.18
    lead_rhythm: str = "driving"  # melody.RHYTHMS
    crash: bool = True


STYLES: dict[str, Style] = {
    "synthwave": Style(
        (100, 126), "minor", ("i VI III VII", "i VII VI VII", "i iv VI V"), ("VI VII i i", "III VII VI VII"),
        "x...x...x...x...", "....x.......x...", "..x...x...x...x.", "x.x.x.x.x.x.x.ox", "bass_saw", "pad_warm", "hold", "x.xxx.xxx.xxx.xx", "arp_pluck", "lead_saw",
        sidechain=0.55, reverb=0.26,
    ),
    "dnb": Style(
        (168, 176), "minor", ("i VI VII i", "i iv VI VII"), ("VI III VII i", "iv VI VII i"),
        "x.........x.....", "....x.......x...", "x.x.x.x.x.x.x.x.", "x.......x..x....", "bass_reese", "pad_air", "hold", "x..x..x...x..x..", "arp_bell", "lead_saw",
        drum_kit="break", sidechain=0.3, reverb=0.2, lead_rhythm="long",
    ),
    "chiptune": Style(
        (132, 168), "major", ("I V vi IV", "vi IV I V", "I IV V IV"), ("IV V iii vi", "vi V IV V"),
        "x.....x.x.......", "....x.......x...", "x.x.x.x.x.x.x.x.", "x.xox.xox.xox.xo", "bass_tri", "chip_chord", "x.x.x.x.x.x.x.x.", "xxxxxxxxxxxxxxxx", "chip_arp", "lead_square",
        drum_kit="chip", sidechain=0.0, reverb=0.05, lead_rhythm="bouncy",
    ),
    "rock": Style(
        (136, 168), "minor", ("i VII VI VII", "i III VII VI"), ("VI VII i i", "III VII i i"),
        "x.....x.x.......", "....x.......x...", "x.x.x.x.x.x.x.x.", "x.x.x.x.x.x.x.x.", "bass_pick", "power", "x.x.x.x.x.x.x.x.", "", "arp_pluck", "lead_brass",
        drum_kit="rock", sidechain=0.0, reverb=0.16, lead_rhythm="driving",
    ),
    "house": Style(
        (122, 128), "minor", ("i VI III VII", "i iv i VII"), ("VI VII III i",),
        "x...x...x...x...", "....x.......x...", "..x...x...x...x.", "..x...x...x...x.", "bass_saw", "stab", "x..x..x...x..x..", "", "arp_pluck", "lead_pluck",
        sidechain=0.6, reverb=0.22, lead_rhythm="bouncy",
    ),
    "techno": Style(
        (128, 136), "phrygian", ("i i II i", "i i VII i"), ("i II VII i",),
        "x...x...x...x...", "....x.......x...", "..x...x...x...x.", "x.xx.xx.x.xx.xx.", "bass_rumble", "stab", "x..x..x...x.....", "x.x.x.xxx.x.x.xx", "arp_bell", "none",
        sidechain=0.65, reverb=0.3,
    ),
    "orchestral": Style(
        (92, 132), "harmonic", ("i VI III VII", "i iv V i", "i VI iv V"), ("VI III VII i", "iv i V i"),
        "x.....x...x.....", "................", "................", "x.......x.......", "bass_cello", "strings", "hold", "x.xxx.xxx.xxx.xx", "strings_short", "lead_brass",
        drum_kit="taiko", sidechain=0.0, reverb=0.4, lead_rhythm="long",
    ),
    "lofi": Style(
        (72, 88), "dorian", ("i7 iv7 VII7 III7", "ii7 V7 i7 i7"), ("VI7 v7 i7 i7",),
        "x.....x...x.....", "....x.......x...", "x.x.x.x.x.x.x.x.", "x.....x...x.....", "bass_soft", "epiano", "x.....x.........", "", "arp_pluck", "lead_soft",
        drum_kit="soft", swing=0.34, sidechain=0.2, reverb=0.2, lead_rhythm="sparse", crash=False,
    ),
    "ambient": Style(
        (62, 78), "major", ("I V vi IV", "vi IV I V"), ("IV I V vi",),
        "................", "................", "................", "x...............", "bass_soft", "pad_air", "hold", "x.....x.....x...", "arp_bell", "lead_soft",
        sidechain=0.0, reverb=0.55, lead_rhythm="sparse", crash=False,
    ),
    "tropical": Style(
        (102, 116), "major", ("vi IV I V", "I V vi IV"), ("IV V vi I",),
        "x...x...x...x...", "...o..o....o..o.", "..x...x...x...x.", "x..x..x...x.....", "bass_soft", "pad_warm", "hold", "x.xx.xx.x.xx.xx.", "marimba", "lead_pluck",
        drum_kit="soft", sidechain=0.45, reverb=0.25, lead_rhythm="bouncy",
    ),
    "desert": Style(
        (108, 128), "hijaz", ("i II i VII", "i VII VI II"), ("iv II i i",),
        "x..o..x...x.....", "....x.....o.x...", "x.x.x.x.x.x.x.x.", "x..x..x...x.....", "bass_pick", "pad_air", "hold", "x.xxx.xxx.xxx.xx", "oud", "lead_reed",
        drum_kit="taiko", sidechain=0.1, reverb=0.3, lead_rhythm="driving",
    ),
    "victory": Style(
        (120, 144), "major", ("I V vi IV", "I IV V I"), ("IV V I I",),
        "x...x...x...x...", "....x.......x...", "x.x.x.x.x.x.x.x.", "x.x.x.x.x.x.x.x.", "bass_saw", "strings", "hold", "x.xxx.xxx.xxx.xx", "arp_bell", "lead_brass",
        sidechain=0.2, reverb=0.3, lead_rhythm="long",
    ),
}
