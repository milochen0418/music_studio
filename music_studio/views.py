"""The studio's page, on its own and in another app's dialog."""

from __future__ import annotations

import reflex as rx
from reflex.utils.imports import ImportVar
from reflex.vars import VarData
from reflex_ddns_auth.intent import Intent, IntentState

from music_studio.library import Source
from music_studio.state import FINDER, Studio, Take

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
        rx.el.textarea(id="words", value=Studio.words, on_change=Studio.set_words, placeholder=T["words_hint"], rows=3, data_testid="words", class_name=f"{INPUT} mt-2 resize-y"),
        rx.el.div(rx.foreach(Studio.scenes, lambda s: rx.el.button(s, on_click=Studio.use_scene(s), class_name="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-amber-400")), class_name="mt-3 flex flex-wrap gap-2"),
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
        rx.el.span(row.clock, class_name="shrink-0 font-mono text-xs text-slate-400"),
        on_click=Studio.choose_source(row.ref, row.title),
        data_testid="source",
        class_name=rx.cond(Studio.source_ref == row.ref, "flex w-full items-center gap-2 rounded-lg bg-slate-800 px-3 py-2 text-sm", "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-slate-800/60"),
    )


def _finder_button() -> rx.Component:
    start = Intent.start(None, FINDER, on_update=Studio.finder_update, on_cancel=Studio.finder_closed, keep_alive=True, label="YouTube")
    return rx.el.button(rx.icon("search", size=15), T["find"], on_click=rx.cond(IntentState.open_actions.contains(FINDER), Intent.show(FINDER), start), data_testid="find", class_name=GHOST)


def _remake() -> rx.Component:
    return rx.el.div(
        rx.el.div(T["source"], class_name="font-semibold"),
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
        rx.el.label(T["how"], html_for="how", class_name="mt-4 block font-semibold"),
        rx.el.textarea(id="how", value=Studio.how, on_change=Studio.set_how, placeholder=T["how_hint"], rows=2, data_testid="how", class_name=f"{INPUT} mt-2 resize-y"),
        rx.el.div(_length(), class_name="mt-3 flex max-w-xs"),
        rx.el.p(rx.icon("info", size=14, class_name="mr-1 inline align-[-2px]"), T["rights_note"], class_name="mt-3 text-xs leading-relaxed text-amber-200/80"),
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
                rx.el.div(rx.icon("repeat", size=12), T["loops"], class_name="mt-0.5 inline-flex items-center gap-1 text-[11px] text-emerald-300"),
                class_name="min-w-0 flex-1",
            ),
            class_name="flex items-center gap-3",
        ),
        rx.image(src=row.wave, alt="", class_name="mt-3 h-8 w-full opacity-70"),
        rx.el.audio(src=BACKEND + "/_studio/take/" + row.id + ".mp3", controls=True, preload="none", class_name="mt-2 h-9 w-full"),
        rx.cond(row.why != "", rx.el.p("“", row.why, "”", class_name="mt-2 text-sm italic text-slate-300")),
        rx.cond(row.from_title != "", rx.el.p(T["from"], " ", row.from_title, class_name="mt-1 truncate text-xs text-slate-400")),
        rx.cond(row.rights != "own", rx.el.p(rx.icon("triangle-alert", size=12, class_name="mr-1 inline align-[-1px]"), T["rights_mark"], class_name="mt-1 text-xs text-amber-300")),
        rx.el.div(
            rx.cond(
                row.ref != "",
                rx.el.span(rx.icon("check", size=14), T["kept"], class_name="inline-flex items-center gap-1 text-sm text-emerald-300"),
                rx.el.button(rx.icon("bookmark-plus", size=15), rx.cond(Studio.in_dialog, T["use"], T["keep"]), on_click=Studio.keep(row.id), data_testid="keep", class_name=PRIMARY),
            ),
            rx.cond(row.model != "", rx.el.span(row.model, class_name="ml-auto truncate font-mono text-[11px] text-slate-500"), rx.el.span(T["by_keywords"], class_name="ml-auto text-[11px] text-slate-500")),
            class_name="mt-3 flex items-center gap-3",
        ),
        data_testid="take",
        class_name=CARD,
    )


def _body() -> rx.Component:
    return rx.el.div(
        rx.el.div(_tab("compose", T["tab_compose"], "sparkles"), _tab("remake", T["tab_remake"], "wand-sparkles"), class_name="flex flex-wrap gap-2 rounded-2xl border border-white/10 bg-slate-900/70 p-1.5"),
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
        class_name="min-h-screen bg-slate-950 text-slate-100",
    )


def dialog() -> rx.Component:
    return rx.el.div(rx.el.div(_body(), data_testid="studio", class_name="p-4"), class_name="bg-slate-950 text-slate-100")
