"""Music Studio (音樂工坊): the AI writes a piece for a situation, or changes a song that exists.

``/`` is the studio; ``/intent/audio-make`` the same in another app's dialog (DDNS Intent
``audio.make``; param ``words`` says what the music is for, and a kept take goes back with its ref,
for a game to play). What is kept lands in the shared ``audio`` collection.
"""

import logging

import reflex as rx
from reflex_ddns_auth import ai
from reflex_ddns_auth.intent import install_intent_host, intent

from music_studio import producer
from music_studio.api import api
from music_studio.state import Studio
from music_studio.views import dialog, index

logging.getLogger("music_studio").setLevel(logging.INFO)

app = rx.App(api_transformer=api)
app.add_page(index, route="/", title="音樂工坊 · Music Studio", on_load=Studio.on_load)


@intent(app, action="audio.make", title="Make music", params={"words": str, "style": str}, on_open=Studio.open_intent)
def make_intent() -> rx.Component:
    return dialog()


# The YouTube finder opens in a dialog from here.
install_intent_host(app)
# The AI Hub's page lists this app's AI by these words.
ai.uses(app, **producer.USES)
