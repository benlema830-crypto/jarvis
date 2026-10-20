"""Find or design Jarvis's ElevenLabs voice. Run via elevenlabs.bat.

    elevenlabs.bat                     menu
    elevenlabs.bat voices              list British voices in your account
    elevenlabs.bat try <voice_id>      hear a voice say a Jarvis line
    elevenlabs.bat design ["prompt"]   design new voices from a description, keep the best
    elevenlabs.bat use <voice_id>      make Jarvis use that voice (writes .env)

Voice Design creates an original voice from a description. ElevenLabs' terms
don't allow cloning a real person's voice without their consent, so describe
the style you want rather than uploading film audio.
"""

import base64
import os
import re
import sys

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
PREVIEW_DIR = os.path.join(HERE, "voices", "previews")
API = "https://api.elevenlabs.io"
load_dotenv(ENV_PATH)

DEFAULT_DESCRIPTION = (
    "A refined English man in his late thirties with a soft, educated Received Pronunciation "
    "accent and a smooth light-baritone voice. He speaks calmly and unhurriedly with precise, "
    "crisp diction, gentle warmth and a hint of dry, understated amusement - polite, composed "
    "and quietly confident, like a sophisticated AI butler. Close-miked, clean studio recording."
)
SAMPLE_LINE = (
    "Good evening, sir. All systems are operational, and I've taken the liberty of reviewing "
    "your schedule for tomorrow. Three items require your attention, one of which I suspect "
    "you'll enjoy rather less than the others. Shall I prepare a summary, or would you prefer "
    "to be surprised?"
)


def _key() -> str:
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        sys.exit("No ELEVENLABS_API_KEY in .env yet.\n"
                 "Sign up at https://elevenlabs.io, open your profile > API Keys, create a key,\n"
                 "and add this line to .env:   ELEVENLABS_API_KEY=your_key_here")
    return key


def _call(method: str, path: str, **kwargs) -> requests.Response:
    resp = requests.request(method, API + path, headers={"xi-api-key": _key()}, timeout=120, **kwargs)
    if resp.status_code >= 400:
        sys.exit(f"ElevenLabs error {resp.status_code}: {resp.text[:400]}")
    return resp


def _play_pcm(data: bytes, rate: int = 24000):
    audio = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    sd.play(audio, rate)
    sd.wait()
    return audio


def set_env(key: str, value: str):
    lines = open(ENV_PATH, encoding="utf-8").read().splitlines() if os.path.exists(ENV_PATH) else []
    for i, line in enumerate(lines):
        if re.match(rf"\s*#?\s*{key}\s*=", line):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def voices():
    found = {}
    for params in ({"accent": "british"}, {"search": "british"}):
        data = _call("GET", "/v2/voices", params={"page_size": 100, **params}).json()
        for v in data["voices"]:
            found[v["voice_id"]] = v
    if not found:
        print("No British voices in your account yet. Try 'design', or add some from the Voice Library on elevenlabs.io.")
    current = os.getenv("ELEVENLABS_VOICE_ID", "")
    for v in sorted(found.values(), key=lambda v: v["name"]):
        labels = ", ".join(f"{k}: {val}" for k, val in (v.get("labels") or {}).items())
        mark = "  <- current" if v["voice_id"] == current else ""
        print(f"{v['voice_id']}  {v['name']:<22} [{v.get('category', '')}] {labels}{mark}")
    print("\nHear one with:  elevenlabs.bat try <voice_id>")


def try_voice(voice_id: str, line: str = SAMPLE_LINE):
    model = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
    print(f"Speaking with {voice_id} ({model})...")
    resp = _call("POST", f"/v1/text-to-speech/{voice_id}", params={"output_format": "pcm_24000"},
                 json={"text": line, "model_id": model})
    _play_pcm(resp.content)


def use(voice_id: str):
    set_env("ELEVENLABS_VOICE_ID", voice_id)
    set_env("JARVIS_TTS", "elevenlabs")
    print(f"Done. Jarvis will use voice {voice_id} next time he starts.")


def design(description: str = DEFAULT_DESCRIPTION):
    print(f"Designing voices for:\n  \"{description}\"\n(this takes ~20 seconds)")
    data = _call("POST", "/v1/text-to-voice/design", params={"output_format": "pcm_24000"},
                 json={"voice_description": description, "text": SAMPLE_LINE}).json()
    previews = data["previews"]
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    while True:
        for i, p in enumerate(previews, 1):
            print(f"\nPreview {i} of {len(previews)}...")
            audio = _play_pcm(base64.b64decode(p["audio_base_64"]))
            sf.write(os.path.join(PREVIEW_DIR, f"preview_{i}.wav"), audio, 24000)
        choice = input(f"\nKeep which one? (1-{len(previews)}, r = replay, Enter = none): ").strip().lower()
        if choice != "r":
            break
    if not choice.isdigit() or not 1 <= int(choice) <= len(previews):
        print("Nothing saved. Previews are in voices/previews. Try a different description for new options.")
        return
    name = input("Name for this voice [Jarvis]: ").strip() or "Jarvis"
    voice = _call("POST", "/v1/text-to-voice", json={
        "voice_name": name, "voice_description": description,
        "generated_voice_id": previews[int(choice) - 1]["generated_voice_id"],
    }).json()
    print(f"Saved '{name}' as voice {voice['voice_id']}.")
    if input("Make it Jarvis's voice now? (Y/n): ").strip().lower() != "n":
        use(voice["voice_id"])


def menu():
    print("=== Jarvis voice studio (ElevenLabs) ===")
    print("1) Design a new Jarvis-style voice")
    print("2) List British voices in my account")
    print("3) Hear a voice")
    print("4) Use a voice")
    choice = input("Choose: ").strip()
    if choice == "1":
        desc = input("Describe the voice (Enter for the default refined British butler):\n> ").strip()
        design(desc or DEFAULT_DESCRIPTION)
    elif choice == "2":
        voices()
    elif choice == "3":
        try_voice(input("Voice ID: ").strip())
    elif choice == "4":
        use(input("Voice ID: ").strip())


def main():
    args = sys.argv[1:]
    if not args:
        menu()
    elif args[0] == "voices":
        voices()
    elif args[0] == "try" and len(args) > 1:
        try_voice(args[1])
    elif args[0] == "use" and len(args) > 1:
        use(args[1])
    elif args[0] == "design":
        design(" ".join(args[1:]) or DEFAULT_DESCRIPTION)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
