"""The studio's page: what is asked for, the work in the background, the takes."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import logging
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

import reflex as rx
from reflex_ddns_auth import ai
from reflex_ddns_auth.intent import IntentPage, intent_update

from music_studio import drafts, library, producer, remake
from music_studio.i18n import SCENES, STYLE_NAMES, TEXT

logger = logging.getLogger(__name__)
TAKES = 2  # at a time
BARS = {"short": 16, "medium": 32, "long": 64}
SECONDS = {"short": 60, "medium": 120, "long": 200}  # a sung song of each length
FINDER = "audio.find"
MAX_COVER_BYTES = 40 * 1024 * 1024


@dataclasses.dataclass
class Take:
    id: str
    title: str
    origin: str
    rights: str
    style: str
    bpm: int
    key: str
    clock: str
    why: str
    model: str
    from_title: str
    wave: str
    ref: str
    lyrics: str
    loops: bool


def _clock(seconds: float) -> str:
    m, s = divmod(int(round(seconds or 0)), 60)
    return f"{m}:{s:02d}"


def _row(found: dict[str, Any]) -> Take:
    return Take(
        id=found["id"],
        title=found.get("title") or "",
        origin=found.get("origin") or "",
        rights=found.get("rights") or "own",
        style=found.get("style") or "",
        bpm=int(found.get("bpm") or 0),
        key=found.get("key") or "",
        clock=_clock(found.get("seconds") or 0),
        why=found.get("why") or "",
        model=found.get("model") or "",
        from_title=found.get("from_title") or "",
        wave="data:image/svg+xml;utf8,"
        + f"%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 -1.1 120 2.2' preserveAspectRatio='none'%3E%3Cpath d='{found.get('wave') or ''}' stroke='%23fbbf24' stroke-width='.55' fill='none'/%3E%3C/svg%3E",
        ref=found.get("ref") or "",
        lyrics="" if (found.get("lyrics") or "").strip().lower() in ("", "[instrumental]") else str(found.get("lyrics")),
        loops=float(found.get("loop_end") or 0) > 0,
    )


def _fill(text: str, **values: Any) -> str:
    return str(text or "").format(**values)


def _whole(value: Any, fallback: int = 0) -> int:
    """A whole number from what the engine reports (it says "N/A" for what it doesn't know)."""
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return fallback


class Studio(rx.State):
    lang: str = rx.LocalStorage("", name="music_studio_lang")
    tab: str = "compose"
    words: str = ""
    style: str = "auto"
    length: str = "medium"
    how: str = ""
    source_ref: str = ""
    source_title: str = ""
    upload: str = ""  # a file of ours in place of a library song
    sources: list[library.Source] = []
    takes: list[Take] = []
    busy: bool = False
    stage: str = ""
    error: str = ""
    in_dialog: bool = False
    caller_loop: bool = False
    finder_busy: int = 0
    # The music engine (ACE-Step through the hub): what it is now, and what is asked of it.
    engine: dict[str, Any] = {}
    voice: str = "none"  # none, or sing
    lyrics_lang: str = ""  # "" = the page's language
    method: str = ""  # tweak, remake; "" = remake when there is an engine
    vocals: str = "keep"  # keep, remove, instrument (a remake)

    @rx.var
    def t(self) -> dict[str, str]:
        return TEXT.get(self.lang, TEXT["zh"])

    @rx.var
    def scenes(self) -> list[str]:
        return SCENES.get(self.lang, SCENES["zh"])

    @rx.var
    def style_rows(self) -> list[list[str]]:
        return [[k, v] for k, v in STYLE_NAMES.get(self.lang, STYLE_NAMES["zh"]).items()]

    @rx.var
    def picked(self) -> str:
        return self.upload or self.source_ref

    @rx.var
    def engine_ok(self) -> bool:
        return bool(self.engine.get("ok"))

    @rx.var
    def engine_words(self) -> str:
        t = self.t
        if self.engine.get("ok"):
            return _fill(t["engine_ready"], tier=self.engine.get("tier") or "")
        if self.engine.get("helper"):
            return t["engine_wait"] + str(self.engine.get("why") or "")
        return t["engine_none"]

    @rx.var
    def remaking(self) -> bool:
        return self.method == "remake" or (self.method == "" and bool(self.engine.get("ok")))

    @rx.var
    def hub_page(self) -> str:
        """The AI Hub's page, next to this app on the same domain ("" when run on its own)."""
        parts = urlsplit(self.router.headers.origin or "")
        host = parts.hostname or ""
        if "." not in host or host.replace(".", "").isdigit():
            return ""
        return f"{parts.scheme}://ai.{host.split('.', 1)[1]}"

    def _detect_lang(self) -> None:
        if self.lang not in TEXT:
            self.lang = "zh" if "zh" in (self.router.headers.accept_language or "").lower() else "en"

    def _load(self) -> None:
        self._detect_lang()
        self.takes = [_row(found) for found in drafts.recent()]
        self.sources = library.sources()

    async def _engine(self) -> None:
        self.engine = (await ai.music_status()) or {"ok": False, "helper": False, "why": "no hub"}

    @rx.event
    async def on_load(self):
        self._load()
        await self._engine()

    @rx.event
    async def open_intent(self, params: dict):
        """Asked by another app: ``words`` is what the music is for, and a kept take goes back."""
        self.in_dialog = True
        self._load()
        await self._engine()
        self.tab = "compose"
        self.words = str(params.get("words") or "")
        self.style = str(params.get("style") or "auto")
        self.takes = []

    @rx.event
    def switch_lang(self):
        self.lang = "en" if self.lang == "zh" else "zh"

    @rx.event
    def set_tab(self, tab: str):
        self.tab = tab
        self.error = ""
        if tab == "remake":
            self.sources = library.sources()

    @rx.event
    def set_words(self, value: str):
        self.words = value

    @rx.event
    def set_how(self, value: str):
        self.how = value

    @rx.event
    def set_style(self, value: str):
        self.style = value

    @rx.event
    def set_length(self, value: str):
        self.length = value

    @rx.event
    def use_scene(self, scene: str):
        self.words = scene

    @rx.event
    def set_voice(self, value: str):
        self.voice = value

    @rx.event
    def set_lyrics_lang(self, value: str):
        self.lyrics_lang = value

    @rx.event
    def set_method(self, value: str):
        self.method = value

    @rx.event
    def set_vocals(self, value: str):
        self.vocals = value

    @rx.event
    def choose_source(self, ref: str, title: str):
        self.source_ref, self.source_title, self.upload = ref, title, ""

    @rx.event
    async def uploaded(self, files: list[rx.UploadFile]):
        for file in files[:1]:
            folder = drafts.data_dir() / "uploads"
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{secrets.token_hex(4)}{Path(file.name or 'song.mp3').suffix[:6]}"
            (folder / name).write_bytes(await file.read())
            self.upload, self.source_ref = name, ""
            self.source_title = file.name or name

    # ---------------------------------------------- news from the YouTube dialog

    @rx.event
    def finder_update(self, data: dict):
        event = data.get("event")
        if event == "started":
            self.finder_busy += 1
        elif event in ("failed", "ready"):
            self.finder_busy = max(0, self.finder_busy - 1)
            self.sources = library.sources()
        elif event == "pick" and data.get("ref"):
            self.sources = library.sources()
            self.source_ref, self.upload = str(data["ref"]), ""
            self.source_title = str(data.get("title") or "")

    @rx.event
    def finder_closed(self, data: dict):
        self.finder_busy = 0
        self.sources = library.sources()

    # ---------------------------------------------- making

    def _who(self) -> str:
        return str(self.router.session.client_token or "")[:8]

    @rx.event(background=True)
    async def make(self):
        async with self:
            words = self.words.strip()
            t = self.t
            if self.busy:
                return
            if not words:
                self.error = t["need_words"]
                return
            if self.voice == "sing" and not self.engine.get("ok"):
                self.error = t["need_engine"]
                return
            self.busy, self.error, self.stage = True, "", t["stage_asking"]
            lang, style, bars = self.lang, self.style, BARS.get(self.length, 32)
            sing, lyrics_lang, seconds = self.voice == "sing", self.lyrics_lang, SECONDS.get(self.length, 120)
        try:
            if sing:
                async for _ in self._sing(words, lang, lyrics_lang, seconds):
                    pass
                return
            brief, model, why = await producer.brief_for(words, lang, bars, style if style != "auto" else "")
            async with self:
                self.stage = t["stage_writing"]
            for _ in range(TAKES):
                made = await asyncio.to_thread(drafts.take_composed, brief, secrets.randbelow(1 << 30), words, model, why)
                async with self:
                    self.takes = [_row(made), *self.takes]
                yield intent_update({"event": "take", "title": made["title"]})
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Composing failed")
            async with self:
                self.error = t["failed"] + str(e)
        finally:
            async with self:
                self.busy, self.stage = False, ""

    async def _follow(self, song: ai.Song, t: dict[str, str]) -> bytes:
        """Shows the engine's progress until the song is done; its MP3."""
        async for event in song:
            if event.get("status"):
                async with self:
                    self.stage = _fill(t["stage_engine"], s=event["status"], t=int(event.get("secs") or 0))
        return await song.audio()

    async def _sing(self, words: str, lang: str, lyrics_lang: str, seconds: int):
        """A song with singing: the model writes it, the engine sings and plays it."""
        t = self.t
        async with self:
            self.stage = t["stage_writing_song"]
        spec, title, model, why = await producer.song_for(words, lang, lyrics_lang, False, seconds)
        song = ai.music(spec)
        mp3 = await self._follow(song, t)
        sung = spec["lyrics"] != "[Instrumental]"
        made = await asyncio.to_thread(
            drafts.take_engine,
            mp3,
            {
                "origin": "sung" if sung else "composed",
                "rights": "own",
                "title": title,
                "words": words,
                "model": model,
                "why": why,
                "mood": spec["caption"][:120],
                "bpm": _whole(song.metas.get("bpm"), _whole(spec.get("bpm"))),
                "key": _clean_meta(song.metas.get("keyscale")),
                "lyrics": spec["lyrics"],
                "caption": spec["caption"],
                "language": spec["language"],
                "engine": song.models,
            },
        )
        async with self:
            self.takes = [_row(made), *self.takes]
        yield intent_update({"event": "take", "title": made["title"]})

    async def _cover(self, path: Path, source: dict[str, str], title: str, how: str, vocals: str):
        """The engine remakes a recording: new style, without the singing, or with an instrument
        in its place."""
        t = self.t
        if path.stat().st_size > MAX_COVER_BYTES:
            raise ValueError("this recording is too big to remake (40 MB at most)")
        found = await asyncio.to_thread(remake.analyse, path)
        spec, new_title, model, why = await producer.cover_for(how, found.facts(), _clean_title(title), vocals)
        spec["audio_b64"] = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode()
        spec["audio_format"] = path.suffix.lstrip(".").lower() or "mp3"
        spec["language"] = "zh" if self.lang == "zh" else "en"
        song = ai.music(spec)
        mp3 = await self._follow(song, t)
        made = await asyncio.to_thread(
            drafts.take_engine,
            mp3,
            {
                "origin": "cover",
                "rights": source.get("rights") or "third-party",
                "title": new_title or title,
                "words": how,
                "model": model,
                "why": why,
                "mood": spec["caption"][:120],
                "bpm": _whole(song.metas.get("bpm"), round(found.bpm)),
                "key": _clean_meta(song.metas.get("keyscale")) or f"{found.key} {found.mode}",
                "from_ref": source.get("ref") or "",
                "from_title": source.get("title") or "",
                "plan": {"cover_strength": round(float(spec["cover_strength"]), 2), "vocals": vocals},
                "lyrics": spec["lyrics"],
                "caption": spec["caption"],
                "engine": song.models,
            },
        )
        async with self:
            self.takes = [_row(made), *self.takes]

    @rx.event(background=True)
    async def change(self):
        async with self:
            t = self.t
            how = self.how.strip()
            if self.busy:
                return
            if not self.picked:
                self.error = t["need_source"]
                return
            if not how:
                self.error = t["need_words"]
                return
            remaking = self.remaking
            if remaking and not self.engine.get("ok"):
                self.error = t["need_engine"]
                return
            self.busy, self.error, self.stage = True, "", t["stage_reading"]
            ref, upload, title, bars, vocals = self.source_ref, self.upload, self.source_title, BARS.get(self.length, 32), self.vocals
        try:
            if upload:
                path: Path | None = drafts.data_dir() / "uploads" / upload
                source = {"title": title, "rights": "own"}
            else:
                path, source = await asyncio.to_thread(library.source_file, ref)
            if path is None or not path.is_file():
                raise FileNotFoundError(t["need_source"])
            if remaking:
                await self._cover(path, source, title, how, vocals)
                return
            found = await asyncio.to_thread(remake.analyse, path)
            plan, model, why = await producer.plan_for(how, found.facts(), _clean_title(title))
            async with self:
                self.stage = t["stage_changing"]
            made = await asyncio.to_thread(drafts.take_remade, path, plan, bars, found, source, how, model, why)
            async with self:
                self.takes = [_row(made), *self.takes]
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Changing a song failed")
            async with self:
                self.error = t["failed"] + str(e)
        finally:
            async with self:
                self.busy, self.stage = False, ""

    @rx.event
    def keep(self, draft: str):
        found = drafts.info(draft)
        if found is None:
            self.takes = [row for row in self.takes if row.id != draft]
            return None
        ref = found.get("ref") or library.keep(found)
        drafts.update(draft, ref=ref)
        self.takes = [dataclasses.replace(row, ref=ref) if row.id == draft else row for row in self.takes]
        if self.in_dialog:
            return IntentPage.finish(
                {
                    "ref": ref,
                    "refs": [ref],
                    "title": found.get("title") or "",
                    "seconds": found.get("seconds"),
                    "loop_start": found.get("loop_start"),
                    "loop_end": found.get("loop_end"),
                    "rights": found.get("rights"),
                }
            )
        return rx.toast.success(self.t["kept"])


def _clean_meta(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in ("N/A", "NONE", "NULL") else text


def _clean_title(title: str) -> str:
    return re.sub(r"\.(mp3|wav|m4a|flac|ogg)$", "", title or "", flags=re.IGNORECASE)
