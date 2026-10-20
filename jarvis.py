"""JARVIS - a voice assistant for your Windows PC, powered by Claude.

Run:  run.bat            voice mode - say "Jarvis, ..." to talk to it
      run.bat --text     type instead of talk
      run.bat --voices   hear the available British voices
"""

import datetime
import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic
import win32api
import win32event
import winerror
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

import activity  # noqa: E402
import context  # noqa: E402
import hud  # noqa: E402
import tools  # noqa: E402
from tools import TOOL_DEFS, run_tool  # noqa: E402
from voice import BRITISH_VOICES, SentenceBuffer, Voice  # noqa: E402

MODEL = "claude-haiku-5-5"
START_TIME = time.time()
WAKE_WORDS = ("jarvis", "jarvas", "jervis")
FOLLOWUP_SECONDS = 8  # after Jarvis answers, you can reply without saying "Jarvis"
EXIT_PHRASES = {"exit", "quit", "goodbye", "good night", "shut down", "go to sleep", "power down"}

SYSTEM_PROMPT = """You are JARVIS, the AI from Iron Man, now running on the user's Windows PC. Address the user as "sir".

Personality: calm, razor-sharp and quietly loyal, with a dry British wit. You're quick on your feet: lead with the answer, add a wry remark when it fits, never ramble.

Everything you write is spoken aloud by a text-to-speech voice, so:
- Usually reply in one or two short sentences; go longer only when asked for detail.
- Plain spoken English only: no markdown, lists, emoji, or reading out URLs.
- Say times and numbers the way a person would ("half past nine", "seventy-two degrees").
- Write the way people actually talk: contractions, natural rhythm, the odd "Ah," or "Right then."
- Your voice can perform a few sound cues: [chuckle], [sigh], [clear throat]. Use one only when it genuinely fits, at most one per reply, and most replies need none.

Use your tools to act on the computer or look things up rather than guessing. Never invent calendar events, weather, or activity you haven't been given."""


class Refused(Exception):
    pass


class Brain:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.messages = []

    def ask(self, text: str, speak):
        """Send `text` to Claude, calling speak(sentence) as each sentence streams in."""
        if len(self.messages) > 150:
            self.messages = []  # very long day: start a fresh conversation
        start = len(self.messages)
        self.messages.append({"role": "user", "content": text})
        try:
            self._run(speak)
        except BaseException:
            del self.messages[start:]  # keep history consistent after a failed turn
            raise

    def _run(self, speak):
        for _ in range(8):  # at most 8 rounds of tool use per request
            buf = SentenceBuffer()
            with self.client.messages.stream(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFS,
                messages=self.messages,
                output_config={"effort": "low"},  # quick replies; it still thinks when it needs to
                cache_control={"type": "ephemeral"},  # reuse the conversation prefix - faster and cheaper
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        for sentence in buf.feed(event.text):
                            speak(sentence)
                response = stream.get_final_message()
            if rest := buf.flush():
                speak(rest)

            if response.stop_reason == "refusal":
                raise Refused()
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if tool_uses and response.stop_reason == "max_tokens":
                raise RuntimeError("tool input was cut off")
            self.messages.append({"role": "assistant", "content": response.content})
            if not tool_uses:
                return
            self.messages.append({"role": "user", "content": [run_tool(b) for b in tool_uses]})
        raise RuntimeError("too many tool rounds")


def respond(brain: Brain, voice: Voice, text: str):
    try:
        brain.ask(text, voice.say)
    except Refused:
        voice.say("I'm afraid that's one I can't help with, sir.")
    except anthropic.AuthenticationError:
        voice.say("My API key appears to be invalid, sir. Please check the .env file.")
    except anthropic.RateLimitError:
        voice.say("I'm being rate limited, sir. Give me a moment.")
    except anthropic.APIStatusError as e:
        voice.say(f"The server returned an error, code {e.status_code}.")
    except anthropic.APIConnectionError:
        voice.say("I can't reach the network, sir.")
    except Exception as e:
        print(f"(error: {e!r})", flush=True)
        hud.emit("error", text=repr(e))
        voice.say("Apologies, sir, I lost my train of thought.")


# ---------- Startup briefing ----------

def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        return f"Unavailable ({type(e).__name__})."


def gather_briefing_context() -> str:
    with ThreadPoolExecutor() as ex:
        cal = ex.submit(_safe, context.upcoming_events, 1)
        wx = ex.submit(_safe, context.weather)
        sysinfo = ex.submit(_safe, context.system_status)
        last = ex.submit(_safe, activity.summarize, 24, START_TIME)
        files = ex.submit(_safe, activity.recent_files)
    now = datetime.datetime.now()
    greeting = ("Good morning" if 5 <= now.hour < 12 else
                "Good afternoon" if 12 <= now.hour < 18 else "Good evening")
    return f"""[STARTUP] You've just come online as the user logged in. Deliver the startup briefing.

Current time: {now.strftime('%A, %B %d, %I:%M %p')} (open with "{greeting}, sir")
System status: {sysinfo.result()}
Weather: {wx.result()}
Calendar (rest of today and tomorrow):
{cal.result()}
What the user was doing last session:
{last.result()}
Recently opened files:
{files.result()}

Match the spirit of this example, but don't copy it:
"Good evening, sir. All systems are operational. I've reviewed your schedule for tomorrow and identified three items requiring your attention. Your first meeting begins at nine o'clock. And, sir, your latest engineering project appears to have developed a minor complication. Nothing catastrophic. Yet."

Rules: four to six short sentences; cover the schedule (or that it's clear), the weather in a few words, and what they were last working on, with a dry witty remark; skip anything unavailable or not connected; don't invent details."""


# ---------- Helpers ----------

def wait_for_network(max_seconds: int = 45):
    """At login the network can take a few seconds to come up."""
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        try:
            socket.create_connection(("api.anthropic.com", 443), timeout=2).close()
            return
        except OSError:
            time.sleep(2)


def single_instance():
    mutex = win32event.CreateMutex(None, False, "JarvisAssistantSingleInstance")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        print("Jarvis is already running.")
        sys.exit(0)
    return mutex


def demo_voices():
    for name in BRITISH_VOICES:
        v = Voice(voice=name)
        print(f"\n--- {name} ---")
        v.say(f"Good evening, sir. This is the {name.split('_')[1].title()} voice. All systems are operational.")
        v.wait()
    print("\nSet your favourite in .env, e.g.  JARVIS_VOICE=bm_lewis")


def split_wake_word(heard: str) -> str | None:
    """Return the command after the wake word, or None if there's no wake word."""
    lower = heard.lower()
    for w in WAKE_WORDS:
        if w in lower:
            return heard[lower.index(w) + len(w):].strip(" ,.!?")
    return None


# ---------- Input ----------
# Speech, the console and the HUD all put commands on hud.commands; the main
# loop answers them one at a time.

class Turns:
    def __init__(self):
        self.idle = threading.Event()  # set while Jarvis is waiting for a command
        self.count = 0                 # bumped each time Jarvis starts answering
        self.followup_until = 0.0


def listen_loop(ears, voice: Voice, turns: Turns):
    while True:
        turns.idle.wait()  # don't listen while talking, or Jarvis would hear itself
        turn = turns.count
        in_followup = time.time() < turns.followup_until
        hud.emit("state", state="listening" if in_followup else "standby")
        print("(listening...)" if in_followup else '(say "Jarvis, ...")', flush=True)
        heard = ears.listen(timeout=max(1.0, turns.followup_until - time.time()) if in_followup else None)
        if not heard or turns.count != turn:  # nothing, or a typed command was answered meanwhile
            continue
        print(f"You: {heard}", flush=True)
        command = split_wake_word(heard)
        if command is None:
            if not in_followup:
                continue
            command = heard
        if not command:
            voice.say("Sir?")
            voice.wait()
            turns.followup_until = time.time() + FOLLOWUP_SECONDS
            continue
        turns.idle.clear()
        hud.commands.put(command)


def console_loop(turns: Turns):
    while True:
        turns.idle.wait()
        try:
            command = input("You: ").strip()
        except EOFError:
            command = "exit"
        if command:
            turns.idle.clear()
            hud.commands.put(command)


# ---------- Main ----------

def main():
    if "--voices" in sys.argv:
        demo_voices()
        return
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY found. Copy .env.example to .env and paste your key in.")
        sys.exit(1)

    _mutex = single_instance()  # noqa: F841 - held for the life of the process
    text_mode = "--text" in sys.argv
    print("JARVIS starting up...", flush=True)
    hud_on = os.getenv("JARVIS_HUD", "on").lower() != "off" and hud.start()
    if hud_on:
        hud.open_window()  # shows the boot sequence while everything loads

    # Load the voice and mic while the briefing info is fetched in the background
    with ThreadPoolExecutor() as ex:
        briefing = ex.submit(lambda: (wait_for_network(), gather_briefing_context())[1])
        voice = Voice(voice=os.getenv("JARVIS_VOICE", "bm_george"),
                      speed=float(os.getenv("JARVIS_VOICE_SPEED", "1.0")),
                      engine=os.getenv("JARVIS_TTS", "chatterbox"),
                      voice_sample=os.path.join(HERE, os.getenv("JARVIS_VOICE_SAMPLE", "voices/bm_george.wav")))
        ears = None
        if not text_mode:
            from ears import Ears
            ears = Ears()
        briefing_prompt = briefing.result()
        print(f"Voice engine: {voice.wait_ready(timeout=60)}", flush=True)

    tools.VOICE = voice
    if hud_on:
        hud.track_voice(lambda: voice.level)
    activity.start_logger()
    brain = Brain()
    hud.emit("state", state="thinking")
    respond(brain, voice, briefing_prompt)
    voice.wait()

    turns = Turns()
    if text_mode:
        threading.Thread(target=console_loop, args=(turns,), daemon=True).start()
    else:
        threading.Thread(target=listen_loop, args=(ears, voice, turns), daemon=True).start()
    hud.emit("state", state="standby")
    turns.idle.set()

    while True:
        command = hud.commands.get()
        turns.idle.clear()
        turns.count += 1
        hud.emit("you", text=command)
        if command.lower().strip(" .!") in EXIT_PHRASES:
            voice.say("Powering down. Goodbye, sir.")
            voice.wait()
            hud.emit("state", state="offline")
            break

        hud.emit("state", state="thinking")
        respond(brain, voice, command)
        voice.wait()
        turns.followup_until = time.time() + FOLLOWUP_SECONDS
        hud.emit("state", state="standby")
        turns.idle.set()


if __name__ == "__main__":
    main()
