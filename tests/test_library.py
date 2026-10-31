import numpy as np

from reflex_ddns_auth.collections import Collection

from music_studio import drafts, library
from music_studio.composer import Brief


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("DDNS_COLLECTIONS_ROOT", str(tmp_path / "collections"))
    monkeypatch.setenv("MUSIC_STUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DDNS_COLLECTIONS_NODE_URL", raising=False)


def test_a_kept_take_is_a_library_item_others_can_loop(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    made = drafts.take_composed(Brief(style="house", title="夜行", key="C", bars=8, energy=0.7), 3, "夜間賽車", "Ollama (x)", "fits")
    ref = library.keep(made)
    item = Collection("audio", app_id="music-box").get(ref, remote=False)
    assert item.kind == "audio.file" and item.title == "夜行"
    meta = item.meta
    assert meta["origin"] == "composed" and meta["rights"] == "own" and meta["words"] == "夜間賽車"
    assert 0 < meta["loop_start"] < meta["loop_end"] < meta["duration"]
    assert meta["artist"] == library.MAKER, "other apps show who made it"
    assert item.manifest["source"] == "https://music-studio.reflex-ddns.com/"
    assert item.manifest["producer"]["app"] == "music-studio"
    assert item.primary.suffix == ".mp3" and item.primary.stat().st_size > 10000
    assert item.thumbnail is not None and item.thumbnail.read_bytes().startswith(b"\x89PNG")


def test_only_the_newest_drafts_stay(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    monkeypatch.setattr(drafts, "KEEP", 2)
    for k in range(4):
        drafts.take_composed(Brief(style="lofi", title=str(k), bars=8), k, "", "", "")
    assert len(drafts.recent()) == 2


def test_a_draft_name_cannot_leave_the_folder(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    assert drafts.audio_path("../../etc") is None and drafts.info("..") is None


def test_what_someone_else_brought_is_not_called_ours(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    other = Collection("audio", app_id="youtube-to-mp3")
    with other.publish("yt-abc", kind="audio.file", title="A song", meta={"duration": 100}, primary="a.mp3") as item:
        with item.open("a.mp3") as fh:
            fh.write(np.zeros(10).tobytes())
    path, source = library.source_file("audio:youtube-to-mp3/yt-abc")
    assert path.name == "a.mp3" and source["rights"] == "third-party"
    assert [r.title for r in library.sources()] == ["A song"]
