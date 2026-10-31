import numpy as np
import pytest

from music_studio.composer import STYLES, Brief, compose
from music_studio.composer import arrange, theory
from music_studio.composer.synth import PATCHES, SR, note


@pytest.mark.parametrize("style", sorted(STYLES))
def test_every_style_plays_in_time_in_key_and_at_a_steady_level(style):
    piece = compose(Brief(style=style, key="D", energy=0.7, bars=8), seed=3)
    audio = piece.audio
    assert np.isfinite(audio).all() and audio.shape[1] == 2
    assert abs(audio).max() <= 1.0
    rms = 20 * np.log10(np.sqrt(np.mean(audio[len(audio) // 3 : len(audio) * 2 // 3] ** 2)))
    assert -24 < rms < -7, rms
    scale = set()
    root = theory.key_root("D")
    for step in range(7):
        scale.add(theory.degree(root, piece.score.mode, step) % 12)
    for n in piece.score.notes:
        if n.patch != "power":
            assert n.pitch % 12 in scale, (n.part, n.pitch)


@pytest.mark.parametrize("style", ["synthwave", "dnb", "lofi", "ambient"])
def test_the_loop_cannot_be_heard_the_two_places_are_the_same_sound(style):
    piece = compose(Brief(style=style, key="A", energy=0.7, bars=16), seed=5)
    step = piece.step_samples
    start, end = (s * step for s in piece.score.loop)
    assert abs(piece.loop[0] - start / SR) < 1e-9
    before_start = piece.audio[start - SR // 2 : start]
    before_end = piece.audio[end - SR // 2 : end]
    assert np.abs(before_start - before_end).max() < 2e-3


def test_same_brief_and_seed_same_piece_and_another_seed_another_tune():
    brief = Brief(style="house", key="C", energy=0.7, bars=8)
    a = compose(brief, 11)
    assert np.array_equal(a.audio, compose(brief, 11).audio)
    tune = lambda p: [n.pitch for n in p.score.notes if n.part == "lead"]  # noqa: E731
    assert tune(a) != tune(compose(brief, 12))


def test_a_melody_stays_singable_and_chords_do_not_jump():
    score = arrange.write(Brief(style="synthwave", key="A", energy=0.8), 9)
    lead = [n.pitch for n in score.notes if n.part == "lead"]
    assert lead and max(lead) - min(lead) <= 26 and max(lead) <= 92
    leaps = np.abs(np.diff(lead))
    assert np.mean(leaps) < 6, np.mean(leaps)


def test_a_motif_opens_the_tune():
    score = arrange.write(Brief(style="synthwave", key="A", mode="minor", energy=0.8, motif=(0, 2, 4)), 9)
    lead = [n for n in sorted(score.notes, key=lambda n: n.step) if n.part == "lead"]
    assert [n.pitch % 12 for n in lead[:3]] == [theory.degree(9, "minor", s) % 12 for s in (0, 2, 4)]


def test_an_instrument_has_nothing_above_what_a_sample_can_hold():
    wave = note("lead_saw", 96, 0.3)[:, 0]
    spectrum = np.abs(np.fft.rfft(wave * np.hanning(wave.size)))
    freqs = np.fft.rfftfreq(wave.size, 1 / SR)
    assert spectrum[freqs > 20500].max() < spectrum.max() * 1e-3


def test_every_patch_named_by_a_style_exists():
    for style in STYLES.values():
        for name in (style.bass_patch, style.chord_patch, style.arp_patch):
            assert name in PATCHES
        assert style.lead == "none" or style.lead in PATCHES
        for pattern in (style.kick, style.snare, style.hats, style.bass):
            assert len(pattern) == 16
        for chords in (*style.verses, *style.choruses):
            assert theory.parse_progression(chords)
