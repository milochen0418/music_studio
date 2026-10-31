"""A composer with no model files: a brief goes in (a style, a tempo, a key, chords, a mood), a
finished stereo piece comes out. ``theory`` is the notes, ``styles`` how each kind of music is
played, ``arrange`` writes the parts, ``synth`` makes the instruments from sums of sine waves,
``render`` plays the score and masters it.

A language model is good at saying what a piece should be and weak at writing hundreds of notes,
so it writes the brief (``music_studio.producer``) and this writes the notes. The same brief and
seed always give the same piece.
"""

from music_studio.composer.render import Piece, compose
from music_studio.composer.styles import STYLES, Brief

__all__ = ["Brief", "Piece", "STYLES", "compose"]
