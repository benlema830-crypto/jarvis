#!/usr/bin/env python3
"""Jarvis in the room: the laptop's microphone and speakers for the Jarvis on the PC.

Runs on the Fedora laptop as a systemd user service (jarvis-room.service, set up by install.sh). It listens with
the laptop's microphone, cuts what you say at a one-second pause, and sends only those clips to the PC over
Tailscale (POST /room/listen). The PC transcribes them and answers only when a clip starts with "Jarvis" (or
right after an answer, as a follow-up); his answer comes back in his own voice and plays here. It keeps listening
while a clip is being checked (so "Jarvis, ..." straight after someone else spoke isn't lost) and goes deaf only
while his answer plays, so he doesn't hear himself.

Standard library only, plus the system's own recorder and player (arecord/aplay, parecord/paplay or
pw-record/pw-play), so nothing has to be installed with pip.

    satellite.py                 run (the service does this)
    satellite.py --once FILE     send one WAV and play the answer (a test)
    jarvis-room on|off           (the launcher) start or stop the service
"""
import argparse
import array
import io
import json
import math
from pathlib import Path
import queue
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

CONFIG = Path.home() / ".config" / "jarvis-laptop" / "config.json"
RATE, FRAME = 16000, 1600            # 100 ms frames of 16-bit mono
PAUSE_S, MAX_S, MIN_SPEECH_S = 1.0, 20.0, 0.3
FOLLOW_S = 8.0
RECORDERS = [
    ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", "1"],
    ["parecord", "--raw", f"--rate={RATE}", "--channels=1", "--format=s16le"],
    ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
]
PLAYERS = [["pw-play"], ["paplay"], ["aplay", "-q"]]


def log(text):
    print(text, flush=True)


def config():
    data = json.loads(CONFIG.read_text())
    return data["url"].rstrip("/"), data["key"]


def tool(options):
    for command in options:
        if shutil.which(command[0]):
            return command
    return None


def wav_bytes(pcm: bytes, rate=RATE) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(pcm)
    return out.getvalue()


def rms(frame: bytes) -> float:
    samples = array.array("h", frame)
    if sys.byteorder != "little":
        samples.byteswap()
    return math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))


def chime() -> bytes:
    pcm = array.array("h")
    for i in range(int(RATE * 0.25)):
        pitch = 880 if i < RATE * 0.08 else 1320
        fade = min(1.0, i / 300, (RATE * 0.25 - i) / 1500)
        pcm.append(int(9000 * fade * math.sin(2 * math.pi * pitch * i / RATE)))
    return wav_bytes(pcm.tobytes())


def play(wav: bytes):
    player = tool(PLAYERS)
    if not player:
        log("(no audio player found: install alsa-utils)")
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as file:
        file.write(wav)
    try:
        subprocess.run(player + [file.name], check=False, timeout=300)
    finally:
        Path(file.name).unlink(missing_ok=True)


def send(url, key, clip: bytes, followup: bool):
    """POST one clip; returns (kind, payload): ("audio", (wav, heard, reply)), ("awake", None) or ("quiet", None)."""
    request = urllib.request.Request(url + "/room/listen" + ("?followup=1" if followup else ""), data=wav_bytes(clip),
                                     headers={"Content-Type": "audio/wav", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(request, timeout=200, context=ssl.create_default_context()) as response:
        body = response.read()
        if response.headers.get("Content-Type", "").startswith("audio/"):
            heard = urllib.parse.unquote(response.headers.get("X-Jarvis-Heard", ""))
            reply = urllib.parse.unquote(response.headers.get("X-Jarvis-Reply", ""))
            return "audio", (body, heard, reply)
        data = json.loads(body or b"{}")
        return ("awake", None) if data.get("awake") else ("quiet", None)


class Microphone:
    """The recorder runs all the time; frames read while `muted` are thrown away (so nothing piles up)."""

    def __init__(self, source=None):
        self.frames: queue.Queue[bytes] = queue.Queue(maxsize=50)
        self.muted = False
        if source is None:
            command = tool(RECORDERS)
            if not command:
                sys.exit("No recorder found. Install one: sudo dnf install alsa-utils")
            log(f"Microphone: {command[0]}")
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            source = self.process.stdout
        threading.Thread(target=self._read, args=(source,), daemon=True).start()

    def _read(self, source):
        while frame := source.read(FRAME * 2):
            if len(frame) < FRAME * 2:
                break
            if not self.muted:
                try:
                    self.frames.put_nowait(frame)
                except queue.Full:
                    pass
        self.frames.put(b"")  # the recorder stopped

    def drain(self):
        while not self.frames.empty():
            self.frames.get_nowait()


class Sender:
    """Sends finished clips one at a time, in order, and plays what comes back."""

    def __init__(self, url, key, mic):
        self.url, self.key, self.mic = url, key, mic
        self.clips: queue.Queue[tuple[bytes, float]] = queue.Queue()
        self.follow_until = 0.0
        self.failures = self.handled = 0
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        while True:
            clip, ended = self.clips.get()
            try:
                self._one(clip, ended)
            finally:
                self.handled += 1

    def _one(self, clip, ended):
        try:
            kind, payload = send(self.url, self.key, clip, ended < self.follow_until)
            self.failures = 0
        except urllib.error.HTTPError as error:
            log(f"(Jarvis refused the clip: {error.code})")
            if error.code == 401:
                time.sleep(30)  # unpaired or locked out: don't hammer the PC
            return
        except (urllib.error.URLError, OSError, ValueError) as error:
            self.failures += 1
            if self.failures == 1 or self.failures % 20 == 0:
                log(f"(Can't reach Jarvis: {error}. Is Tailscale on and the PC awake?)")
            return
        if kind == "quiet":
            return
        self.mic.muted = True  # deaf while he talks; what was said meanwhile was said over him
        try:
            if kind == "audio":
                wav, heard, reply = payload
                log(f"You: {heard}\nJarvis: {reply}")
                play(wav)
            else:
                play(chime())
            while not self.clips.empty():
                self.clips.get_nowait()
                self.handled += 1
        finally:
            self.mic.drain()
            self.mic.muted = False
            self.follow_until = time.time() + FOLLOW_S


def run(source=None, stop_after=None):
    url, key = config()
    mic = Microphone(source)
    sender = Sender(url, key, mic)
    floor, loud, speaking, clip, pre = 300.0, 0, False, [], []
    speech_s = quiet_s = total_s = 0.0
    sent = 0
    log(f"Listening for \"Jarvis\" (sending to {url})")
    while True:
        if stop_after and sender.handled >= stop_after:
            return
        try:
            frame = mic.frames.get(timeout=1)
        except queue.Empty:
            continue
        if not frame:
            if stop_after:  # a test's recording ran out: let the last clips finish
                while sender.handled < sent:
                    time.sleep(0.1)
                return
            sys.exit("The microphone stopped.")
        if mic.muted:
            continue
        level = rms(frame)
        loud_enough = level > max(350.0, floor * 3)
        if not speaking:
            if not loud_enough:
                floor = floor * 0.95 + level * 0.05
            pre = (pre + [frame])[-4:]  # keep the start of the first word
            loud = loud + 1 if loud_enough else 0
            if loud >= 2:
                speaking, clip, speech_s, quiet_s, total_s = True, list(pre), 0.2, 0.0, len(pre) * 0.1
            continue
        clip.append(frame)
        total_s += 0.1
        speech_s, quiet_s = (speech_s + 0.1, 0.0) if loud_enough else (speech_s, quiet_s + 0.1)
        if quiet_s < PAUSE_S and total_s < MAX_S:
            continue
        speaking, loud, pre = False, 0, []
        if speech_s >= MIN_SPEECH_S:
            sender.clips.put((b"".join(clip), time.time()))
            sent += 1


def once(path):
    url, key = config()
    with wave.open(str(path)) as file:
        if file.getframerate() != RATE or file.getnchannels() != 1 or file.getsampwidth() != 2:
            sys.exit("The test WAV must be 16 kHz mono 16-bit.")
        pcm = file.readframes(file.getnframes())
    kind, payload = send(url, key, pcm, False)
    if kind == "audio":
        log(f"You: {payload[1]}\nJarvis: {payload[2]}")
        play(payload[0])
    else:
        log(f"({kind})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis in the room")
    parser.add_argument("--once", metavar="WAV", help="send one 16 kHz mono WAV and play the answer")
    args = parser.parse_args()
    once(args.once) if args.once else run()
