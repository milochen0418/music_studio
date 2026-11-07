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


def _heard(*phrases: tuple[float, str], each: float = 0.4) -> list[tuple[float, float, str]]:
    """Words as Whisper gives them: each phrase's words one after another from its time."""
    words = []
    for at, phrase in phrases:
        for word in phrase.split():
            words.append((at, at + each, word))
            at += each
    return words


SONG = ["The lake lies quiet, white and wide", "No wind tonight, no other side", "Your laugh, the summer, one small boat", "The words we said, the songs we wrote"]


def test_each_line_goes_where_it_was_heard_even_when_heard_a_little_wrong():
    words = _heard((10.0, "The lake lies quite white and wide"), (14.0, "no wind to night know other side"), (18.0, "You laughed the summer one small boat"), (22.5, "the words we said the songs we wrote"))
    lines = lyrics.align(SONG, words, 60)
    assert [round(line.at, 1) for line in lines] == [10.0, 14.0, 18.0, 22.5]
    assert all(line.heard for line in lines) and all(line.at < line.end <= line.at + 4 for line in lines)


def test_a_line_not_sung_is_marked_and_waits_between_its_neighbours():
    words = _heard((5.0, "music music"), (18.0, "your laugh the summer one small boat"), (22.0, "the words we said the songs we wrote"))
    lines = lyrics.align(SONG, words, 60)
    assert [line.heard for line in lines] == [False, False, True, True]
    assert lines[0].at < lines[1].at < lines[2].at == 18.0, "in order, before the first heard line"


def test_one_common_word_does_not_make_a_line_heard():
    # "you" alone would fit "No wind tonight": not enough to say that line was sung.
    words = _heard((18.0, "you laughed the summer one small boat"))
    lines = lyrics.align(SONG, words, 60)
    assert [line.heard for line in lines] == [False, False, True, False]


def test_a_word_missed_at_the_start_of_a_line_moves_it_earlier():
    words = _heard((20.0, "the summer one small boat"))  # "Your laugh" not heard
    line = lyrics.align(SONG, words, 60)[2]
    assert line.heard and 19.0 < line.at < 20.0


def test_chinese_is_matched_by_its_sound():
    lines = ["衝進髮夾彎 甩尾向天", "火花點亮萬丈深淵", "降檔 入彎 全油門向前"]
    # Whisper writes simplified characters, and the wrong ones for the right sound.
    words = _heard((30.0, "冲 进 发 夹 弯 甩 尾 向 天"), (33.0, "火 花 点 亮 万 整 深 渊"), (36.0, "将 刀 入 弯 全 油 门 向 前"), each=0.3)
    found = lyrics.align(lines, words, 60)
    assert [line.at for line in found] == [30.0, 33.0, 36.0] and all(line.heard for line in found)
    assert lyrics.units("髮夾彎") == lyrics.units("发夹弯") == ["fa", "jia", "wan"]


def test_noise_before_the_singing_is_left_alone():
    words = _heard((2.0, "优 优 独 播 剧 场 Yo Yo Television"), (30.0, "冲 进 发 夹 弯 甩 尾 向 天"), each=0.3)
    found = lyrics.align(["衝進髮夾彎 甩尾向天"], words, 60)
    assert found[0].at == 30.0


def test_nothing_heard_means_nothing_placed():
    assert [line.heard for line in lyrics.align(SONG, [], 60)] == [False] * 4
    assert all(not line.heard for line in lyrics.align(SONG, _heard((5.0, "la la la la")), 60))


def test_a_line_heard_holds_until_it_is_sung_then_leaves_the_screen():
    shown = lyrics.shown([Line(10, "a", end=12.0, heard=True), Line(40, "b", end=43.0, heard=True)], 60)
    a = next(cue for cue in shown if cue[2] == "a")
    assert a[0] == 10 and 12.5 <= a[1] <= 13.5, a


def test_lyrics_get_section_tags_and_a_part_sung_again_is_a_chorus():
    text = lyrics.tagged("霓虹劃過\n引擎咆哮\n\n最後一圈\n踩到底\n\n轉彎\n\n最後一圈\n踩到底")
    assert text == "[Verse 1]\n霓虹劃過\n引擎咆哮\n\n[Chorus]\n最後一圈\n踩到底\n\n[Verse 2]\n轉彎\n\n[Chorus]\n最後一圈\n踩到底"
    assert lyrics.tagged("[Intro]\nhey\n\n[Chorus]\nla la") == "[Intro]\nhey\n\n[Chorus]\nla la", "tags already there stay"
    assert lyrics.tagged("[00:01.00]one\n[00:03.00]two") == "[Verse 1]\none\ntwo" and lyrics.tagged("  \n") == ""


def test_timed_lyrics_become_plain_lines_in_parts():
    assert lyrics.from_lrc_text("[00:00.04] Por los\n[00:05.40] \n[00:18.01] Lydia 迷離\n[00:23.10] 為何流浪\n[01:21.32] ") == "Por los\n\nLydia 迷離\n為何流浪"


def test_what_is_heard_in_simplified_is_written_as_in_taiwan():
    assert lyrics.traditional("为何流浪 心碎的海洋 受了伤 软件") == "為何流浪 心碎的海洋 受了傷 軟體"
    assert lyrics.traditional("Lydia 迷離的眼眶") == "Lydia 迷離的眼眶" and lyrics.traditional("") == ""


def test_the_language_lyrics_are_written_in():
    assert lyrics.script_language("Por los momentos difíciles\nLydia 迷離的眼眶 為何流浪 心碎的海洋") == "zh"
    assert lyrics.script_language("こんにちは世界") == "ja" and lyrics.script_language("안녕하세요 여러분") == "ko"
    assert lyrics.script_language("Por los momentos difíciles") == "en" and lyrics.script_language("123") == ""
