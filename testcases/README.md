# E2E testcases

`testcases/<suite>/run_test.py`, run with `poetry run ./run_test_suite.sh <suite>`. Set
`FRONTEND_PORT` and `BACKEND_PORT` if 3000/8000 are taken, and point `DDNS_COLLECTIONS_ROOT` at a
scratch folder: the suite publishes into it.

| Suite | What it checks |
|-------|----------------|
| `studio_flow` | Say what a piece is for, get two takes that play, keep one, find it in the collection with its loop points and its making record, read and copy that record (who decided, what the composer was given), make it again with the same settings, then change it into a new take. |
| `video_flow` | Make Video on a take with lyrics but no times: the lines guessed, tapped along to, nudged and given as LRC; a 1080p MP4 (H.264 High + AAC) as long as the song, playing in the dialog, downloading under its title, the first line on screen when it is sung; another video started and stopped. About a minute. |
| `listen_flow` | (Needs `MUSIC_STUDIO_WHISPER` set to a model folder, and macOS `say`; skipped without.) Lines said at known times over music and one never said: on opening Make Video the AI listens by itself, each line lands within a second of where it is said, the line never said is marked and left out, and the video shows each line while it is said. |
| `sing_flow` | (Needs an AI Hub with the music engine; skipped without one.) A song sung by the AI from a few words, its lyrics shown; a whole remake of a library song with an instrument in place of the singing; and one that keeps the singing: the AI listens for the original's words, the engine sings them again, and Make Video's listening hears them in the new take (needs the speech model); the words found (LRCLIB's or the AI's) are checked and changed before the remake starts. `edit` (after `keep`) makes a take again with the same settings and remakes one part of it. Each take's making record must show the producer's message and answer and what went to the engine. Several minutes. `REMAKE_CLOSENESS` (close, standard, free) picks how close; locally, `MUSIC_STUDIO_LRCLIB=0` keeps the words from the AI's listening. `SUITE_ARGS=sing`, `remake` or `keep` runs one part; `REMAKE_SOURCE` (a pattern its row matches, such as `Lydia.*YouTube`) picks the song, `REMAKE_HOW` what it should become. |
