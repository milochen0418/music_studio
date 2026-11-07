"""The studio's page, on its own and in another app's dialog."""

from __future__ import annotations

import reflex as rx
from reflex.utils.imports import ImportVar
from reflex.vars import VarData
from reflex_components_core.el.elements.inline import A
from reflex_ddns_auth.intent import Intent, IntentState

from music_studio.library import Source
from music_studio.making import Part
from music_studio.state import FINDER, Cue, Making, Studio, Take, Video

T = Studio.t
CARD = "rounded-2xl border border-white/10 bg-slate-900/70 p-4 sm:p-5"
BUTTON = "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-colors"
PRIMARY = f"{BUTTON} bg-amber-400 text-slate-950 hover:bg-amber-300 disabled:opacity-50"
GHOST = f"{BUTTON} border border-slate-700 text-slate-200 hover:border-slate-500"
INPUT = "w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-amber-400 focus:outline-none"
# The backend's origin: the /_studio links are relative to it (two ports on a laptop, one here).
BACKEND = rx.Var(
    _js_expr="getBackendURL(env.UPLOAD).origin",
    _var_data=VarData(imports={"$/utils/state": "getBackendURL", "$/env.json": ImportVar(tag="env", is_default=True)}),
).to(str)


def _header() -> rx.Component:
    return rx.el.header(
        rx.el.div(
            rx.icon("audio-lines", size=22, class_name="text-amber-400"),
            rx.el.span(T["app"], class_name="text-lg font-bold tracking-wide"),
            class_name="flex items-center gap-2",
        ),
        rx.el.button(rx.icon("languages", size=16), T["lang_other"], on_click=Studio.switch_lang, data_testid="lang", class_name="flex items-center gap-1.5 rounded-full border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:border-slate-500"),
        class_name="flex items-center justify-between py-4",
    )


def _tab(name: str, words, icon: str) -> rx.Component:
    return rx.el.button(
        rx.icon(icon, size=16),
        words,
        on_click=Studio.set_tab(name),
        data_testid=f"tab-{name}",
        class_name=rx.cond(Studio.tab == name, f"{BUTTON} bg-slate-100 text-slate-950", f"{BUTTON} text-slate-300 hover:bg-slate-800"),
    )


def _choice(testid: str, chosen, value: str, words, pick, disabled=None, tip=None) -> rx.Component:
    on = chosen == value
    return rx.el.button(
        words,
        on_click=pick(value),
        disabled=disabled,
        title=tip,
        data_testid=f"{testid}-{value}",
        class_name=rx.cond(on, f"{BUTTON} bg-slate-100 text-slate-950 disabled:opacity-40", f"{BUTTON} border border-slate-700 text-slate-300 hover:border-slate-500 disabled:opacity-40"),
    )


def _engine_banner() -> rx.Component:
    return rx.cond(
        Studio.engine_ok,
        rx.el.p(rx.icon("mic-vocal", size=14, class_name="mr-1 inline align-[-2px] text-emerald-300"), Studio.engine_words, data_testid="engine", class_name="mt-3 text-xs text-slate-400"),
        rx.el.div(
            rx.icon("info", size=16, class_name="mt-0.5 shrink-0 text-amber-300"),
            rx.el.div(
                rx.el.span(Studio.engine_words, data_testid="engine"),
                rx.cond(Studio.hub_page != "", rx.el.a(T["open_hub"], " →", href=Studio.hub_page, target="_blank", class_name="ml-2 text-amber-300 hover:underline")),
                class_name="text-sm leading-relaxed text-amber-100/90",
            ),
            class_name="mt-3 flex gap-2 rounded-xl border border-amber-400/30 bg-amber-950/40 px-3 py-2",
        ),
    )


def _voice() -> rx.Component:
    return rx.el.div(
        rx.el.span(T["voice"], class_name="mr-1 text-xs text-slate-400"),
        _choice("voice", Studio.voice, "none", T["voice_none"], Studio.set_voice),
        _choice("voice", Studio.voice, "sing", T["voice_sing"], Studio.set_voice, disabled=~Studio.engine_ok, tip=T["voice_tip"]),
        rx.cond(
            Studio.voice == "sing",
            rx.el.select(
                rx.el.option(T["lang_zh"], value="zh"),
                rx.el.option(T["lang_en"], value="en"),
                rx.el.option(T["lang_ja"], value="ja"),
                rx.el.option(T["lang_ko"], value="ko"),
                value=rx.cond(Studio.lyrics_lang != "", Studio.lyrics_lang, rx.cond(Studio.lang == "zh", "zh", "en")),
                on_change=Studio.set_lyrics_lang,
                data_testid="lyrics-lang",
                class_name=f"{INPUT} w-auto",
                title=T["lyrics_lang"],
            ),
        ),
        class_name="mt-4 flex flex-wrap items-center gap-2",
    )


def _length() -> rx.Component:
    return rx.el.label(
        rx.el.span(T["length"], class_name="mb-1 block text-xs text-slate-400"),
        rx.el.select(
            rx.el.option(T["short"], value="short"),
            rx.el.option(T["medium"], value="medium"),
            rx.el.option(T["long"], value="long"),
            value=Studio.length,
            on_change=Studio.set_length,
            data_testid="length",
            class_name=INPUT,
        ),
        class_name="min-w-0 flex-1",
    )


def _compose() -> rx.Component:
    return rx.el.div(
        rx.el.label(T["words"], html_for="words", class_name="font-semibold"),
        # The box keeps its own text: a value written back per key cuts Chinese input off.
        rx.el.textarea(id="words", default_value=Studio.words, on_change=Studio.set_words, placeholder=T["words_hint"], rows=3, data_testid="words", class_name=f"{INPUT} mt-2 resize-y"),
        rx.el.div(rx.foreach(Studio.scenes, lambda s: rx.el.button(s, on_click=Studio.use_scene(s), class_name="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-amber-400")), class_name="mt-3 flex flex-wrap gap-2"),
        _voice(),
        rx.el.div(
            rx.el.label(
                rx.el.span(T["style"], class_name="mb-1 block text-xs text-slate-400"),
                rx.el.select(rx.foreach(Studio.style_rows, lambda row: rx.el.option(row[1], value=row[0])), value=Studio.style, on_change=Studio.set_style, data_testid="style", class_name=INPUT),
                class_name="min-w-0 flex-1",
            ),
            _length(),
            class_name="mt-4 flex flex-wrap gap-3",
        ),
        rx.el.button(rx.icon("sparkles", size=16), rx.cond(Studio.busy, T["making"], T["make"]), on_click=Studio.make, disabled=Studio.busy, data_testid="make", class_name=f"{PRIMARY} mt-4"),
        class_name=CARD,
    )


def _source_row(row: Source) -> rx.Component:
    return rx.el.button(
        rx.cond(Studio.source_ref == row.ref, rx.icon("circle-check", size=16, class_name="shrink-0 text-amber-400"), rx.icon("music-2", size=16, class_name="shrink-0 text-slate-500")),
        rx.el.span(row.title, class_name="min-w-0 flex-1 truncate text-left"),
        # Where it came from: a version made here may carry the same title as its original.
        rx.el.span(
            rx.cond(row.origin == "music-studio", T["app"], rx.cond(row.origin == "youtube-to-mp3", "YouTube", row.origin)),
            data_testid="source-from",
            class_name="shrink-0 rounded-full bg-slate-800 px-2 py-0.5 text-[11px] text-slate-400",
        ),
        rx.el.span(row.clock, class_name="shrink-0 font-mono text-xs text-slate-400"),
        on_click=Studio.choose_source(row.ref, row.title),
        data_testid="source",
        class_name=rx.cond(Studio.source_ref == row.ref, "flex w-full items-center gap-2 rounded-lg bg-slate-800 px-3 py-2 text-sm", "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-slate-800/60"),
    )


def _finder_button() -> rx.Component:
    start = Intent.start(None, FINDER, on_update=Studio.finder_update, on_cancel=Studio.finder_closed, keep_alive=True, label="YouTube")
    return rx.el.button(rx.icon("search", size=15), T["find"], on_click=rx.cond(IntentState.open_actions.contains(FINDER), Intent.show(FINDER), start), data_testid="find", class_name=GHOST)


def _step(number: str, words, html_for: str = "") -> rx.Component:
    return rx.el.label(
        rx.el.span(number, class_name="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-400 text-[11px] font-bold text-slate-950"),
        words,
        html_for=html_for or None,
        class_name="flex items-center gap-2 font-semibold",
    )


def _note(words, testid: str) -> rx.Component:
    return rx.el.p(words, data_testid=testid, class_name="mt-2 text-xs leading-relaxed text-slate-400")


def _remake() -> rx.Component:
    method = rx.cond(Studio.remaking, "remake", "tweak")
    return rx.el.div(
        _step("1", T["source"]),
        rx.el.div(
            rx.cond(Studio.sources.length() > 0, rx.foreach(Studio.sources, _source_row), rx.el.p(T["no_source"], class_name="p-3 text-sm text-slate-400")),
            data_testid="sources",
            class_name="mt-2 max-h-60 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/60 p-1",
        ),
        rx.el.div(
            _finder_button(),
            rx.upload.root(
                rx.el.span(rx.icon("upload", size=15), T["upload"], class_name=GHOST),
                id="song",
                accept={"audio/*": [".mp3", ".wav", ".m4a", ".flac", ".ogg"]},
                max_files=1,
                multiple=False,
                on_drop=Studio.uploaded(rx.upload_files(upload_id="song")),
                class_name="cursor-pointer",
            ),
            rx.cond(Studio.upload != "", rx.el.span(rx.icon("circle-check", size=15, class_name="text-amber-400"), Studio.source_title, class_name="inline-flex items-center gap-1.5 text-sm text-slate-300")),
            class_name="mt-3 flex flex-wrap items-center gap-2",
        ),
        rx.el.div(_step("2", T["method"]), class_name="mt-6"),
        rx.el.div(
            _choice("method", method, "tweak", T["method_tweak"], Studio.set_method),
            _choice("method", method, "remake", T["method_remake"], Studio.set_method, disabled=~Studio.engine_ok, tip=T["method_tip"]),
            class_name="mt-2 flex flex-wrap items-center gap-2",
        ),
        _note(rx.cond(Studio.remaking, T["method_remake_note"], T["method_tweak_note"]), "method-note"),
        rx.cond(
            Studio.remaking,
            rx.el.div(
                rx.el.div(
                    rx.el.span(T["vocals"], class_name="mr-1 text-xs text-slate-400"),
                    _choice("vocals", Studio.vocals, "keep", T["vocals_keep"], Studio.set_vocals),
                    _choice("vocals", Studio.vocals, "remove", T["vocals_remove"], Studio.set_vocals),
                    _choice("vocals", Studio.vocals, "instrument", T["vocals_instrument"], Studio.set_vocals),
                    class_name="flex flex-wrap items-center gap-2",
                ),
                _note(Studio.vocals_note, "vocals-note"),
                class_name="mt-3 rounded-xl border border-slate-800 bg-slate-950/40 p-3",
            ),
        ),
        rx.el.div(_step("3", T["how"], "how"), class_name="mt-6"),
        rx.el.textarea(id="how", default_value=Studio.how, on_change=Studio.set_how, placeholder=rx.cond(Studio.remaking, T["how_hint_remake"], T["how_hint"]), rows=2, data_testid="how", class_name=f"{INPUT} mt-2 resize-y"),
        rx.cond(
            Studio.remaking,
            rx.el.p(T["remake_length"], data_testid="remake-length", class_name="mt-3 text-xs text-slate-400"),
            rx.el.div(_length(), class_name="mt-3 flex max-w-xs"),
        ),
        rx.el.p(rx.icon("info", size=14, class_name="mr-1 inline align-[-2px]"), T["rights_note"], class_name="mt-4 text-xs leading-relaxed text-amber-200/80"),
        rx.el.button(rx.icon("wand-sparkles", size=16), rx.cond(Studio.busy, T["making"], T["change"]), on_click=Studio.change, disabled=Studio.busy, data_testid="change", class_name=f"{PRIMARY} mt-4"),
        class_name=CARD,
    )


def _take(row: Take) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.image(src=BACKEND + "/_studio/cover/" + row.id + ".png", alt="", class_name="h-14 w-14 shrink-0 rounded-lg"),
            rx.el.div(
                rx.el.div(row.title, class_name="truncate font-semibold"),
                rx.el.div(row.key, " · ", row.bpm.to(str), " BPM · ", row.clock, class_name="text-xs text-slate-400"),
                rx.cond(row.loops, rx.el.div(rx.icon("repeat", size=12), T["loops"], class_name="mt-0.5 inline-flex items-center gap-1 text-[11px] text-emerald-300")),
                class_name="min-w-0 flex-1",
            ),
            class_name="flex items-center gap-3",
        ),
        rx.image(src=row.wave, alt="", class_name="mt-3 h-8 w-full opacity-70"),
        rx.el.audio(src=BACKEND + "/_studio/take/" + row.id + ".mp3", controls=True, preload="none", class_name="mt-2 h-9 w-full"),
        rx.cond(row.origin == "sung", rx.el.p(rx.icon("mic-vocal", size=12, class_name="mr-1 inline align-[-1px]"), T["sung"], class_name="mt-2 text-xs text-pink-300")),
        rx.cond(row.origin == "cover", rx.el.p(rx.icon("wand-sparkles", size=12, class_name="mr-1 inline align-[-1px]"), T["cover"], class_name="mt-2 text-xs text-violet-300")),
        rx.cond(row.why != "", rx.el.p("“", row.why, "”", class_name="mt-2 text-sm italic text-slate-300")),
        rx.cond(row.lyrics != "", rx.el.details(rx.el.summary("♪ ", T["lyrics"], class_name="cursor-pointer text-xs text-slate-400"), rx.el.pre(row.lyrics, class_name="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap font-sans text-xs text-slate-300"), class_name="mt-2")),
        rx.cond(row.from_title != "", rx.el.p(T["from"], " ", row.from_title, class_name="mt-1 truncate text-xs text-slate-400")),
        rx.cond(row.rights != "own", rx.el.p(rx.icon("triangle-alert", size=12, class_name="mr-1 inline align-[-1px]"), T["rights_mark"], class_name="mt-1 text-xs text-amber-300")),
        rx.el.div(
            rx.cond(
                row.ref != "",
                rx.el.span(rx.icon("check", size=14), T["kept"], class_name="inline-flex items-center gap-1 text-sm text-emerald-300"),
                rx.el.button(rx.icon("bookmark-plus", size=15), rx.cond(Studio.in_dialog, T["use"], T["keep"]), on_click=Studio.keep(row.id), data_testid="keep", class_name=PRIMARY),
            ),
            rx.cond(~Studio.in_dialog, _video_button(row)),
            rx.cond(~Studio.in_dialog, _making_button(row)),
            rx.cond(
                row.model != "",
                rx.el.span(row.model, class_name="ml-auto truncate font-mono text-[11px] text-slate-500"),
                # A take that says why it is as it is (nothing was asked for) didn't wait on the AI.
                rx.cond(row.why == "", rx.el.span(T["by_keywords"], class_name="ml-auto text-[11px] text-slate-500")),
            ),
            class_name="mt-3 flex flex-wrap items-center gap-3",
        ),
        data_testid="take",
        class_name=CARD,
    )


def _video_button(row: Take) -> rx.Component:
    return rx.el.button(
        rx.icon("clapperboard", size=15),
        rx.cond(Video.rendering == row.id, Video.film_stage, T["make_video"]),
        rx.cond(row.has_video, rx.el.span(rx.icon("film", size=12), T["video_ready"], class_name="ml-1 inline-flex items-center gap-1 rounded-full bg-sky-400/15 px-2 py-0.5 text-[11px] text-sky-200")),
        on_click=Video.open_film(row.id),
        data_testid="make-video",
        class_name=GHOST,
    )


# ------------------------------------------------------------------ How it was made


def _making_button(row: Take) -> rx.Component:
    return rx.el.button(rx.icon("notebook-text", size=15), T["mk_button"], on_click=Making.open_record(row.id), data_testid="making", class_name=GHOST)


def _record_part(part: Part) -> rx.Component:
    text = rx.cond(
        part.mono,
        rx.el.pre(part.body, class_name="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950/70 p-3 font-mono text-xs text-slate-200"),
        rx.el.p(part.body, class_name="mt-1 whitespace-pre-wrap text-sm text-slate-200"),
    )
    return rx.cond(
        part.fold,
        rx.el.details(rx.el.summary(part.head, class_name="cursor-pointer text-sm font-semibold text-amber-300"), text, data_testid="making-part", class_name="mt-4"),
        rx.el.div(rx.el.h3(part.head, class_name="text-sm font-semibold text-amber-300"), text, data_testid="making-part", class_name="mt-4"),
    )


def _record_dialog() -> rx.Component:
    return rx.cond(
        Making.record_open,
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.el.h2(rx.icon("notebook-text", size=20, class_name="text-amber-400"), T["mk_head"], class_name="flex items-center gap-2 text-lg font-bold"),
                        rx.el.p(Making.record_title, class_name="mt-1 truncate text-sm text-slate-300"),
                        class_name="min-w-0",
                    ),
                    rx.el.button(rx.icon("x", size=18), on_click=Making.close_record, title=T["close"], data_testid="making-close", class_name="rounded-full p-2 text-slate-300 hover:bg-slate-800"),
                    class_name="flex items-start justify-between gap-3",
                ),
                rx.el.p(T["mk_note"], class_name="mt-2 text-xs text-slate-400"),
                rx.cond(Making.record_old, rx.el.p(T["mk_old"], data_testid="making-old", class_name="mt-3 rounded-xl bg-amber-400/10 px-3 py-2 text-sm text-amber-200")),
                rx.foreach(Making.record_parts, _record_part),
                rx.el.div(
                    rx.el.button(rx.icon("copy", size=15), T["mk_copy"], on_click=Making.copy_record, data_testid="making-copy", class_name=GHOST),
                    rx.el.button(T["close"], on_click=Making.close_record, class_name=GHOST),
                    class_name="mt-5 flex flex-wrap justify-end gap-3",
                ),
                data_testid="making-dialog",
                class_name="relative mx-auto my-4 w-full max-w-3xl rounded-2xl border border-white/10 bg-slate-900 p-4 text-slate-100 shadow-2xl sm:my-8 sm:p-6",
            ),
            class_name="fixed inset-0 z-50 overflow-y-auto bg-slate-950/80 px-3 backdrop-blur-sm",
        ),
    )


# ------------------------------------------------------------------ Make Video

# The dialog's player, read in the browser the moment a button is pressed: where the song is.
PLAYING = "(document.getElementById('mv-audio')?.currentTime ?? 0)"
FILM_URL = BACKEND + "/_studio/video/" + Video.film + ".mp4?v=" + Video.film_version
LABEL = "mb-1 block text-xs text-slate-400"
SMALL = "inline-flex items-center justify-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:border-slate-500 disabled:opacity-40"
# While the player plays: the row of the line being sung lights up and its words show above. The
# space bar taps while tapping along; Escape closes the dialog.
FILM_JS = """
(() => {
  if (window.__musicVideo) return;
  window.__musicVideo = true;
  document.addEventListener("timeupdate", (e) => {
    const player = e.target;
    if (!player || player.id !== "mv-audio") return;
    let on = null, best = -1;
    document.querySelectorAll("#mv-cues [data-at]").forEach((row) => {
      const at = parseFloat(row.dataset.at);
      if (at <= player.currentTime + 0.05 && at >= best) { best = at; on = row; }
    });
    document.querySelectorAll("#mv-cues [data-now]").forEach((row) => { if (row !== on) row.removeAttribute("data-now"); });
    if (on) on.setAttribute("data-now", "");
    const now = document.getElementById("mv-now");
    if (now) now.textContent = on ? on.dataset.line : "";
  }, true);
  document.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    if (e.repeat || ["INPUT", "TEXTAREA", "SELECT"].includes(tag) || (e.target && e.target.isContentEditable)) return;
    if (e.key === " ") {
      const tap = document.getElementById("mv-tap");
      if (!tap) return;
      e.preventDefault();
      if (document.activeElement === tap) tap.blur();
      tap.click();
    } else if (e.key === "Escape") {
      document.getElementById("mv-close")?.click();
    }
  });
})();
"""


def _playing_spec(e: rx.Var) -> tuple[rx.Var[float]]:
    return (rx.Var(PLAYING).to(float),)


class AtPlayer(rx.el.Button):
    """A button that tells its handler where the dialog's player is."""

    on_click: rx.EventHandler[_playing_spec]


def _text_field(label, testid: str, value, setter) -> rx.Component:
    return rx.el.label(
        rx.el.span(label, class_name=LABEL),
        # Keyed by the take and keeping its own text: written back per key, Chinese input breaks.
        rx.el.input(default_value=value, on_change=setter, key=Video.film + testid, data_testid=testid, class_name=INPUT),
        class_name="block",
    )


def _film_preview() -> rx.Component:
    making = Video.rendering == Video.film
    return rx.el.div(
        rx.cond(
            Video.film_version != "",
            rx.el.video(src=FILM_URL, controls=True, preload="metadata", data_testid="video-player", class_name="aspect-video w-full rounded-xl bg-black"),
            rx.el.div(
                rx.image(src=BACKEND + "/_studio/cover/" + Video.film + ".png", alt="", class_name="h-24 w-24 rounded-xl"),
                rx.el.p(T["film_none"], class_name="max-w-sm text-center text-sm leading-relaxed text-slate-400"),
                class_name="flex aspect-video w-full flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-slate-700 bg-slate-950/60 p-6",
            ),
        ),
        rx.cond(
            making,
            rx.el.div(
                rx.el.div(rx.el.div(class_name="h-full rounded-full bg-amber-400 transition-all", style={"width": f"{Video.progress}%"}), class_name="h-2 w-full overflow-hidden rounded-full bg-slate-800"),
                rx.el.div(
                    rx.el.span(rx.spinner(size="2"), Video.film_stage, data_testid="video-stage", class_name="inline-flex items-center gap-2 text-sm text-slate-300"),
                    rx.el.button(rx.icon("square", size=13), T["stop"], on_click=Video.stop_film, data_testid="video-stop", class_name=GHOST),
                    class_name="mt-3 flex flex-wrap items-center justify-between gap-3",
                ),
                class_name="mt-4",
            ),
            rx.el.div(
                rx.el.button(
                    rx.icon("clapperboard", size=16),
                    rx.cond(Video.film_version != "", T["remake_film"], T["make_film"]),
                    on_click=Video.make_film,
                    disabled=(Video.rendering != "") | (Video.listening == Video.film),
                    data_testid="video-make",
                    class_name=PRIMARY,
                ),
                rx.cond(
                    Video.film_version != "",
                    A.create(rx.icon("download", size=16), T["download"], " · ", Video.film_size, href=FILM_URL + "&download=1", download=True, data_testid="video-download", class_name=GHOST),
                ),
                class_name="mt-4 flex flex-wrap items-center gap-3",
            ),
        ),
        rx.cond(Video.film_error != "", rx.el.p(Video.film_error, data_testid="video-error", class_name="mt-3 rounded-xl bg-rose-950/60 px-3 py-2 text-sm text-rose-200")),
    )


def _film_settings() -> rx.Component:
    return rx.el.div(
        _text_field(T["film_title"], "video-title", Video.film_title, Video.set_film_title),
        _text_field(T["film_artist"], "video-artist", Video.film_artist, Video.set_film_artist),
        _text_field(T["film_about"], "video-about", Video.film_about, Video.set_film_about),
        rx.el.div(
            rx.el.span(T["look"], class_name=LABEL),
            rx.el.div(_choice("look", Video.look, "bars", T["look_bars"], Video.set_look), _choice("look", Video.look, "wave", T["look_wave"], Video.set_look), class_name="flex flex-wrap gap-2"),
        ),
        rx.el.div(
            rx.el.span(T["motion"], class_name=LABEL),
            rx.el.div(
                _choice("motion", rx.cond(Video.motion, "on", "off"), "on", T["motion_on"], Video.set_motion),
                _choice("motion", rx.cond(Video.motion, "on", "off"), "off", T["motion_off"], Video.set_motion),
                class_name="flex flex-wrap gap-2",
            ),
        ),
        rx.el.div(
            rx.el.span(T["show_lyrics"], class_name=LABEL),
            rx.el.div(
                _choice("lyrics", rx.cond(Video.show_lyrics, "on", "off"), "on", T["lyrics_on"], Video.set_show_lyrics, disabled=Video.cues.length() == 0),
                _choice("lyrics", rx.cond(Video.show_lyrics, "on", "off"), "off", T["lyrics_off"], Video.set_show_lyrics),
                class_name="flex flex-wrap gap-2",
            ),
        ),
        class_name="space-y-4",
    )


def _cue_row(cue: Cue, index) -> rx.Component:
    return rx.el.div(
        rx.el.button(rx.icon("play", size=11), cue.clock, on_click=Video.play_from(index), title=T["play_here"], data_testid="cue-play", class_name="inline-flex w-[5.5rem] shrink-0 items-center gap-1.5 rounded-md px-1.5 py-1 font-mono text-xs text-amber-200 hover:bg-slate-800"),
        rx.el.span(cue.line, class_name=rx.cond(cue.heard == 0, "min-w-0 flex-1 truncate text-sm text-slate-500 line-through decoration-slate-600", "min-w-0 flex-1 truncate text-sm")),
        rx.cond(cue.heard == 0, rx.el.span(rx.icon("ear-off", size=12), T["not_heard"], title=T["not_heard_tip"], data_testid="cue-unheard", class_name="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-400/10 px-2 py-0.5 text-[11px] text-amber-200")),
        rx.el.button(rx.icon("minus", size=12), on_click=Video.nudge(index, -0.25), title="-0.25 s", data_testid="cue-earlier", class_name=SMALL),
        rx.el.button(rx.icon("plus", size=12), on_click=Video.nudge(index, 0.25), title="+0.25 s", data_testid="cue-later", class_name=SMALL),
        AtPlayer.create(rx.icon("timer", size=13), on_click=Video.stamp(index), title=T["stamp"], data_testid="cue-stamp", class_name=SMALL),
        data_at=cue.at,
        data_line=cue.line,
        data_testid="cue",
        class_name=rx.cond(
            Video.tap == index,
            "flex items-center gap-2 rounded-lg bg-amber-400/20 px-2 py-1 ring-1 ring-amber-400/60",
            "flex items-center gap-2 rounded-lg px-2 py-1 [&[data-now]]:bg-sky-400/15 hover:bg-slate-800/60",
        ),
    )


def _film_lyrics() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.h3(rx.icon("captions", size=16, class_name="text-amber-400"), T["show_lyrics"], class_name="flex items-center gap-2 font-semibold"),
            rx.el.p(Video.timed_words, data_testid="timed", class_name="text-xs text-slate-400"),
            class_name="flex flex-wrap items-baseline gap-x-3 gap-y-1",
        ),
        rx.cond(
            Video.listening == Video.film,
            rx.el.div(
                rx.el.span(rx.spinner(size="2"), Video.listen_note, data_testid="listen-stage", class_name="inline-flex items-center gap-2 text-sm text-slate-200"),
                rx.el.button(rx.icon("square", size=13), T["stop"], on_click=Video.stop_listen, data_testid="listen-stop", class_name=GHOST),
                class_name="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-sky-400/30 bg-sky-950/40 px-3 py-2",
            ),
            rx.el.div(
                rx.el.button(rx.icon("ear", size=16), T["listen"], on_click=Video.listen_film, disabled=(Video.cues.length() == 0) | (Video.listening != ""), title=T["listen_tip"], data_testid="listen", class_name=f"{BUTTON} bg-sky-400 text-slate-950 hover:bg-sky-300 disabled:opacity-50"),
                rx.cond(~Video.ears, rx.el.span(T["listen_first"], class_name="text-xs text-slate-400")),
                class_name="mt-3 flex flex-wrap items-center gap-3",
            ),
        ),
        rx.el.audio(id="mv-audio", src=BACKEND + "/_studio/take/" + Video.film + ".mp3", controls=True, preload="metadata", class_name="mt-3 h-9 w-full"),
        rx.el.p(rx.el.span(T["now_singing"], class_name="shrink-0 text-xs text-slate-500"), rx.el.span(id="mv-now", data_testid="now", class_name="min-w-0 truncate text-sm text-sky-200"), class_name="mt-2 flex min-h-6 items-baseline gap-2"),
        rx.el.div(
            rx.el.button(rx.icon("mouse-pointer-click", size=14), T["tap_start"], on_click=Video.tap_start, disabled=Video.cues.length() == 0, data_testid="tap-start", class_name=GHOST),
            rx.el.button(rx.icon("chevrons-left", size=14), T["earlier"], on_click=Video.shift(-0.5), disabled=Video.cues.length() == 0, data_testid="shift-earlier", class_name=GHOST),
            rx.el.button(rx.icon("chevrons-right", size=14), T["later"], on_click=Video.shift(0.5), disabled=Video.cues.length() == 0, data_testid="shift-later", class_name=GHOST),
            rx.el.button(rx.icon("rotate-ccw", size=14), T["guess_again"], on_click=Video.guess_again, disabled=Video.cues.length() == 0, data_testid="guess-again", class_name=GHOST),
            rx.el.button(rx.icon("file-pen-line", size=14), T["edit_lrc"], on_click=Video.edit_lrc, data_testid="edit-lrc", class_name=GHOST),
            class_name="mt-3 flex flex-wrap gap-2",
        ),
        rx.cond(
            Video.tap >= 0,
            rx.el.div(
                rx.el.p(T["tap_hint"], class_name="text-xs text-amber-100/80"),
                rx.el.p(Video.tap_place, "：", Video.tap_line, data_testid="tap-line", class_name="mt-2 text-lg font-semibold text-amber-100"),
                rx.el.div(
                    AtPlayer.create(rx.icon("mouse-pointer-click", size=18), T["tap_now"], on_click=Video.tap_mark, id="mv-tap", data_testid="tap", class_name=f"{PRIMARY} px-6 py-3 text-base"),
                    rx.el.button(rx.icon("undo-2", size=14), T["tap_back"], on_click=Video.tap_back, data_testid="tap-back", class_name=GHOST),
                    rx.el.button(rx.icon("square", size=13), T["tap_done"], on_click=Video.tap_stop, data_testid="tap-stop", class_name=GHOST),
                    class_name="mt-3 flex flex-wrap items-center gap-2",
                ),
                class_name="mt-3 rounded-xl border border-amber-400/40 bg-amber-950/40 p-3",
            ),
        ),
        rx.cond(
            Video.lrc_open,
            rx.el.div(
                rx.el.p(T["lrc_hint"], class_name="text-xs text-slate-400"),
                # Its own text, as above: Chinese typed into it must not be cut off.
                rx.el.textarea(default_value=Video.lrc, on_change=Video.set_lrc, rows=10, data_testid="lrc", class_name=f"{INPUT} mt-2 resize-y font-mono"),
                rx.el.div(
                    rx.el.button(T["apply"], on_click=Video.apply_lrc, data_testid="lrc-apply", class_name=PRIMARY),
                    rx.el.button(T["cancel"], on_click=Video.close_lrc, class_name=GHOST),
                    class_name="mt-2 flex gap-2",
                ),
                class_name="mt-3",
            ),
        ),
        rx.cond(
            Video.cues.length() > 0,
            rx.el.div(rx.foreach(Video.cues, _cue_row), id="mv-cues", data_testid="cues", class_name="mt-3 max-h-80 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/60 p-1"),
        ),
        class_name="mt-6 rounded-2xl border border-white/10 bg-slate-950/50 p-4",
    )


def _film_dialog() -> rx.Component:
    return rx.cond(
        Video.film_open,
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        rx.el.h2(rx.icon("clapperboard", size=20, class_name="text-amber-400"), T["video_head"], class_name="flex items-center gap-2 text-lg font-bold"),
                        rx.el.p(T["video_note"], class_name="mt-1 text-xs text-slate-400"),
                        class_name="min-w-0",
                    ),
                    rx.el.button(rx.icon("x", size=18), on_click=Video.close_film, id="mv-close", title=T["close"], data_testid="video-close", class_name="rounded-full p-2 text-slate-300 hover:bg-slate-800"),
                    class_name="flex items-start justify-between gap-3",
                ),
                rx.el.div(
                    rx.el.div(_film_preview(), class_name="min-w-0 lg:col-span-3"),
                    rx.el.div(_film_settings(), class_name="min-w-0 lg:col-span-2"),
                    class_name="mt-4 grid gap-5 lg:grid-cols-5",
                ),
                _film_lyrics(),
                on_mount=rx.call_script(FILM_JS),
                data_testid="video-dialog",
                class_name="relative mx-auto my-4 w-full max-w-6xl rounded-2xl border border-white/10 bg-slate-900 p-4 text-slate-100 shadow-2xl sm:my-8 sm:p-6",
            ),
            class_name="fixed inset-0 z-50 overflow-y-auto bg-slate-950/80 px-3 backdrop-blur-sm",
        ),
    )


def _body() -> rx.Component:
    return rx.el.div(
        rx.el.div(_tab("compose", T["tab_compose"], "sparkles"), _tab("remake", T["tab_remake"], "wand-sparkles"), class_name="flex flex-wrap gap-2 rounded-2xl border border-white/10 bg-slate-900/70 p-1.5"),
        _engine_banner(),
        rx.el.div(rx.cond(Studio.tab == "compose", _compose(), _remake()), class_name="mt-4"),
        rx.cond(Studio.error != "", rx.el.p(Studio.error, data_testid="error", class_name="mt-3 rounded-xl bg-rose-950/60 px-3 py-2 text-sm text-rose-200")),
        rx.cond(Studio.busy, rx.el.p(rx.spinner(size="2"), Studio.stage, data_testid="stage", class_name="mt-3 flex items-center gap-2 text-sm text-slate-300")),
        rx.el.h2(T["takes"], class_name="mt-7 mb-3 text-lg font-semibold"),
        rx.cond(
            Studio.takes.length() > 0,
            rx.el.div(rx.foreach(Studio.takes, _take), data_testid="takes", class_name="grid gap-4 md:grid-cols-2"),
            rx.el.p(T["no_takes"], class_name="text-sm text-slate-400"),
        ),
    )


def index() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            _header(),
            rx.el.p(T["tagline"], class_name="pb-4 text-slate-300"),
            _body(),
            data_testid="studio",
            class_name="mx-auto max-w-4xl px-4 pb-16",
        ),
        _film_dialog(),
        _record_dialog(),
        class_name="min-h-screen bg-slate-950 text-slate-100",
    )


def dialog() -> rx.Component:
    return rx.el.div(rx.el.div(_body(), data_testid="studio", class_name="p-4"), class_name="bg-slate-950 text-slate-100")
