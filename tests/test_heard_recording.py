"""What was heard in a recording about to be remade: whether anybody sings in it, and its lines as
lyrics for the engine. (Listening itself needs the speech model: tests/test_listen.py.)"""

from music_studio import listen, lyrics

# What Whisper "heard" in two pieces nobody sings in (measured on the studio's synthwave and on
# fifteen minutes of sea waves), and in a song (F.I.R.'s Lydia).
SYNTHWAVE = {"seconds": 150.0, "lines": [[61.78, 62.2, "Thank you."], [100.42, 100.96, "Thank you."], [137.8, 138.26, "Thank you."]]}
WAVES = {
    "seconds": 900.0,
    "lines": [[9.76, 11.62, "Here we go."], [38.54, 39.32, "We'll be right back."], [242.72, 245.68, "I don't know."], [268.24, 271.2, "I don't know."],
              [297.94, 298.2, "Let's go."], [373.34, 376.36, "I don't know."], [490.84, 492.28, "Let's go."], [787.58, 788.48, "I don't know."]],
}
SONG = {
    "seconds": 235.8,
    "lines": [[23.88, 27.84, "為何流浪"], [27.84, 31.44, "心碎的海洋"], [31.44, 33.28, "受了伤"], [33.28, 36.96, "连微笑都彷徨"],
              [36.96, 39.5, "Gypsy女郎"], [39.5, 41.86, "为谁而唱"], [97.22, 103.06, "Lidia 幸福不在遠方"], [103.06, 108.08, "可以擅長 許下願望"],
              [108.08, 113.96, "你会感受爱 感受恨 感受原谅"], [234.34, 235.0, "很近"]],
}


def test_music_nobody_sings_in_has_no_lines_to_sing_again():
    assert listen.sung(SYNTHWAVE) == []
    assert listen.sung(WAVES) == []
    assert listen.sung({}) == [] and listen.sung(None) == []


def test_a_songs_lines_are_kept_in_order_without_the_too_short_ones():
    lines = listen.sung(SONG)
    assert [text for _, _, text in lines][:3] == ["為何流浪", "心碎的海洋", "受了伤"]
    assert "很近" not in [text for _, _, text in lines], "under a second: mostly invented"
    assert len(lines) == 9


def test_lines_heard_become_lyrics_in_sections():
    text = lyrics.from_heard(listen.sung(SONG))
    assert text.splitlines()[0] == "[Verse 1]" and "\n\n[Verse 2]\nLidia 幸福不在遠方" in text
    assert lyrics.sections(text)[0][:2] == ["為何流浪", "心碎的海洋"]


def test_the_stretches_where_nothing_was_heard_are_listened_to_again():
    """Whisper samples when unsure, so each listen misses different lines: a whole verse at times."""
    heard = [[1.92, 6.82, "intro"], [31.34, 36.84, "a"], [36.84, 80.58, "b"], [120.2, 144.16, "c"], [219.42, 235.0, "d"]]
    assert listen.gaps(heard, 235.79) == [(6.82, 31.34), (80.58, 120.2), (144.16, 219.42)]
    assert listen.gaps([], 100.0) == [(0.0, 100.0)]
    assert listen.gaps([[0.5, 50.0, "x"], [40.0, 99.0, "overlapping"]], 100.0) == []


def test_lines_heard_again_fill_only_what_the_first_listen_missed():
    words, lines = listen._merged(
        [[2.0, 3.0, "a", 0.9]], [[1.0, 5.0, "a"]], [[100.0, 101.0, "Lydia", 0.8], [2.0, 3.0, "a2", 0.5]], [[98.0, 103.0, "Lydia 幸福不在遠方"], [1.5, 4.5, "a again"]]
    )
    assert [row[2] for row in lines] == ["a", "Lydia 幸福不在遠方"], "a line heard twice is kept once"
    assert [w[2] for w in words] == ["a", "Lydia"]
