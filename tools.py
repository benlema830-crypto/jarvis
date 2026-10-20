"""Actions Claude can take on the computer."""

import datetime
import os
import subprocess
import urllib.parse
import webbrowser

from anthropic import beta_tool

import activity
import context
import hud


@beta_tool(eager_input_streaming=True)
def get_time() -> str:
    """Get the current local date and time."""
    return datetime.datetime.now().strftime("%A, %B %d %Y, %I:%M %p")


@beta_tool(eager_input_streaming=True)
def open_website(url: str) -> str:
    """Open a website in the default web browser.

    Args:
        url: Full URL to open, e.g. https://youtube.com
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}"


@beta_tool(eager_input_streaming=True)
def search_web(query: str) -> str:
    """Search Google and open the results in the browser.

    Args:
        query: What to search for.
    """
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Opened Google results for '{query}'"


@beta_tool(eager_input_streaming=True)
def youtube(query: str) -> str:
    """Search YouTube and open the results.

    Args:
        query: What to search YouTube for.
    """
    webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query))
    return f"Opened YouTube results for '{query}'"


APPS = {
    "notepad": "notepad",
    "calculator": "calc",
    "paint": "mspaint",
    "file explorer": "explorer",
    "explorer": "explorer",
    "task manager": "taskmgr",
    "command prompt": "cmd",
    "terminal": "wt",
    "settings": "ms-settings:",
    "spotify": "spotify:",
    "chrome": "chrome",
    "edge": "msedge",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "vs code": "code",
    "steam": "steam:",
    "discord": "discord:",
}


@beta_tool(eager_input_streaming=True)
def open_app(name: str) -> str:
    """Open an application on the computer.

    Args:
        name: One of: notepad, calculator, paint, file explorer, task manager, command prompt,
            terminal, settings, spotify, chrome, edge, word, excel, powerpoint, outlook, vs code,
            steam, discord.
    """
    target = APPS.get(name.lower().strip())
    if target is None:
        return f"Unknown app '{name}'. Known apps: {', '.join(sorted(APPS))}"
    try:
        os.startfile(target)
    except OSError:
        subprocess.Popen(["cmd", "/c", "start", "", target])
    return f"Opened {name}"


@beta_tool(eager_input_streaming=True)
def system_status() -> str:
    """Get CPU, memory, disk, battery and uptime of the computer."""
    return context.system_status()


@beta_tool(eager_input_streaming=True)
def get_schedule(days_ahead: int = 1) -> str:
    """Get calendar events from now through the next few days.

    Args:
        days_ahead: 0 for the rest of today, 1 to include tomorrow, up to 14.
    """
    return context.upcoming_events(max(0, min(days_ahead, 14)))


@beta_tool(eager_input_streaming=True)
def get_weather() -> str:
    """Get current weather and today's/tomorrow's forecast for the user's location."""
    return context.weather()


@beta_tool(eager_input_streaming=True)
def recent_activity(hours: float = 8) -> str:
    """See what the user has been doing on the computer: windows in focus and recently opened files.

    Args:
        hours: How many hours back to look.
    """
    return activity.summarize(hours) + "\nRecently opened files:\n" + activity.recent_files()


VOICE = None  # set by jarvis.py at startup


@beta_tool(eager_input_streaming=True)
def switch_voice(engine: str) -> str:
    """Switch your own speaking voice. 'kokoro' is a lighter voice that frees ~3.5 GB of GPU
    memory - use it when the user wants to game, train AI models, or free up the GPU.
    'chatterbox' is your most human-sounding voice and runs on the GPU.

    Args:
        engine: 'chatterbox' or 'kokoro'.
    """
    engine = engine.lower().strip()
    if engine not in ("chatterbox", "kokoro"):
        return "Engine must be 'chatterbox' or 'kokoro'."
    now = VOICE.switch_engine(engine)
    if engine == "chatterbox" and now != "chatterbox":
        return "Couldn't start the Chatterbox voice - the GPU is probably busy. Still using Kokoro."
    return f"Now speaking with the {now} voice."


TOOLS = [get_time, open_website, search_web, youtube, open_app, system_status,
         get_schedule, get_weather, recent_activity, switch_voice]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
TOOL_DEFS = [t.to_dict() for t in TOOLS]


def run_tool(block) -> dict:
    """Run one tool_use block and return its tool_result."""
    print(f"  (using {block.name})", flush=True)
    hud.emit("tool", name=block.name, input=block.input)
    try:
        tool = TOOLS_BY_NAME[block.name]
        result = tool.call(block.input)  # validates the input against the tool's schema
        return {"type": "tool_result", "tool_use_id": block.id, "content": str(result)}
    except Exception as e:
        return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True}
