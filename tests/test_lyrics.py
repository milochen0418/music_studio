import numpy as np

from music_studio import lyrics
from music_studio.lyrics import Line

WORDS = "[Verse 1]\n夜色降臨\n引擎聲劃破雨幕\n\n[Chorus]\nRacing through the night\n(Instrumental)\nNever look behind\n"


def test_the_tags_are_not_sung():
    assert lyrics.sections(WORDS) == [["夜色降臨", "引擎聲劃破雨幕"], ["Racing through the night"], ["Never look behind"]], "a break in the band parts them too"
    assert lyrics.sections("[Instrumental]") == [] and lyrics.sections("【副歌】\n（間奏）") == []
    assert lyrics.sections("one\n(oh, oh)\n\nthree") == [["one", "(oh, oh)"], ["three"]], "without tags, blank lines part them; backing vocals are sung"


def test_lrc_both_ways():
    lines = [Line(2.0, "夜色降臨"), Line(65.25, "Racing")]
    text = lyrics.to_lrc(lines)
    assert text == "[00:02.00]夜色降臨\n[01:05.25]Racing"
    assert lyrics.from_lrc(text) == lines
    assert lyrics.has_times(text) and not lyrics.has_times(WORDS)


def test_a_line_sung_twice_comes_twice_in_time_order():
    got = lyrics.from_lrc("[ti:A song]\n[00:30.00][00:10.00]chorus\n[00:20.5]verse\nno time")
    assert [(line.at, line.text) for line in got] == [(10.0, "chorus"), (20.5, "verse"), (30.0, "chorus")]


def test_clocks():
    assert lyrics.clock(83.44) == "1:23.4" and lyrics.clock(0) == "0:00.0" and lyrics.clock(59.99) == "1:00.0"
    assert lyrics.read_clock("1:23.4") == 83.4 and lyrics.read_clock("83.4") == 83.4
    assert lyrics.read_clock("x") is None and lyrics.read_clock("-1") is None


def test_syllables():
    assert lyrics.syllables("夜色降臨") == 4
    assert lyrics.syllables("Racing through the night") == 5
    assert lyrics.syllables("我的 night") == 3
    assert lyrics.syllables("…") == 1


def test_a_guess_keeps_the_order_inside_the_song_with_a_break_between_sections():
    lines = lyrics.guess(WORDS, 120.0)
    assert [line.text for line in lines] == ["夜色降臨", "引擎聲劃破雨幕", "Racing through the night", "Never look behind"]
    at = [line.at for line in lines]
    assert at == sorted(at) and 0 < at[0] and at[-1] < 120
    # Each line takes time for its syllables; a new section waits a little longer.
    assert abs((at[2] - at[1]) / (at[1] - at[0]) - (7 + lyrics.SECTION_GAP) / 4) < 0.01


def test_a_quiet_intro_puts_the_first_line_after_it():
    loudness = np.r_[np.full(40, 0.01), np.full(200, 0.5)]  # 20 s of almost nothing, then music
    assert lyrics.guess(WORDS, 120.0, loudness, 0.5)[0].at >= 20


def test_what_the_video_shows_moves_line_by_line():
    shown = lyrics.shown([Line(5, "a"), Line(8, "b"), Line(40, "c")], 60)
    assert all(start < end for start, end, *_ in shown)
    assert all(earlier[1] <= later[0] + 1e-9 for earlier, later in zip(shown, shown[1:])), "never two at once"
    starts = {now: start for start, _, now, _ in shown if now}
    assert starts == {"a": 5, "b": 8, "c": 40}
    assert (2, 5, "", "a") in shown, "the first line is announced before it comes"
    b = next(cue for cue in shown if cue[2] == "b")
    assert b[1] < 40 and b[3] == "c", "after a line, a long break leaves the screen to the music"
    assert (37, 40, "", "c") in shown
