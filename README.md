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

A whole remake draws a coarse skeleton of the recording (its melody, sections and timing) and plays and sings everything again on it from a description and lyrics: the result sits between a cover and a remix, and it often takes a few tries. So for its singing there are three choices:

- **Sung again, same words.** The engine never keeps the original singer's voice: it sings only the lyrics it is given (`[Instrumental]` means nobody sings). So the words are found first and **shown to you before the engine starts**: the studio looks the song up by its title in [LRCLIB](https://lrclib.net) (a free lyrics database its users keep; only the cleaned-up title is sent), and when it isn't there, listens to the recording with Whisper, the same speech model as Make Video's. Whisper tells the language from a few windows across the song (its first half minute is often music alone, or another language: Lydia opens in Spanish), and listens once more to any stretch of 12 seconds or more where it heard nothing (a single listen can miss a whole verse). Chinese it hears in Simplified characters is written as in Taiwan (OpenCC `s2twp`), and the lines are put in parts (a part sung again becomes `[Chorus]`). You check them, change any word, paste the right lyrics, choose another language and have it listen again, or clear them for a version without singing; then **Remake it with these words** starts the remake with exactly those words. What was heard is kept by the file (`heard/` in the data folder), so a second remake of the same song doesn't listen again.
- **No singing**, or **an instrument plays the tune**.

To keep the original singer's voice, use **Adjust**.

**How close to the original?** ACE-Step follows the recording's skeleton for `int(8 × cover_strength)` of its 8 steps, so only whole steps make a difference. The studio uses three that do: **Close** (8 of 8: the same melody, sections and timing, a new sound; still a new performance, not a copy), **Standard** (6 of 8: recognisable, played more freely) and **Free** (4 of 8: the melody only roughly, for a whole new genre). Left to the AI, the producer picks one, at least Standard when the original words are sung again. **Also aim for the original's sound** (experimental) sends the recording as the engine's reference too (its timbre and mix, averaged over time); it doesn't bring back the singer's voice, and nobody has compared the results by ear yet. Uploaded recordings count as somebody else's (`rights: third-party`) unless you tick that they are your own.

**After a take is made**, two buttons work on it: **Make it again** sends what its record says was asked (the same words, description and closeness; for a remake, the recording read anew) with a new random seed, as `title #2`; **Remake one part** makes 3 to 90 seconds of an engine's take again (ACE-Step's repaint, a little or a lot), with the whole lyrics and description there to change, while the rest stays exactly as it was. A remake is also measured against its recording (tempo, key, length), and its record can have the AI count how many of its lines are really sung.

What the engine's songs are not: they don't loop without a seam (a game starts them again), and a remake of someone else's recording stays theirs (`rights: third-party`).

A song someone else wrote stays theirs when changed: such takes are marked `rights: third-party` and shown as for your own use. Get permission before putting one in a public game or video.

## How it was made: each take's record

Every take has a **How it was made** button (製作紀錄), so you can look back at how each piece came about and learn what works. It shows:

- who made it: the AI Hub's role (`smart`) and the model that answered, as the hub names it (with the owner's Claude Code, the model it runs, e.g. "Claude Code (your computer, claude-opus-5-5)"; see the hub's README), and how long it took; for a remake that sings the recording's words again, the speech model that heard them and how many lines; the music engine's models (ACE-Step's DiT and planner) and how long it worked, or the studio's own composer or remaker, which use no model;
- what you wrote;
- the producer's rules (the same each time, folded) and the message it got, word for word (for a remake: the recording's tempo and key, what you asked for, the lines heard in it);
- its whole answer, as written;
- what went to the music engine (the caption, lyrics, language, length, tempo, cover strength; not the recording itself), or the brief and seed the composer played, or the remaker's plan;
- what the engine said when it was done (its tempo, key, length, and the seed that makes the same song again);
- for a remake: where the words sung came from (LRCLIB, the AI's listening, or your own) and whether you changed them, how close it stayed (the level and its steps), and how it came out against the recording (tempo, key, length, and, when the AI has listened, how many lines are sung); a take made again names the take it came from.

**Copy all** copies it as text for your own notes. It is kept with the take (`making.json`), and a kept take carries it into its library item beside `piece.mp3`, so it stays when the take leaves the studio's newest 24. Takes made before records were kept show what they still have.

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
- `music_studio/making.py`: each take's making record (`making.json`): what it holds, and how the page shows it.
- `music_studio/lrclib.py`: looking a song's lyrics up in LRCLIB by its title (`MUSIC_STUDIO_LRCLIB=0` turns it off).
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
# With an AI Hub that has the music engine: parts of sing_flow (sing, remake, keep, edit), on one song
SUITE_ARGS=keep REMAKE_SOURCE=Lydia DDNS_COLLECTIONS_ROOT=/tmp/collections FRONTEND_PORT=3175 BACKEND_PORT=8175 poetry run ./run_test_suite.sh sing_flow
```
