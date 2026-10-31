"""The takes' sound and covers, next to Reflex's routes (``backend-paths.txt`` sends ``/_studio/``
here behind re-ddns)."""

from __future__ import annotations

import asyncio

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.routing import Route

from music_studio import drafts, library

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


api = Starlette(
    routes=[
        Route("/_studio/take/{draft}.mp3", take, methods=["GET"]),
        Route("/_studio/cover/{draft}.png", cover, methods=["GET"]),
        Route("/_studio/source", source, methods=["GET"]),
    ]
)
