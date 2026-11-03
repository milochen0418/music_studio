"""The takes' sound, covers and videos, next to Reflex's routes (``backend-paths.txt`` sends
``/_studio/`` here behind re-ddns)."""

from __future__ import annotations

import asyncio
import re

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.routing import Route

from music_studio import drafts, library, video

HEADERS = {"Access-Control-Allow-Origin": "*", "Cache-Control": "private, max-age=600"}


async def take(request: Request) -> Response:
    path = await asyncio.to_thread(drafts.audio_path, request.path_params["draft"])
    if path is None:
        return PlainTextResponse("no such take", status_code=404, headers=HEADERS)
    return FileResponse(path, media_type="audio/mpeg", headers=HEADERS)


async def cover(request: Request) -> Response:
    path = await asyncio.to_thread(drafts.cover_path, request.path_params["draft"])
    if path is None:
        return PlainTextResponse("no such take", status_code=404, headers=HEADERS)
    return FileResponse(path, media_type="image/png", headers=HEADERS)


async def source(request: Request) -> Response:
    """A library song, to hear before changing it."""
    path, _ = await asyncio.to_thread(library.source_file, request.query_params.get("ref", ""))
    if path is None or not path.is_file():
        return PlainTextResponse("no such song", status_code=404, headers=HEADERS)
    return FileResponse(path, media_type="audio/mpeg", headers=HEADERS)


async def film(request: Request) -> Response:
    """A take's music video, to watch (a range at a time) or, with ``?download=1``, to save under
    the song's title."""
    draft = request.path_params["draft"]
    path = await asyncio.to_thread(video.path, draft)
    if path is None:
        return PlainTextResponse("no video", status_code=404, headers=HEADERS)
    if not request.query_params.get("download"):
        return FileResponse(path, media_type="video/mp4", headers=HEADERS)
    title = str((await asyncio.to_thread(video.settings, draft) or {}).get("title") or "")
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title).strip()[:80] or "music-video"
    return FileResponse(path, media_type="video/mp4", headers=HEADERS, filename=f"{name}.mp4")


api = Starlette(
    routes=[
        Route("/_studio/take/{draft}.mp3", take, methods=["GET"]),
        Route("/_studio/cover/{draft}.png", cover, methods=["GET"]),
        Route("/_studio/video/{draft}.mp4", film, methods=["GET"]),
        Route("/_studio/source", source, methods=["GET"]),
    ]
)
