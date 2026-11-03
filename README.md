# Music Studio 音樂工坊

Say what a piece of music is for and the AI writes it, or turn a song you have into what you need. What you keep goes into the shared `audio` collection, where [Music Box](https://github.com/milochen0418/music_box), the Video Audio Mixer and games can use it.

## Three ways to get music

- **Compose.** Say the situation ("the last lap of a night race, tense but cool"). The AI Hub's model chooses the style, tempo, key and chords; the composer here writes every note and plays it. Twelve styles: synthwave, drum & bass, chiptune, rock, house, techno, orchestral, lo-fi, ambient, tropical, desert, victory. Two takes each time, about 3 seconds of work for a minute of music after the model answers.
- **Change a song.** Pick one from the library, upload your own, or open YouTube to MP3's finder. The studio measures its tempo and key; the model decides how to change it (speed, pitch, tone, room, new drums); numpy and ffmpeg do it.
- **Use it in a game.** Other apps open the studio as a dialog (DDNS Intent `audio.make`, param `words`), and the take you keep goes back to them.

Everything made loops without a seam: `loop_start` and `loop_end` in the item's `meta` say where to jump.

## With the music engine: singing, and whole remakes

The composer here plays instruments only. For a song with singing, or to remake a recording outright (a new style, without the singing, an instrument playing its melody), the studio asks the AI Hub for the **music engine**, ACE-Step on the Mac (installed from the hub's page or with re_ddns's `macos_music_engine.sh`; see re_ddns's README). The hub's model then writes the lyrics and the song's description, the engine sings and plays it, and the take comes back here like any other. Without the engine those options are greyed out and the page says why.

What the engine's songs are not: they don't loop without a seam (a game starts them again), and a remake of someone else's recording stays theirs (`rights: third-party`).

A song someone else wrote stays theirs when changed: such takes are marked `rights: third-party` and shown as for your own use. Get permission before putting one in a public game or video.

## Make Video: a take as a YouTube video

Every take has a **Make Video** button. It makes a music video ready to upload to YouTube: an MP4 in 1080p (H.264 High + AAC, 30 frames a second, the index at the front), exactly as long as the song. It is made on this computer with FFmpeg, with no video model and no network; a 3-minute song takes about 1 to 2 minutes, and the page shows how far it is.

- **Background:** the song's cover, blurred, drifting slowly (or still).
- **Moves with the music:** spectrum bars or a waveform, in the cover's colour.
- **The cover, the title, who made it and a small line** (style, tempo, key), all editable before it is made.
- **Lyrics:** the line being sung, with the next one dimmed under it. The music engine gives lyrics without times, so the studio first guesses them from the song's length; then you can **tap along** (the song plays, and you press the space bar as each line begins), move every line or one line earlier or later, set a line to where the player is, or paste **LRC** (`[01:23.40]a line`) whose times are kept. While the song plays in the dialog, the line it has reached lights up, so you can check before making the video.

The video plays in the dialog and downloads under its title. It is kept with the take (`video.mp4`, and what it was made with in `video.json`, so the dialog opens with the same settings and times); making it again replaces it.

## How it is built

- `music_studio/producer.py`: what the model is told and how its answer is read. With no hub, or no answer, your words choose the style, so a piece always comes. `song_for` and `cover_for` write for the engine (`reflex_ddns_auth.ai.music`).
- `music_studio/composer/`: `theory.py` (scales, chords), `styles.py` (how each style is played), `arrange.py` (writes the parts), `synth.py` (instruments as sums of sine waves, drums), `render.py` (plays and masters the score). The same brief and seed give the same samples.
- `music_studio/remake.py`: tempo and key finding, and the changes.
- `music_studio/drafts.py`, `library.py`: takes until they are kept, then `audio.file` items.
- `music_studio/lyrics.py`: lyric lines without the section tags, LRC both ways, and the first guess at their times.
- `music_studio/video.py`: the music video. Pillow draws the still pictures and the lyric lines (an FFmpeg built without libass or freetype, as Homebrew's, can't write text); numpy measures a row of levels a frame for the bars or the wave; FFmpeg moves, joins and encodes it all.

## Running it

```bash
poetry env use python3.11
poetry install
DDNS_AI_HUB_URL=http://127.0.0.1:8172 DDNS_AUTH_SECRET=<the hub's secret> SERVICE_SUBDOMAIN=music-studio \
  DDNS_COLLECTIONS_ROOT=/tmp/collections REFLEX_API_URL=http://localhost:8175 \
  poetry run reflex run --frontend-port 3175 --backend-port 8175
```

It needs `ffmpeg` (with `libx264`), and for Chinese titles and lyrics in videos a font that has Chinese in it (a Mac has one; on Debian, `fonts-noto-cjk`). On re-ddns, `apt-packages.txt` installs both.

## Tests

```bash
poetry run pytest
DDNS_COLLECTIONS_ROOT=/tmp/collections FRONTEND_PORT=3175 BACKEND_PORT=8175 poetry run ./run_test_suite.sh studio_flow
DDNS_COLLECTIONS_ROOT=/tmp/collections FRONTEND_PORT=3175 BACKEND_PORT=8175 poetry run ./run_test_suite.sh video_flow
```
