# Music Studio 音樂工坊

Say what a piece of music is for and the AI writes it, or turn a song you have into what you need. What you keep goes into the shared `audio` collection, where [Music Box](https://github.com/milochen0418/music_box), the Video Audio Mixer and games can use it.

## Three ways to get music

- **Compose.** Say the situation ("the last lap of a night race, tense but cool"). The AI Hub's model chooses the style, tempo, key and chords; the composer here writes every note and plays it. Twelve styles: synthwave, drum & bass, chiptune, rock, house, techno, orchestral, lo-fi, ambient, tropical, desert, victory. Two takes each time, about 3 seconds of work for a minute of music after the model answers.
- **Change a song.** Pick one from the library, upload your own, or open YouTube to MP3's finder (each row says where it came from: a version made here may carry its original's title). Two ways:
  - **Adjust** works on the recording itself, so the original singing stays. The studio measures its tempo and key, the model decides how to change it (speed, pitch, tone, room, new drums), numpy and ffmpeg do it, and the strongest stretch becomes a seamless loop. With nothing written in the box, it is only cut into a loop, the sound unchanged.
  - **The AI remakes the whole song** with the music engine (below), as long as the original. With nothing written, it keeps the song's own style.
- **Use it in a game.** Other apps open the studio as a dialog (DDNS Intent `audio.make`, param `words`), and the take you keep goes back to them.

Everything made loops without a seam: `loop_start` and `loop_end` in the item's `meta` say where to jump.

## With the music engine: singing, and whole remakes

The composer here plays instruments only. For a song with singing, or to remake a recording outright (a new style, without the singing, an instrument playing its melody), the studio asks the AI Hub for the **music engine**, ACE-Step on the Mac (installed from the hub's page or with re_ddns's `macos_music_engine.sh`; see re_ddns's README). The hub's model then writes the lyrics and the song's description, the engine sings and plays it, and the take comes back here like any other. Without the engine those options are greyed out and the page says why.

A whole remake follows the recording's melody, sections and timing, and plays and sings everything again from a description and lyrics. So for its singing there are three choices:

- **Sung again, same words.** The engine never keeps the original singer's voice: it sings only the lyrics it is given (`[Instrumental]` means nobody sings). So the studio first listens to the recording with Whisper, the same speech model as Make Video's. It tells the language from a few windows across the song (its first half minute is often music alone, where Whisper's own guess goes wrong), and listens once more to any stretch of 12 seconds or more where it heard nothing (when unsure, Whisper guesses afresh each time, and a single listen can miss a whole verse: on Lydia the five lines checked were found 0 of 5 by one listen, 4 or 5 of 5 with the second). The lines it hears go to the hub's model, which puts them in sections and mends only words plainly misheard, and the engine sings them to the recording's tune. What was heard is kept by the file (`heard/` in the data folder), so a second remake of the same song doesn't listen again. When nobody is heard singing (a piece without vocals), the remake has no singing and says so.
- **No singing**, or **an instrument plays the tune**.

To keep the original singer's voice, use **Adjust**. How closely a remake follows the recording is `cover_strength`, the share of the engine's steps that follow it: 1.0 keeps its melody, structure and much of its arrangement, lower is freer. Sung words need at least 0.7 to fit the tune.

What the engine's songs are not: they don't loop without a seam (a game starts them again), and a remake of someone else's recording stays theirs (`rights: third-party`).

A song someone else wrote stays theirs when changed: such takes are marked `rights: third-party` and shown as for your own use. Get permission before putting one in a public game or video.

## Make Video: a take as a YouTube video

Every take has a **Make Video** button. It makes a music video ready to upload to YouTube: an MP4 in 1080p (H.264 High + AAC, 30 frames a second, the index at the front), exactly as long as the song. It is made on this computer with FFmpeg, with no video model and no network; a 3-minute song takes about 1 to 2 minutes, and the page shows how far it is.

- **Background:** the song's cover, blurred, drifting slowly (or still).
- **Moves with the music:** spectrum bars or a waveform, in the cover's colour.
- **The cover, the title, who made it and a small line** (style, tempo, key), all editable before it is made.
- **Lyrics:** the line being sung, with the next one dimmed under it, each when it is sung.

The music engine gives lyrics without times, and doesn't always sing every line, or start with the first. So **the AI listens to the song**: Whisper hears what is sung and when, and the studio matches what it heard with the lyrics, sound by sound and in order (Chinese by its pinyin, so simplified or homophone characters heard still match). Each line goes where its words were heard; a line the AI didn't hear is marked *not heard* and left out of the video, so no line shows while something else is sung. It starts by itself when the dialog opens, once the speech model is here; the first time, the **AI listens** button downloads it (about 1.6 GB, once). On this Mac a 3-minute song takes about 40 seconds. A line shows a fraction of a second before it is sung, as subtitles do.

You can still change any time by hand: **tap along** (the song plays, and you press the space bar as each line begins), move every line or one line earlier or later, set a line to where the player is (which also puts a line the AI didn't hear back in), or paste **LRC** (`[01:23.40]a line`) whose times are kept; lyrics pasted without times are matched with what the AI heard. While the song plays in the dialog, the line it has reached lights up.

The video plays in the dialog and downloads under its title. It is kept with the take (`video.mp4`, and what it was made with in `video.json`, so the dialog opens with the same settings and times; what the AI heard in `heard.json`); making it again replaces it.

## How it is built

- `music_studio/producer.py`: what the model is told and how its answer is read. With no hub, or no answer, your words choose the style, so a piece always comes. `song_for` and `cover_for` write for the engine (`reflex_ddns_auth.ai.music`).
- `music_studio/composer/`: `theory.py` (scales, chords), `styles.py` (how each style is played), `arrange.py` (writes the parts), `synth.py` (instruments as sums of sine waves, drums), `render.py` (plays and masters the score). The same brief and seed give the same samples.
- `music_studio/remake.py`: tempo and key finding, and the changes.
- `music_studio/drafts.py`, `library.py`: takes until they are kept, then `audio.file` items.
- `music_studio/lyrics.py`: lyric lines without the section tags, LRC both ways, matching what was heard with the lyrics (`align`), and a first guess at the times when nobody listened.
- `music_studio/listen.py`: Whisper ([faster-whisper](https://github.com/SYSTRAN/faster-whisper), int8 on the CPU, in this app as English Chat's subtitles are): the model's download (into the data folder), the listening, `heard.json`; for a remake, the recording's words (`hear_recording`) and whether anybody sings in it at all (`sung`). `MUSIC_STUDIO_WHISPER` picks another model (`medium`, `small`, a Hugging Face repo or a folder); `MUSIC_STUDIO_WHISPER_THREADS` the CPU threads (8).
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
# With the speech model (a folder holding it; the app's data folder has one under models/ after its first download):
MUSIC_STUDIO_WHISPER=<model folder> poetry run pytest tests/test_listen.py
MUSIC_STUDIO_WHISPER=<model folder> DDNS_COLLECTIONS_ROOT=/tmp/collections FRONTEND_PORT=3175 BACKEND_PORT=8175 poetry run ./run_test_suite.sh listen_flow
# With an AI Hub that has the music engine: one part of sing_flow (sing, remake or keep), on one song
SUITE_ARGS=keep REMAKE_SOURCE=Lydia DDNS_COLLECTIONS_ROOT=/tmp/collections FRONTEND_PORT=3175 BACKEND_PORT=8175 poetry run ./run_test_suite.sh sing_flow
```
