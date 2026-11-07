import asyncio

import httpx

from music_studio import lrclib

LYDIA_TITLE = "F.I.R. 飛兒樂團 - Lydia (official 官方完整版MV)"
ROWS = [
    {"id": 1, "trackName": "Lydia", "artistName": "LYDIA JAZMIN", "duration": 236.0, "plainLyrics": "somebody else's song", "instrumental": False},
    {"id": 2, "trackName": "Lydia", "artistName": "F.I.R.", "duration": 206.0, "plainLyrics": "Lydia 迷離的眼眶", "instrumental": False},
    {
        "id": 3,
        "trackName": "Lydia",
        "artistName": "F.I.R.",
        "duration": 236.0,
        "plainLyrics": "Lydia 迷離的眼眶\n為何流浪",
        "syncedLyrics": "[00:18.01] Lydia 迷離的眼眶\n[00:23.10] 為何流浪\n[01:21.32] \n[01:35.94] Lydia 幸福不在遠方",
        "instrumental": False,
    },
    {"id": 4, "trackName": "Lydia", "artistName": "F.I.R.", "duration": 238.0, "plainLyrics": "", "syncedLyrics": "", "instrumental": True},
]


def test_a_video_title_comes_apart_into_the_names_in_it():
    assert lrclib.chunks(LYDIA_TITLE) == ["F.I.R.", "飛兒樂團", "Lydia"]
    assert lrclib.chunks("周杰倫 Jay Chou【稻香 Rice Field】Official MV") == ["周杰倫", "Jay Chou", "稻香", "Rice Field"]
    assert lrclib.chunks("五月天 MAYDAY [ 倔強 ] Official Music Video") == ["五月天", "MAYDAY", "倔強"]
    assert lrclib.queries("周杰倫 Jay Chou【稻香 Rice Field】Official MV")[:3] == ["周杰倫 Jay Chou 稻香 Rice Field", "周杰倫 Jay Chou", "Jay Chou 稻香"]
    assert len(lrclib.queries("a b c d e f g h")) <= lrclib.TRIES and lrclib.queries("") == []


def test_the_song_is_the_one_by_the_singer_in_the_title_and_nearest_in_length():
    found = lrclib.pick(ROWS, LYDIA_TITLE, 236.0)
    assert found.id == 3 and found.near and found.artist == "F.I.R."
    assert found.lyrics == "Lydia 迷離的眼眶\n為何流浪\n\nLydia 幸福不在遠方", "the timed lyrics part the song better than the plain ones"
    assert lrclib.pick(ROWS, LYDIA_TITLE, 207.0).id == 2
    far = lrclib.pick(ROWS, LYDIA_TITLE, 300.0)
    assert far is None, "too far in length: another song or version"
    assert lrclib.pick(ROWS, "Lydia", 236.0).id in (1, 3), "without a singer in the title, only the very same length counts"
    assert lrclib.pick(ROWS, "Lydia", 220.0) is None
    assert lrclib.pick([], LYDIA_TITLE, 236.0) is None and lrclib.pick("oops", LYDIA_TITLE, 236.0) is None


def test_a_search_tries_names_until_one_finds_the_song(monkeypatch):
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        q = request.url.params["q"]
        asked.append(q)
        assert request.headers["user-agent"] == lrclib.AGENT
        return httpx.Response(200, json=ROWS if q == "F.I.R. 飛兒樂團 Lydia" else [])

    real = httpx.AsyncClient
    monkeypatch.setattr(lrclib.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(answer), **kw))
    found = asyncio.run(lrclib.find(LYDIA_TITLE, 236.0))
    assert found.id == 3 and asked == ["F.I.R. 飛兒樂團 Lydia"]
    asked.clear()
    assert asyncio.run(lrclib.find("周杰倫 稻香", 223.0)) is None and asked == ["周杰倫 稻香"]


def test_without_an_answer_or_when_turned_off_nothing_is_found(monkeypatch):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    real = httpx.AsyncClient
    monkeypatch.setattr(lrclib.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(down), **kw))
    assert asyncio.run(lrclib.find(LYDIA_TITLE, 236.0)) is None
    monkeypatch.setenv("MUSIC_STUDIO_LRCLIB", "0")
    assert not lrclib.enabled() and asyncio.run(lrclib.find(LYDIA_TITLE, 236.0)) is None
