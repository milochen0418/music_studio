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

import numpy as np
import reflex as rx
from reflex_ddns_auth import ai
from reflex_ddns_auth.intent import IntentPage, intent_update

from music_studio import drafts, library, listen, lrclib, lyrics, making, producer, remake, video
from music_studio.composer import Brief
from music_studio.i18n import SCENES, STYLE_NAMES, TEXT

logger = logging.getLogger(__name__)
TAKES = 2  # at a time
BARS = {"short": 16, "medium": 32, "long": 64}
SECONDS = {"short": 60, "medium": 120, "long": 200}  # a sung song of each length
FINDER = "audio.find"
MAX_COVER_BYTES = 40 * 1024 * 1024
# What of a take's engine request is sent again to make it again (the recording is read anew).
AGAIN_KEYS = ("task", "caption", "lyrics", "language", "duration", "bpm", "cover_strength", "reference", "repaint_start", "repaint_end", "repaint_mode", "audio_format")
# The words' languages the person can choose (Whisper's codes; the engine sings in each).
WORD_LANGUAGES = [["zh", "中文"], ["yue", "粵語"], ["en", "English"], ["ja", "日本語"], ["ko", "한국어"], ["es", "Español"], ["fr", "Français"], ["de", "Deutsch"], ["it", "Italiano"], ["pt", "Português"], ["ru", "Русский"]]
PATCH_SHORTEST, PATCH_LONGEST = 3.0, 90.0  # seconds: what ACE-Step's repaint is made for


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
    has_video: bool = False  # rows kept in a session from before videos have none
    level: str = ""  # a remake's closeness: close, standard, free
    again_ok: bool = False  # its record says enough to make it again
    patch_ok: bool = False  # made by the engine: a part of it can be made again


def _clock(seconds: float) -> str:
    m, s = divmod(int(round(seconds or 0)), 60)
    return f"{m}:{s:02d}"


def _row(found: dict[str, Any]) -> Take:
    plan = found.get("plan") if isinstance(found.get("plan"), dict) else {}
    level = str(plan.get("closeness") or "") or (producer.level_of(plan.get("cover_strength")) if found.get("origin") == "cover" else "")
    kept = drafts.making_path(found["id"]) is not None
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
        has_video=video.path(found["id"]) is not None,
        level=level,
        again_ok=kept and found.get("origin") in ("composed", "sung", "cover"),
        patch_ok=bool(found.get("engine")),
    )


def _numbered(title: str, taken: list[str]) -> str:
    """A title for one more take like ``title``: ``title #2``, ``#3``…"""
    base = re.sub(r" #\d+$", "", title or "")
    n = 2
    while f"{base} #{n}" in taken:
        n += 1
    return f"{base} #{n}"


def _plain_clock(seconds: float) -> str:
    m, s = divmod(int(round(seconds or 0)), 60)
    return f"{m}:{s:02d}"


def _compared(draft: str, recording: dict[str, Any]) -> dict[str, Any]:
    """A take measured against the recording it was made from (its tempo, key and length)."""
    path = drafts.audio_path(draft)
    if path is None or not recording.get("seconds"):
        return {}
    out = remake.analyse(path)
    return {
        "bpm": [round(float(recording.get("bpm") or 0)), round(out.bpm)],
        "key": [str(recording.get("key") or ""), f"{out.key} {out.mode}"],
        "seconds": [round(float(recording["seconds"]), 1), round(out.seconds, 1)],
    }


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
    vocals: str = "keep"  # keep (sung again), remove, instrument (a remake)
    closeness: str = ""  # "" = the AI producer chooses; close, standard, free
    aim_sound: bool = False  # the recording also as the sound to aim for (experimental)
    upload_own: bool = False  # the person says the uploaded recording is theirs to change
    # The words a remake will sing again, shown to the person before the engine starts.
    confirming: bool = False
    confirm_lyrics: str = ""
    confirm_language: str = ""
    confirm_note: str = ""
    confirm_from: str = ""  # lrclib, heard, none
    confirm_version: int = 0  # a new suggestion: the box shows it afresh
    _pending: dict[str, Any] = {}  # the remake waiting for its words

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
    def vocals_note(self) -> str:
        return self.t.get(f"vocals_{self.vocals}_note", "")

    @rx.var
    def closeness_note(self) -> str:
        return self.t.get(f"closeness_{self.closeness or 'auto'}_note", "")

    @rx.var
    def word_languages(self) -> list[list[str]]:
        return WORD_LANGUAGES

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
        yield rx.set_value("words", self.words)

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
        yield rx.set_value("words", scene)

    @rx.event
    def set_voice(self, value: str):
        self.voice = value

    @rx.event
    def set_lyrics_lang(self, value: str):
        self.lyrics_lang = value

    @rx.event
    def set_method(self, value: str):
        self.method = value
        self._drop_words()

    @rx.event
    def set_vocals(self, value: str):
        self.vocals = value
        self._drop_words()

    @rx.event
    def set_closeness(self, value: str):
        self.closeness = value if value in producer.LEVELS else ""

    @rx.event
    def set_aim_sound(self, value: bool):
        self.aim_sound = bool(value)

    @rx.event
    def set_upload_own(self, value: bool):
        self.upload_own = bool(value)

    @rx.event
    def set_confirm_lyrics(self, value: str):
        self.confirm_lyrics = value

    @rx.event
    def set_confirm_language(self, value: str):
        self.confirm_language = value

    @rx.event
    def cancel_words(self):
        self._drop_words()

    def _drop_words(self) -> None:
        self.confirming, self._pending = False, {}

    @rx.event
    def choose_source(self, ref: str, title: str):
        self.source_ref, self.source_title, self.upload = ref, title, ""
        self._drop_words()

    @rx.event
    async def uploaded(self, files: list[rx.UploadFile]):
        for file in files[:1]:
            folder = drafts.data_dir() / "uploads"
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{secrets.token_hex(4)}{Path(file.name or 'song.mp3').suffix[:6]}"
            (folder / name).write_bytes(await file.read())
            self.upload, self.source_ref = name, ""
            self.source_title = file.name or name
            self.upload_own = False  # said anew for each recording
            self._drop_words()

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
            talk = producer.Talk()
            brief, model, why = await producer.brief_for(words, lang, bars, style if style != "auto" else "", talk=talk)
            async with self:
                self.stage = t["stage_writing"]
            for _ in range(TAKES):
                seed = secrets.randbelow(1 << 30)
                record = making.record("composed", words, talk, "composer", {**dataclasses.asdict(brief), "seed": seed})
                made = await asyncio.to_thread(drafts.take_composed, brief, seed, words, model, why, record)
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
        talk = producer.Talk()
        spec, title, model, why = await producer.song_for(words, lang, lyrics_lang, False, seconds, talk=talk)
        song = ai.music(spec)
        mp3 = await self._follow(song, t)
        sung = spec["lyrics"] != "[Instrumental]"
        record = making.record("sung" if sung else "composed", words, talk, "engine", dict(spec), engine=making.engine_said(song))
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
            record,
        )
        async with self:
            self.takes = [_row(made), *self.takes]
        yield intent_update({"event": "take", "title": made["title"]})

    async def _cover(
        self,
        path: Path,
        source: dict[str, str],
        title: str,
        how: str,
        vocals: str,
        t: dict[str, str],
        lang: str,
        *,
        recording: dict[str, Any] | None = None,
        closeness: str = "",
        aim: bool = False,
        words: str = "",
        language: str = "",
        listening: dict[str, Any] | None = None,
        words_from: dict[str, Any] | None = None,
    ):
        """The engine remakes a recording, in a new style or its own: sung again with the words the
        person checked (``words``, in ``language``), without the singing, or with an instrument
        playing its tune. ``recording`` is what was measured in it, when it already was."""
        if path.stat().st_size > MAX_COVER_BYTES:
            raise ValueError("this recording is too big to remake (40 MB at most)")
        recording = recording or await asyncio.to_thread(_measured, path)
        async with self:
            self.stage = t["stage_planning"]
        talk = producer.Talk()
        spec, new_title, model, why = await producer.cover_for(
            how, recording["facts"], _clean_title(title), vocals, lyrics=words, closeness=closeness, lang=lang, talk=talk
        )
        sung = spec["lyrics"] != "[Instrumental]"
        if vocals == "keep" and not sung:
            why = f"{t['no_singing_heard']} {why}".strip()
        spec["audio_b64"] = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode()
        spec["audio_format"] = path.suffix.lstrip(".").lower() or "mp3"
        spec["language"] = (producer.engine_language(language) if sung else "") or ("zh" if lang == "zh" else "en")
        if aim:
            spec["reference"] = "source"
        song = ai.music(spec)
        mp3 = await self._follow(song, t)
        request = {k: v for k, v in spec.items() if k != "audio_b64"}
        request["source"] = {"title": source.get("title") or title, "bytes": path.stat().st_size, **{k: source[k] for k in ("ref", "upload") if source.get(k)}}
        record = making.record("cover", how, talk, "engine", request, engine=making.engine_said(song), listening=listening, lyrics_from=words_from)
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
                "bpm": _whole(song.metas.get("bpm"), round(float(recording["bpm"]))),
                "key": _clean_meta(song.metas.get("keyscale")) or str(recording["key"]),
                "from_ref": source.get("ref") or "",
                "from_title": source.get("title") or "",
                "plan": {"cover_strength": spec["cover_strength"], "closeness": producer.level_of(spec["cover_strength"]), "vocals": vocals, "reference": aim},
                "lyrics": spec["lyrics"],
                "caption": spec["caption"],
                "language": spec["language"],
                "engine": song.models,
            },
            record,
        )
        await self._add_compared(made, recording)

    async def _add_compared(self, made: dict[str, Any], recording: dict[str, Any] | None) -> None:
        """The new take beside the others, measured against its recording first (a few seconds)."""
        if recording:
            try:
                compare = await asyncio.to_thread(_compared, made["id"], recording)
                if compare:
                    await asyncio.to_thread(drafts.update_making, made["id"], compare=compare)
            except Exception:  # noqa: BLE001 - the take is there either way
                logger.exception("Measuring a take against its recording failed")
        async with self:
            self.takes = [_row(made), *self.takes]

    async def _find_words(self, path: Path, source: dict[str, str], title: str, t: dict[str, str], lang: str) -> None:
        """The words a remake will sing again, for the person to check before the engine starts:
        the song's lyrics from LRCLIB when it has them, else what the AI hears in the recording."""
        recording = await asyncio.to_thread(_measured, path)
        async with self:
            self.stage = t["stage_lookup"]
        hit = await lrclib.find(_clean_title(source.get("title") or title), float(recording["seconds"]))
        if hit is not None:
            language = producer.engine_language(lyrics.script_language(hit.lyrics))
            text = lyrics.tagged(hit.lyrics)
            if lang == "zh" and language in ("zh", "yue"):
                text = lyrics.traditional(text)
            note = _fill(t["confirm_lrclib"], artist=hit.artist, track=hit.track) + ("" if hit.near else t["confirm_lrclib_far"])
            words_from: dict[str, Any] = {"from": "lrclib", **hit.as_dict()}
            listening = None
        else:
            text, language, note, words_from, listening = await self._listen_words(path, source.get("language") or "", t, lang)
        async with self:
            self._pending = {"path": str(path), "source": source, "title": title, "recording": recording, "suggested": text, "words_from": words_from, "listening": listening}
            self.confirm_lyrics, self.confirm_language, self.confirm_note = text, language, note
            self.confirm_from = str(words_from["from"])
            self.confirm_version += 1
            self.confirming = True

    async def _listen_words(self, path: Path, language: str, t: dict[str, str], lang: str):
        """What the AI hears sung in a recording, as lyrics in parts: (text, its language, the note
        for the person, where the words came from, the listening's record)."""

        async def told(job: listen.Progress) -> None:
            async with self:
                self.stage = _fill(t[f"hear_{job.phase}"], p=int(job.done * 100), mb=job.note)

        async with self:
            self.stage = t["hear_wait"]
        said = await listen.hear_recording(path, language, told)
        heard, heard_in = listen.sung(said), str(said.get("language") or "")
        text = lyrics.tagged(re.sub(r"^\[Verse \d+\]$", "", lyrics.from_heard(heard), flags=re.MULTILINE)) if heard else ""
        if text and lang == "zh" and heard_in in ("zh", "yue"):
            text = lyrics.traditional(text)
        note = _fill(t["confirm_heard"], n=len(heard)) if heard else t["confirm_none"]
        listening = {"model": said.get("model") or "", "language": heard_in, "lines": len(heard)}
        return text, producer.engine_language(heard_in), note, {"from": "heard" if heard else "none"}, listening

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
            remaking = self.remaking
            if remaking and not self.engine.get("ok"):
                self.error = t["need_engine"]
                return
            self.busy, self.error, self.stage, self.confirming = True, "", t["stage_reading"], False
            ref, upload, title, bars, vocals, lang = self.source_ref, self.upload, self.source_title, BARS.get(self.length, 32), self.vocals, self.lang
            own, closeness, aim = self.upload_own, self.closeness, self.aim_sound
        try:
            if upload:
                path: Path | None = drafts.data_dir() / "uploads" / upload
                # Somebody else's unless the person says it is theirs.
                source = {"title": title, "rights": "own" if own else "third-party", "upload": upload}
            else:
                path, source = await asyncio.to_thread(library.source_file, ref)
            if path is None or not path.is_file():
                raise FileNotFoundError(t["need_source"])
            if remaking:
                if vocals == "keep":
                    # The engine can't keep a singer: it sings the words it is given, so they are
                    # found first and shown to the person, who starts the remake with them.
                    await self._find_words(path, source, title, t, lang)
                else:
                    await self._cover(path, source, title, how, vocals, t, lang, closeness=closeness, aim=aim)
                return
            found = await asyncio.to_thread(remake.analyse, path)
            talk: producer.Talk | None = None
            if how:
                talk = producer.Talk()
                plan, model, why = await producer.plan_for(how, found.facts(), _clean_title(title), talk=talk)
            else:  # nothing asked for: the strongest stretch as a loop, as it sounds
                plan, model, why = remake.Plan(title=_clean_title(title), room=0.0), "", t["tweak_as_is"]
            async with self:
                self.stage = t["stage_changing"]
            record = making.record("remake", how, talk, "remaker", {**dataclasses.asdict(plan), "bars": bars, "source": source.get("title") or title})
            made = await asyncio.to_thread(drafts.take_remade, path, plan, bars, found, source, how, model, why, record)
            async with self:
                self.takes = [_row(made), *self.takes]
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Changing a song failed")
            async with self:
                self.error = t["failed"] + str(e)
        finally:
            async with self:
                self.busy, self.stage = False, ""

    @rx.event(background=True)
    async def listen_words(self):
        """The words as the AI hears them (in the language chosen, when one is) in place of the
        ones shown."""
        async with self:
            t, lang = self.t, self.lang
            if self.busy or not self._pending:
                return
            pending = dict(self._pending)
            language = self.confirm_language
            self.busy, self.error = True, ""
        try:
            text, heard_in, note, words_from, listening = await self._listen_words(Path(pending["path"]), language, t, lang)
            async with self:
                if self._pending.get("path") == pending["path"]:
                    self._pending = {**self._pending, "suggested": text, "words_from": words_from, "listening": listening}
                    self.confirm_lyrics, self.confirm_note, self.confirm_from = text, note, str(words_from["from"])
                    self.confirm_language = heard_in or language
                    self.confirm_version += 1
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Listening for the words failed")
            async with self:
                self.error = t["failed"] + str(e)
        finally:
            async with self:
                self.busy, self.stage = False, ""

    @rx.event(background=True)
    async def confirm_words(self):
        """The remake, with the words as the person left them."""
        async with self:
            t, lang = self.t, self.lang
            if self.busy or not self.confirming or not self._pending:
                return
            if not self.engine.get("ok"):
                self.error = t["need_engine"]
                return
            pending = dict(self._pending)
            words, language = self.confirm_lyrics, self.confirm_language
            how, closeness, aim = self.how.strip(), self.closeness, self.aim_sound
            self.busy, self.error, self.stage, self.confirming = True, "", t["stage_planning"], False
        try:
            words_from = dict(pending.get("words_from") or {})
            if words.strip() and words_from.get("from") == "none":
                words_from = {"from": "typed"}
            elif words_from.get("from") in ("lrclib", "heard"):
                words_from["edited"] = _same_words(words) != _same_words(str(pending.get("suggested") or ""))
            await self._cover(
                Path(pending["path"]),
                pending["source"],
                pending["title"],
                how,
                "keep",
                t,
                lang,
                recording=pending.get("recording"),
                closeness=closeness,
                aim=aim,
                words=words,
                language=language,
                listening=pending.get("listening"),
                words_from=words_from,
            )
            async with self:
                if self._pending.get("path") == pending["path"]:
                    self._pending = {}
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Remaking a song failed")
            async with self:
                self.error = t["failed"] + str(e)
                self.confirming = bool(self._pending)  # the words stay, to try again
        finally:
            async with self:
                self.busy, self.stage = False, ""

    @rx.event(background=True)
    async def again(self, draft: str):
        """The same take made again: what its record says was asked, with a new random seed."""
        async with self:
            t = self.t
            if self.busy:
                return
            taken = [row.title for row in self.takes]
            engine_ok = bool(self.engine.get("ok"))
            self.busy, self.error, self.stage = True, "", t["stage_writing"]
        try:
            take, rec = drafts.info(draft), drafts.making(draft)
            if take is None or rec is None:
                raise FileNotFoundError(t["gone"])
            title = _numbered(str(take.get("title") or ""), taken)
            again_of = {"id": draft, "title": take.get("title") or ""}
            if rec.get("to") == "composer":
                made = await asyncio.to_thread(_compose_again, take, rec, title, again_of)
                async with self:
                    self.takes = [_row(made), *self.takes]
                return
            if not engine_ok:
                raise RuntimeError(t["need_engine"])
            request = dict(rec.get("request") or {})
            spec = {k: request[k] for k in AGAIN_KEYS if k in request}
            if spec.get("task") in ("cover", "repaint"):
                path = await asyncio.to_thread(_recording_of, request.get("source") or {}, take)
                if path is None:
                    raise FileNotFoundError(t["again_gone"])
                spec["audio_b64"] = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode()
                spec["audio_format"] = path.suffix.lstrip(".").lower() or "mp3"
            song = ai.music(spec)
            mp3 = await self._follow(song, t)
            record = making.record(
                str(rec.get("kind") or take.get("origin") or "sung"),
                str(rec.get("words") or ""),
                rec.get("producer"),
                "engine",
                request,
                engine=making.engine_said(song),
                listening=rec.get("listening"),
                lyrics_from=rec.get("lyrics_from"),
                again_of=again_of,
            )
            info = {k: take[k] for k in ("origin", "rights", "words", "model", "why", "mood", "from_ref", "from_title", "plan", "lyrics", "caption", "language") if k in take}
            info.update(title=title, engine=song.models, bpm=_whole(song.metas.get("bpm"), _whole(take.get("bpm"))), key=_clean_meta(song.metas.get("keyscale")) or str(take.get("key") or ""))
            made = await asyncio.to_thread(drafts.take_engine, mp3, info, record)
            await self._add_compared(made, _recording_from(rec.get("compare") or {}))
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Making a take again failed")
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


def _measured(path: Path) -> dict[str, Any]:
    """What a recording is, as measured here: for the producer (``facts``) and to compare with."""
    found = remake.analyse(path)
    return {"facts": found.facts(), "bpm": round(found.bpm, 1), "key": f"{found.key} {found.mode}", "seconds": round(found.seconds, 2)}


def _recording_from(compare: dict[str, Any]) -> dict[str, Any] | None:
    """The recording's measures kept in a record's comparison (to measure a take made again)."""
    pairs = [compare.get(k) for k in ("bpm", "key", "seconds")]
    if not all(isinstance(pair, list) and len(pair) == 2 for pair in pairs):
        return None
    return {"bpm": pairs[0][0], "key": pairs[1][0], "seconds": pairs[2][0]}


def _same_words(text: str) -> str:
    return "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())


def _recording_of(source: dict[str, Any], take: dict[str, Any]) -> Path | None:
    """The recording a take was made from, if it is still here: another take, an upload, or a
    library song."""
    if source.get("draft"):
        return drafts.audio_path(str(source["draft"]))
    if source.get("upload"):
        path = drafts.data_dir() / "uploads" / Path(str(source["upload"])).name
        return path if path.is_file() else None
    ref = source.get("ref") or take.get("from_ref")
    if ref:
        path, _ = library.source_file(str(ref))
        return path if path is not None and path.is_file() else None
    return None


def _compose_again(take: dict[str, Any], rec: dict[str, Any], title: str, again_of: dict[str, Any]) -> dict[str, Any]:
    """A composed take again: the same brief, a new seed."""
    fields = {f.name for f in dataclasses.fields(Brief)}
    values = {k: v for k, v in (rec.get("request") or {}).items() if k in fields}
    if isinstance(values.get("motif"), list):
        values["motif"] = tuple(values["motif"])
    brief = dataclasses.replace(Brief(**values), title=title)
    seed = secrets.randbelow(1 << 30)
    record = making.record(str(rec.get("kind") or "composed"), str(rec.get("words") or ""), rec.get("producer"), "composer", {**dataclasses.asdict(brief), "seed": seed}, again_of=again_of)
    return drafts.take_composed(brief, seed, str(take.get("words") or ""), str(take.get("model") or ""), str(take.get("why") or ""), record)


# ------------------------------------------------------------------ How a take was made


class Making(Studio):
    """A take's making record: who decided with which model, what the producer was told and
    answered, and what went to the music engine."""

    record_open: bool = False
    record_title: str = ""
    record: dict[str, Any] = {}

    @rx.var
    def record_parts(self) -> list[making.Part]:
        return making.parts(self.record, self.t)

    @rx.var
    def record_old(self) -> bool:
        return bool(self.record.get("old"))

    record_checking: str = ""  # while the AI listens to the take: how far it is

    @rx.var
    def record_can_check(self) -> bool:
        """A sung take nobody counted the lines of yet."""
        request = self.record.get("request") or {}
        sung = str(request.get("lyrics") or "").strip().lower() not in ("", "[instrumental]")
        lines = (self.record.get("compare") or {}).get("lines")
        return sung and not self.record.get("old") and not lines

    @rx.event(background=True)
    async def check_lines(self):
        """The AI listens to the take and counts the lines of its lyrics it hears sung."""
        async with self:
            t = self.t
            draft = str(self.record.get("id") or "")
            if not draft or self.record_checking:
                return
            take = drafts.info(draft) or {}
            words = str(take.get("lyrics") or "")
            texts = [line for group in lyrics.sections(words) for line in group]
            language = listen.language_of(take, words)
            self.record_checking = _fill(t["mk_checking"], p=0)

        async def told(job: listen.Progress) -> None:
            async with self:
                self.record_checking = _fill(t["mk_checking"], p=int(job.done * 100))

        try:
            found = await listen.hear(draft, language, told)
            lines = await asyncio.to_thread(_matched, texts, found)
            compare = dict((drafts.making(draft) or {}).get("compare") or {})
            compare["lines"] = [sum(1 for line in lines if line.heard), len(texts)]
            await asyncio.to_thread(drafts.update_making, draft, compare=compare)
            async with self:
                if str(self.record.get("id") or "") == draft:
                    self.record = making.of_take(drafts.info(draft) or {}, drafts.making(draft))
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Counting the lines sung failed")
            async with self:
                self.error = t["failed"] + str(e)
        finally:
            async with self:
                self.record_checking = ""

    @rx.event
    def open_record(self, draft: str):
        take = drafts.info(draft)
        if take is None:
            return rx.toast.error(self.t["gone"])
        self.record = making.of_take(take, drafts.making(draft))
        self.record_title = str(take.get("title") or "")
        self.record_open = True
        return None

    @rx.event
    def close_record(self):
        self.record_open = False

    @rx.event
    def copy_record(self):
        old = self.t["mk_old"] if self.record.get("old") else ""
        return [rx.set_clipboard(making.as_text(self.record_title, making.parts(self.record, self.t), old)), rx.toast.success(self.t["mk_copied"])]


# ------------------------------------------------------------------ One part made again


class Patch(Studio):
    """Remake one part of a take (ACE-Step's repaint): the rest stays exactly as it is."""

    patch_open: bool = False
    patch_draft: str = ""
    patch_title: str = ""
    patch_seconds: float = 0.0
    patch_start: str = ""
    patch_end: str = ""
    patch_lyrics: str = ""
    patch_caption: str = ""
    patch_mode: str = "balanced"
    patch_error: str = ""
    patch_version: int = 0  # a take opened: the boxes show its words afresh
    _patch_language: str = ""

    @rx.event
    def open_patch(self, draft: str):
        take = drafts.info(draft)
        if take is None:
            return rx.toast.error(self.t["gone"])
        request = (drafts.making(draft) or {}).get("request") or {}
        self.patch_draft, self.patch_title = draft, str(take.get("title") or "")
        self.patch_seconds = float(take.get("seconds") or 0)
        self.patch_lyrics = str(request.get("lyrics") or take.get("lyrics") or "")
        self.patch_caption = str(request.get("caption") or take.get("caption") or "")
        self._patch_language = str(request.get("language") or take.get("language") or ("zh" if self.lang == "zh" else "en"))
        self.patch_start, self.patch_end, self.patch_mode, self.patch_error = "", "", "balanced", ""
        self.patch_version += 1
        self.patch_open = True
        return None

    @rx.event
    def close_patch(self):
        self.patch_open = False

    @rx.event
    def set_patch_start(self, value: str):
        self.patch_start, self.patch_error = value, ""

    @rx.event
    def set_patch_end(self, value: str):
        self.patch_end, self.patch_error = value, ""

    @rx.event
    def mark_start(self, at: float):
        self.patch_start, self.patch_error = _plain_clock(float(at or 0)), ""

    @rx.event
    def mark_end(self, at: float):
        self.patch_end, self.patch_error = _plain_clock(float(at or 0)), ""

    @rx.event
    def set_patch_lyrics(self, value: str):
        self.patch_lyrics = value

    @rx.event
    def set_patch_caption(self, value: str):
        self.patch_caption = value

    @rx.event
    def set_patch_mode(self, value: str):
        self.patch_mode = value if value in ("balanced", "aggressive") else "balanced"

    @rx.event(background=True)
    async def make_patch(self):
        async with self:
            t = self.t
            if self.busy:
                return
            if not self.engine.get("ok"):
                self.patch_error = t["need_engine"]
                return
            start, end = _seconds_of(self.patch_start), _seconds_of(self.patch_end)
            if start is None or end is None or not (0 <= start < end <= self.patch_seconds + 0.5) or not (PATCH_SHORTEST <= end - start <= PATCH_LONGEST):
                self.patch_error = t["patch_bad"]
                return
            draft, words, caption, mode, language = self.patch_draft, self.patch_lyrics, self.patch_caption, self.patch_mode, self._patch_language
            self.patch_open, self.patch_error = False, ""
            self.busy, self.error, self.stage = True, "", t["stage_writing"]
        try:
            take, path = drafts.info(draft), drafts.audio_path(draft)
            if take is None or path is None:
                raise FileNotFoundError(t["gone"])
            spec = {
                "task": "repaint",
                "caption": caption,
                "lyrics": words.strip() or "[Instrumental]",
                "language": language,
                "audio_b64": base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode(),
                "audio_format": "mp3",
                "repaint_start": round(start, 2),
                "repaint_end": round(end, 2),
                "repaint_mode": mode,
            }
            song = ai.music(spec)
            mp3 = await self._follow(song, t)
            a, b = _plain_clock(start), _plain_clock(end)
            said = _fill(t["patch_words"], a=a, b=b)
            request = {k: v for k, v in spec.items() if k != "audio_b64"}
            request["source"] = {"draft": draft, "title": take.get("title") or ""}
            record = making.record("repaint", said, None, "engine", request, engine=making.engine_said(song))
            info = {k: take[k] for k in ("origin", "rights", "bpm", "key", "from_ref") if k in take}
            info.update(
                title=_fill(t["patch_title"], title=take.get("title") or "", a=a, b=b),
                words=said,
                model="",
                why=said,
                mood=caption[:120],
                from_title=take.get("title") or "",
                plan={"repaint": [round(start, 2), round(end, 2)], "mode": mode},
                lyrics=spec["lyrics"],
                caption=caption,
                language=language,
                engine=song.models,
            )
            made = await asyncio.to_thread(drafts.take_engine, mp3, info, record)
            async with self:
                self.takes = [_row(made), *self.takes]
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Remaking a part failed")
            async with self:
                self.error = t["failed"] + str(e)
        finally:
            async with self:
                self.busy, self.stage = False, ""


def _seconds_of(text: str) -> float | None:
    """A time as written: ``1:05``, ``1:05.5`` or ``65``."""
    text = str(text or "").strip()
    if not text:
        return None
    if ":" in text:
        return lyrics.read_clock(text)
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value >= 0 else None


# ------------------------------------------------------------------ Make Video

PLAYER = "document.getElementById('mv-audio')"


def _play_from(at: float) -> str:
    return f"(() => {{ const a = {PLAYER}; if (a) {{ a.currentTime = {max(0.0, at):.2f}; a.play(); }} }})()"


@dataclasses.dataclass
class Cue:
    at: float
    clock: str
    line: str
    end: float = 0.0  # when its singing ends, if the AI heard it
    heard: int = -1  # 1 the AI heard it sung, 0 it didn't (left out of the video), -1 nobody listened or a person timed it


def _cues(lines: list[lyrics.Line]) -> list[Cue]:
    return [Cue(round(line.at, 2), lyrics.clock(line.at), line.text, line.end, -1 if line.heard is None else int(line.heard)) for line in lines]


def _line(cue: Cue) -> lyrics.Line:
    return lyrics.Line(cue.at, cue.line, cue.end, None if cue.heard < 0 else bool(cue.heard))


def _at(cue: Cue, at: float, seconds: float, by_hand: bool = True) -> Cue:
    """The line moved to ``at``. Moved by hand, it is shown even if the AI didn't hear it."""
    at = round(min(max(0.0, at), seconds or at), 2)
    end = round(cue.end + at - cue.at, 2) if cue.end > 0 else 0.0
    return Cue(at, lyrics.clock(at), cue.line, end, -1 if by_hand else cue.heard)


def _about(take: dict[str, Any], lang: str) -> str:
    """The video's small line: what kind of music, its tempo and key."""
    t = TEXT.get(lang, TEXT["zh"])
    kind = {"sung": t["sung"], "cover": t["cover"]}.get(take.get("origin") or "") or STYLE_NAMES.get(lang, STYLE_NAMES["zh"]).get(take.get("style") or "", "")
    bpm = _whole(take.get("bpm"))
    key = str(take.get("key") or "").replace("♭", "b").replace("♯", "#")  # not in every font
    return " · ".join(part for part in (kind, f"{bpm} BPM" if bpm else "", key) if part)


def _guessed(draft: str, words: str) -> tuple[list[lyrics.Line], float]:
    """A first guess at when each line of ``words`` is sung in the take, and the take's length."""
    path = drafts.audio_path(draft)
    if path is None:
        return [], 0.0
    rate, step = 8000, 4000  # the level every half second is enough
    mono = remake.decode(path, rate, 1).ravel()
    level = np.sqrt((mono[: mono.size // step * step].reshape(-1, step) ** 2).mean(axis=1))
    seconds = mono.size / rate
    return lyrics.guess(words, seconds, level, step / rate), seconds


def _matched(texts: list[str], found: dict[str, Any]) -> list[lyrics.Line]:
    """The lines put where the AI heard them sung."""
    return lyrics.align(texts, [(float(w[0]), float(w[1]), str(w[2])) for w in found.get("words") or []], float(found.get("seconds") or 0))


class Video(Studio):
    """Make Video: a take as a 1080p MP4 for YouTube, with its lyrics timed by ear."""

    film: str = ""  # the take whose video is open
    film_open: bool = False
    film_title: str = ""
    film_artist: str = ""
    film_about: str = ""
    look: str = "bars"
    motion: bool = True
    show_lyrics: bool = True
    cues: list[Cue] = []
    timed: str = ""  # where the times came from: guess, lrc, tap, hand, saved
    tap: int = -1  # the line the next tap times; -1 when nobody is tapping
    lrc: str = ""
    lrc_open: bool = False
    seconds: float = 0.0
    rendering: str = ""  # the take whose video is being made
    progress: int = 0
    film_error: str = ""
    made: dict[str, Any] = {}  # what the open take's video was made with
    listening: str = ""  # the take the AI is listening to
    listen_note: str = ""
    ears: bool = False  # the speech model is here: listening needs no download
    _words: str = ""  # the take's lyrics as they came, tags and all
    _language: str = ""

    @rx.var
    def film_version(self) -> str:
        return str(self.made.get("made") or "")

    @rx.var
    def film_size(self) -> str:
        size = float(self.made.get("bytes") or 0)
        return f"{size / 1e6:.0f} MB" if size else ""

    @rx.var
    def tap_line(self) -> str:
        return self.cues[self.tap].line if 0 <= self.tap < len(self.cues) else ""

    @rx.var
    def tap_place(self) -> str:
        return _fill(self.t["tap_place"], n=self.tap + 1, all=len(self.cues)) if self.tap >= 0 else ""

    @rx.var
    def film_stage(self) -> str:
        return _fill(self.t["film_making"], p=self.progress)

    @rx.var
    def timed_words(self) -> str:
        if not self.cues:
            return self.t["no_lyrics"]
        heard = sum(1 for cue in self.cues if cue.heard == 1)
        return _fill(self.t.get(f"timed_{self.timed}", ""), n=heard, all=len(self.cues))

    @rx.event
    async def open_film(self, draft: str):
        if draft != self.film:
            take = drafts.info(draft)
            if take is None:
                return rx.toast.error(self.t["gone"])
            self.film, self.tap, self.lrc_open, self.film_error = draft, -1, False, ""
            saved = video.settings(draft) or {}
            self._words = "" if str(take.get("lyrics") or "").strip().lower() == "[instrumental]" else str(take.get("lyrics") or "")
            lines, self.seconds = await asyncio.to_thread(_guessed, draft, self._words)
            self.made = saved
            self.film_title = str(saved.get("title") or take.get("title") or "")
            self.film_artist = str(saved.get("artist") or library.MAKER)
            self.film_about = str(saved.get("about") if "about" in saved else _about(take, self.lang))
            self.look = saved.get("look") if saved.get("look") in video.LOOKS else "bars"
            self.motion = bool(saved.get("motion", True))
            self._language = listen.language_of(take, self._words)
            self.ears = await asyncio.to_thread(listen.present)
            found = None if saved.get("lines") else await asyncio.to_thread(listen.heard, draft)
            self.timed = "saved" if saved.get("lines") else "guess"
            if saved.get("lines"):
                lines = [lyrics.Line(float(row[0]), str(row[1]), *(float(row[2]), row[3]) if len(row) > 3 else ()) for row in saved["lines"]]
            elif found and lines:
                lines, self.timed = _matched([line.text for line in lines], found), "heard"
            self.cues = _cues(lines)
            self.show_lyrics = bool(saved.get("lyrics", True)) and bool(lines)
            if self.timed == "guess" and lines and self.ears and not self.listening:
                self.film_open = True
                return Video.listen_film  # the model is here: the AI times the lines at once
        self.film_open = True
        return None

    @rx.event
    def close_film(self):
        self.film_open, self.tap = False, -1

    @rx.event
    def set_film_title(self, value: str):
        self.film_title = value

    @rx.event
    def set_film_artist(self, value: str):
        self.film_artist = value

    @rx.event
    def set_film_about(self, value: str):
        self.film_about = value

    @rx.event
    def set_look(self, value: str):
        self.look = value if value in video.LOOKS else "bars"

    @rx.event
    def set_motion(self, value: str):
        self.motion = value == "on"

    @rx.event
    def set_show_lyrics(self, value: str):
        self.show_lyrics = value == "on" and bool(self.cues)

    # ---------------------------------------------- the lyrics' times

    @rx.event
    def nudge(self, index: int, delta: float):
        if 0 <= index < len(self.cues):
            self.cues[index] = _at(self.cues[index], self.cues[index].at + delta, self.seconds)
            self.timed = "hand"

    @rx.event
    def shift(self, delta: float):
        self.cues = [_at(cue, cue.at + delta, self.seconds, by_hand=False) for cue in self.cues]
        self.timed = "hand"

    @rx.event
    def stamp(self, index: int, at: float):
        """A line starts where the player is."""
        if 0 <= index < len(self.cues):
            self.cues[index] = _at(self.cues[index], at, self.seconds)
            self.timed = "hand"

    @rx.event
    def play_from(self, index: int):
        if 0 <= index < len(self.cues):
            return rx.call_script(_play_from(self.cues[index].at - 0.5))
        return None

    @rx.event
    def tap_start(self):
        if not self.cues:
            return None
        self.tap, self.lrc_open = 0, False
        return rx.call_script(_play_from(0))

    @rx.event
    def tap_mark(self, at: float):
        """The line waiting for its tap starts now."""
        if not 0 <= self.tap < len(self.cues):
            return None
        self.cues[self.tap] = _at(self.cues[self.tap], at, self.seconds)
        self.timed = "tap"
        self.tap += 1
        if self.tap >= len(self.cues):
            self.tap = -1
            return [rx.call_script(f"{PLAYER}?.pause()"), rx.toast.success(self.t["tap_finished"])]
        return None

    @rx.event
    def tap_back(self):
        """One line back, and the music a little before it, to tap it again."""
        if self.tap > 0:
            self.tap -= 1
            before = self.cues[self.tap - 1].at if self.tap > 0 else self.cues[self.tap].at - 3
            return rx.call_script(_play_from(before))
        return None

    @rx.event
    def tap_stop(self):
        self.tap = -1
        return rx.call_script(f"{PLAYER}?.pause()")

    @rx.event
    async def guess_again(self):
        same = [cue.line for cue in self.cues] == [line for group in lyrics.sections(self._words) for line in group]
        words = self._words if same else "\n".join(cue.line for cue in self.cues)
        lines, self.seconds = await asyncio.to_thread(_guessed, self.film, words)
        self.cues, self.timed, self.tap = _cues(lines), "guess", -1

    @rx.event
    def edit_lrc(self):
        self.lrc = lyrics.to_lrc([_line(cue) for cue in self.cues])
        self.lrc_open, self.tap = True, -1

    @rx.event
    def set_lrc(self, value: str):
        self.lrc = value

    @rx.event
    def close_lrc(self):
        self.lrc_open = False

    @rx.event
    async def apply_lrc(self):
        """The lines as written: with times in front (LRC) they keep them; else they go where the AI
        heard them, if it listened, or are guessed."""
        found = None
        if lyrics.has_times(self.lrc):
            lines, self.timed = lyrics.from_lrc(self.lrc), "lrc"
        else:
            self._words = self.lrc
            lines, self.seconds = await asyncio.to_thread(_guessed, self.film, self.lrc)
            found = await asyncio.to_thread(listen.heard, self.film)
            self.timed = "guess"
        if found and lines:
            lines, self.timed = _matched([line.text for line in lines], found), "heard"
        self.cues = _cues(lines)
        self.show_lyrics = bool(lines)
        self.lrc_open = False

    # ---------------------------------------------- the AI listens

    @rx.event(background=True)
    async def listen_film(self):
        """The AI hears what is sung and when, and each line goes where it was heard."""
        async with self:
            t = self.t
            draft, language = self.film, self._language
            texts = [cue.line for cue in self.cues]
            if self.listening or not draft or not texts:
                return
            self.listening, self.listen_note, self.film_error, self.tap = draft, t["listen_wait"], "", -1

        async def heard(job: listen.Progress) -> None:
            async with self:
                self.listen_note = _fill(t[f"listen_{job.phase}"], p=int(job.done * 100), mb=job.note)

        try:
            found = await listen.hear(draft, language, heard)
            lines = await asyncio.to_thread(_matched, texts, found)
            async with self:
                self.ears = True
                if self.film == draft and [cue.line for cue in self.cues] == texts:
                    if any(line.heard for line in lines):
                        self.cues, self.timed = _cues(lines), "heard"
                    else:
                        self.film_error = t["listen_none"]
        except listen.Stopped:
            pass
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Listening failed")
            async with self:
                self.film_error = t["failed"] + str(e)
        finally:
            async with self:
                self.listening, self.listen_note = "", ""

    @rx.event
    def stop_listen(self):
        if self.listening:
            listen.stop(self.listening)

    # ---------------------------------------------- the video

    @rx.event(background=True)
    async def make_film(self):
        async with self:
            t = self.t
            draft = self.film
            if self.rendering or not draft:
                return
            if video.busy(draft):
                self.film_error = t["film_busy"]
                return
            spec = video.Spec(
                title=self.film_title.strip(),
                artist=self.film_artist.strip(),
                about=self.film_about.strip(),
                look=self.look,
                motion=self.motion,
                lines=[_line(cue) for cue in self.cues],
                lyrics=self.show_lyrics,
            )
            self.rendering, self.progress, self.film_error, self.tap = draft, 0, "", -1

        async def heard(fraction: float) -> None:
            async with self:
                self.progress = int(fraction * 100)

        try:
            made = await video.render(draft, spec, heard)
            async with self:
                if self.film == draft:
                    self.made = made
                found = drafts.info(draft)
                self.takes = [_row(found) if row.id == draft and found else row for row in self.takes]
            yield rx.toast.success(t["film_made"])
        except video.Stopped:
            pass
        except Exception as e:  # noqa: BLE001 - said on the page
            logger.exception("Making a video failed")
            async with self:
                self.film_error = t["failed"] + str(e)
        finally:
            async with self:
                self.rendering, self.progress = "", 0

    @rx.event
    def stop_film(self):
        if self.rendering:
            video.stop(self.rendering)
