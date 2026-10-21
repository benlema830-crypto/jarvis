"""Stable identity and HUD defaults for each installed Jarvis copy."""
import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
_profile_path = HERE / "voice-profile.json"
PROFILE = json.loads(_profile_path.read_text(encoding="utf-8")) if _profile_path.exists() else {}


def mutex_name(folder):
    canonical = os.path.normcase(os.path.realpath(folder))
    suffix = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return "JarvisAssistant_" + suffix


MUTEX_NAME = mutex_name(HERE)
HUD_PORT = int(os.getenv("JARVIS_HUD_PORT") or PROFILE.get("hud_port", 7777))
