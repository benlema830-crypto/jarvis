"""Sends quick everyday requests to the free local model; everything else stays on the selected brain.

Plain rules, not a model, so deciding takes no time. Only routes when Ollama is enabled and the
model is installed; a request that matches nothing here goes to the selected brain as before.
A small model sometimes says "done" without doing it, so an action answer with no tool behind
it is dropped and the selected brain answers instead (jarvis.Brain._run_local).
Change it in data/preferences.json: "local_router": {"enabled": false} or {"model": "..."}.
"""
import re

import ollama_brain
import preferences

DEFAULT_MODEL = 'qwen3:4b-instruct'
KEEP_ALIVE = '30m'  # stay loaded between requests; reloading takes ~3 s
# Only the request itself: with history, a small model copies its past "done" replies instead of
# acting. Follow-ups like "turn it back on" then fail locally and the selected brain, which has the
# conversation, answers them.
RECENT = 1

# A 4B model picks tools reliably only from a short list, and all of them overflow its context.
LOCAL_TOOLS = ('home_control', 'home_status', 'open_website', 'show_search_results', 'amazon_cart', 'youtube', 'open_app', 'media_control',
               'set_volume', 'app_audio_control', 'set_reminder', 'list_reminders', 'cancel_reminder',
               'get_weather', 'get_schedule', 'add_task', 'list_tasks', 'complete_task', 'system_status')

# Pause, resume and skip never get here: music.run handles them before any model.
# A request naming a smart-home device gets only the smart-home tools, so a small model can't
# answer "open YouTube on the Apple TV" by opening YouTube on the PC.
HOME = re.compile(r"\b(lights?|lamps?|tv|television|apple\ tv|plugs?|outlets?|fans?|scene|brightness|dim|brighter|dimmer)\b", re.I)
HOME_TOOLS = ('home_control', 'home_status')
QUICK = re.compile(r"""
      ^(mute|unmute)\b
    | \bvolume\b | \b(louder|quieter)\b
    | \b(lights?|lamps?|tv|television|apple\ tv|plugs?|outlets?|fans?|scene|brightness|dim|brighter|dimmer)\b
    | \b(turn|switch)\ (it\ )?(on|off)\b | \b(turn|switch)\ (the\ |my\ )?\w+(\ \w+)?\ (on|off)\b
    | ^(open|launch|start|pull\ up)\ \S
    | \b(remind\ me|reminders?|timer|alarm)\b
    | \b(to-?do|my\ tasks|task\ list)\b
    | \b(weather|forecast|temperature\ outside|going\ to\ rain)\b
    | ^what('s|\ is)\ (the\ )?(time|date|day)\b | \bwhat\ time\ is\ it\b
    | \bwhat('s|\ is)\ on\ my\ (schedule|calendar)\b
    | \b(amazon|my\ cart)\b
    | \b(cpu|ram|battery|system\ status)\b
    | ^(hi|hello|hey|thanks|thank\ you|good\ (morning|afternoon|evening|night)|how\ are\ you)\b
""", re.I | re.X)

# The only quick requests answered without a tool. Any other local answer must be backed by one.
CHAT = re.compile(r"""
      ^what('s|\ is)\ (the\ )?(time|date|day)\b | \bwhat\ time\ is\ it\b
    | ^(hi|hello|hey|thanks|thank\ you|good\ (morning|afternoon|evening|night)|how\ are\ you)\b
""", re.I | re.X)

# Reasoning, live web search, files, memory, agents and multi-step jobs stay on the selected brain.
HARD = re.compile(r"""
      \b(code|coding|script|program|bug|debug|fix|build|project|repo|file|folder|install|update|upgrade
        |agent|session|codex|claude|terminal|research|search\ for|look\ up|latest|news|price|cost|compare|best
        |explain|why|plan|write|draft|email|document|summar\w*|analy\w*|remember|forget|memory|screen|camera
        |meeting|appointment|book|schedule\ (a|an|my)|and\ then|after\ that
        |mode|focus|holo\w*|hologram|listening|voice|window|monitor|wake\ word
        |shopping\ list|notes?|vault|products|items|everything|conversation)\b
    | \?.*\?
""", re.I | re.X)


def settings():
    value = preferences.read().get('local_router')
    value = value if isinstance(value, dict) else {}
    model = value.get('model')
    return {'enabled': value.get('enabled', True) is not False,
            'model': model if isinstance(model, str) and model else DEFAULT_MODEL}


def choose(text, selected):
    """The local model for a quick request, and whether its answer needs a tool behind it;
    None to use the selected brain."""
    current = settings()
    if not current['enabled'] or selected.get('provider') == 'ollama' or not ollama_brain.enabled():
        return None
    text = text.strip()
    if len(text.split()) > 16 or not QUICK.search(text) or HARD.search(text):
        return None
    if current['model'] not in ollama_brain.models():
        return None
    return {'provider': 'ollama', 'model': current['model'], 'action': not CHAT.search(text),
            'tools': HOME_TOOLS if HOME.search(text) else LOCAL_TOOLS}


def tool_defs(names=LOCAL_TOOLS):
    from tools import TOOL_DEFS
    return [t for t in TOOL_DEFS if t['name'] in names]
