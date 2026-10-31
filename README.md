# Music Studio 音樂工坊

Say what a piece of music is for and the AI writes it, or turn a song you have into what you need. What you keep goes into the shared `audio` collection, where [Music Box](https://github.com/milochen0418/music_box), the Video Audio Mixer and games can use it.

## Three ways to get music

- **Compose.** Say the situation ("the last lap of a night race, tense but cool"). The AI Hub's model chooses the style, tempo, key and chords; the composer here writes every note and plays it. Twelve styles: synthwave, drum & bass, chiptune, rock, house, techno, orchestral, lo-fi, ambient, tropical, desert, victory. Two takes each time, about 3 seconds of work for a minute of music after the model answers.
- **Change a song.** Pick one from the library, upload your own, or open YouTube to MP3's finder. The studio measures its tempo and key; the model decides how to change it (speed, pitch, tone, room, new drums); numpy and ffmpeg do it.
- **Use it in a game.** Other apps open the studio as a dialog (DDNS Intent `audio.make`, param `words`), and the take you keep goes back to them.

Everything made loops without a seam: `loop_start` and `loop_end` in the item's `meta` say where to jump.

## What this is not

It is instrumental: no singing. Changing a song doesn't touch its notes or separate its instruments. For that, a music model such as ACE-Step would have to run on the host and be offered through the AI Hub.

A song someone else wrote stays theirs when changed: such takes are marked `rights: third-party` and shown as for your own use. Get permission before putting one in a public game or video.

## How it is built

- `music_studio/producer.py`: what the model is told and how its answer is read. With no hub, or no answer, your words choose the style, so a piece always comes.
- `music_studio/composer/`: `theory.py` (scales, chords), `styles.py` (how each style is played), `arrange.py` (writes the parts), `synth.py` (instruments as sums of sine waves, drums), `render.py` (plays and masters the score). The same brief and seed give the same samples.
- `music_studio/remake.py`: tempo and key finding, and the changes.
- `music_studio/drafts.py`, `library.py`: takes until they are kept, then `audio.file` items.

## Running it

```bash
poetry env use python3.11
poetry install
DDNS_AI_HUB_URL=http://127.0.0.1:8172 DDNS_AUTH_SECRET=<the hub's secret> SERVICE_SUBDOMAIN=music-studio \
  DDNS_COLLECTIONS_ROOT=/tmp/collections REFLEX_API_URL=http://localhost:8175 \
  poetry run reflex run --frontend-port 3175 --backend-port 8175
```

It needs `ffmpeg`. On re-ddns, `apt-packages.txt` installs it.

## Tests

```bash
poetry run pytest
DDNS_COLLECTIONS_ROOT=/tmp/collections FRONTEND_PORT=3175 BACKEND_PORT=8175 poetry run ./run_test_suite.sh studio_flow
```
