"""The studio's page: what is asked for, the work in the background, the takes."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import secrets
from pathlib import Path
from typing import Any

import reflex as rx
from reflex_ddns_auth.intent import IntentPage, intent_update

from music_studio import drafts, library, producer, remake
from music_studio.i18n import SCENES, STYLE_NAMES, TEXT

logger = logging.getLogger(__name__)
TAKES = 2  # at a time
BARS = {"short": 16, "medium": 32, "long": 64}
FINDER = "audio.find"


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
    )


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

    def _detect_lang(self) -> None:
        if self.lang not in TEXT:
            self.lang = "zh" if "zh" in (self.router.headers.accept_language or "").lower() else "en"

    def _load(self) -> None:
        self._detect_lang()
        self.takes = [_row(found) for found in drafts.recent()]
        self.sources = library.sources()

    @rx.event
    def on_load(self):
        self._load()

    @rx.event
    def open_intent(self, params: dict):
        """Asked by another app: ``words`` is what the music is for, and a kept take goes back."""
        self.in_dialog = True
        self._load()
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
            self.busy, self.error, self.stage = True, "", t["stage_asking"]
            lang, style, bars = self.lang, self.style, BARS.get(self.length, 32)
        try:
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
            self.busy, self.error, self.stage = True, "", t["stage_reading"]
            ref, upload, title, bars = self.source_ref, self.upload, self.source_title, BARS.get(self.length, 32)
        try:
            if upload:
                path: Path | None = drafts.data_dir() / "uploads" / upload
                source = {"title": title, "rights": "own"}
            else:
                path, source = await asyncio.to_thread(library.source_file, ref)
            if path is None or not path.is_file():
                raise FileNotFoundError(t["need_source"])
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


def _clean_title(title: str) -> str:
    return re.sub(r"\.(mp3|wav|m4a|flac|ogg)$", "", title or "", flags=re.IGNORECASE)
