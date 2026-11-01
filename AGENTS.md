# AGENTS.md

Read `README.md` first. Python 3.11 through Poetry; `poetry run` for everything; E2E through `./run_test_suite.sh <suite>` with a scratch `DDNS_COLLECTIONS_ROOT`.

- The app holds no model or key: the producer is the AI Hub's role `smart` through `reflex_ddns_auth.ai`. Thinking models need a large `max_tokens`, or they think it away and answer nothing.
- The model writes a brief, never notes. A bad answer must fall back to the style's own choice, and no answer to `producer.guess`.
- The composer is deterministic: nothing in `composer/` may use unseeded randomness, or the loop stops being exact. Everything after the notes looks only backwards in time for the same reason (`render._high_pass`).
- A dataclass field named `length` clashes with `ObjectVar.length()` in `rx.foreach`: rows use `clock`.
- A new style needs its row in `styles.py`, `art.COLOURS`, `i18n.STYLE_NAMES` and the system prompt's tempo list.
- The engine (ACE-Step) is reached only through the hub (`ai.music`, `ai.music_status`): never an address or key here. Its lyrics must carry section tags and "[Instrumental]" means no singing; a cover sends the recording as `audio_b64` (40 MB at most). Takes it made have no loop points.
- Check sound by numbers (`tests/test_composer.py`): nobody here can hear it, so say so when reporting.
