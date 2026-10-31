#!/usr/bin/env python3
"""Puts the music apps on this machine's re-ddns as dev installs, from these checkouts. Run it
yourself: it uses re-ddns's admin token, inside the re-ddns container.

    python3 dev_install.py                     # all of them
    python3 dev_install.py music-studio        # one
"""

import json
import pathlib
import subprocess
import sys
import time

GITS = pathlib.Path.home() / "gits"
AUDIO_READ = [{"collection": "audio", "access": "read"}]
AUDIO_WRITE = [{"collection": "audio", "access": "contribute"}]
APPS = {
    "ai": {"app_name": "ai_hub", "name": "AI Hub", "folder": "ai_hub", "volumes": ["smart-app-ai-data:/root/.local/share/ai_hub"]},
    "youtube-to-mp3": {"app_name": "youtube_to_mp3_tool", "name": "YouTube to MP3", "folder": "youtube_to_mp3_tool", "storage": AUDIO_WRITE},
    "music-studio": {"app_name": "music_studio", "name": "Music Studio", "folder": "music_studio", "volumes": ["smart-app-music-studio-data:/root/.local/share/music_studio"], "storage": AUDIO_WRITE},
    "music-box": {"app_name": "music_box", "name": "Music Box", "folder": "music_box", "storage": AUDIO_READ},
    "apexline": {"app_name": "apexline", "name": "Apexline", "folder": "apexline", "volumes": ["smart-app-apexline-data:/root/.local/share/apexline"], "storage": AUDIO_READ},
}


def call(path: str, body: dict | None = None) -> str:
    if body is None:
        script = f"curl -s -m 30 http://127.0.0.1:8000{path}"
    else:
        script = f"curl -s -m 30 -X POST -H \"X-Re-DDNS-Admin-Token: $(cat /app/data/admin_token)\" -H 'Content-Type: application/json' -d @- http://127.0.0.1:8000{path}"
    done = subprocess.run(["docker", "exec", "-i", "re-ddns", "sh", "-c", script], input=json.dumps(body or {}), capture_output=True, text=True)
    return done.stdout


for sub in sys.argv[1:] or APPS:
    spec = dict(APPS[sub])
    spec["local_path"] = str(GITS / spec.pop("folder"))
    print(sub, call("/api/appstore/dev-install", {"subdomain": sub, "zone": "reflex-ddns.com", **spec})[:120], flush=True)
    for _ in range(100):
        time.sleep(6)
        try:
            state = json.loads(call(f"/api/appstore/status/{sub}"))
        except ValueError:
            continue
        print(f"  {state.get('percent')}% {state.get('phase')}", flush=True)
        if state.get("status") not in ("installing", None):
            print(" ", state.get("status"), str(state.get("message") or "")[:160], flush=True)
            break
