"""The local brain: a model on this PC, answered by Jarvis's own Ollama (127.0.0.1:11435, data/local-brain).

Free, private and offline: nothing leaves this PC and no plan limits apply. The default is an uncensored
("abliterated") Qwen 3.5 9B, chosen by the owner on 2026-11-11. It refuses far less than the plan models, so
the owner's own judgement is the only filter.

A 9B model can't carry all of Jarvis's tools (86 of them, about 16k tokens), so it gets the everyday set in
TOOLS. Its thinking is off, to keep spoken replies quick. Each turn starts from the recent conversation as plain
text, so nothing here needs closing when the brain changes.
"""
import base64
import json
import re
import threading
from types import SimpleNamespace

import requests

import agent_models
import model_provider
import privacy

URL = agent_models.LOCAL_URL
DEFAULT_MODEL = "huihui_ai/qwen3.5-abliterated:9b"
CONTEXT = 28672          # system prompt (~7k tokens) + these tools (~6.5k) + the recent conversation
KEEP_ALIVE = "10m"       # stays loaded between replies; Ollama unloads it after ten quiet minutes
TOOL_ROUNDS = 8
NOT_CHAT = ("embed", "-agent")   # embedding models and the agent's long-context copy aren't conversation brains
# Chosen 2026-11-11 from the owner's real use (every transcript): the workshop, screen and terminal agents, Spotify
# (through call_mcp_tool) and window control came in; the clipboard, file writing, completing tasks, forgetting,
# and listing or cancelling reminders (0-2 uses each) went out. Switch brains for those.
TOOLS = (
    "open_website", "show_search_results", "open_app", "list_apps", "find_files", "open_path",
    "look_at_screen", "media_control", "set_volume", "system_status", "get_schedule", "get_weather",
    "remember", "recall_memory", "update_memory", "set_reminder",
    "home_control", "home_status", "run_command", "read_file", "search_knowledge",
    "add_task", "list_tasks", "switch_model", "self_check",
    "workshop", "do_on_computer", "terminal_task", "terminal_status", "list_app_windows", "control_app_window",
    "audio_output", "sleep_computer", "list_mcp_tools", "call_mcp_tool",
)
NOTE = ("\n\nYou are running as the local model on this PC, not Claude or Codex. Only the tools you were given "
        "exist this session: there is no web_search and no research tool. 3D models go through workshop, clicking "
        "and typing on the screen through do_on_computer, multi-step computer jobs through terminal_task, music "
        "through call_mcp_tool (Spotify). Those run in the background: say you've started it, and only say it's "
        "built, showing or done when a tool result says so. If none of your tools can do something, say so in one "
        "sentence and offer to switch brains. "
        "Never say you'll do something unless you call the tool for it in this same reply. For news or other live facts, "
        "say you can't look that up while on the local brain, offer show_search_results, or suggest switching "
        "brains. To open an app use open_app; home_control is only for smart-home devices. Call a tool only with "
        "the arguments its definition lists.")
NOT_RUNNING = "The local model service isn't running. Start it with start-local-model.bat, or restart me."


def _session():
    session = requests.Session()
    session.trust_env = False  # this PC only, never through a proxy
    return session


def models():
    """Installed chat models, the uncensored default first. [] when the service isn't running."""
    try:
        with _session() as session:
            names = [m.get("name", "") for m in session.get(URL + "/api/tags", timeout=2).json().get("models", [])]
    except (requests.RequestException, ValueError):
        return []
    names = [n.removesuffix(":latest") for n in names if n and not any(word in n for word in NOT_CHAT)]
    return sorted(names, key=lambda n: (n != DEFAULT_MODEL, n))


def definitions(all_tools):
    """Ollama's tool format for the everyday set."""
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t["input_schema"]}}
            for t in all_tools if t["name"] in TOOLS]


def _images(found):
    """Base64 pictures from model_provider.tool_output's data: URLs, the way Ollama takes them."""
    out = []
    for image in found:
        url = image.get("image_url", "")
        if url.startswith("data:") and ";base64," in url:
            out.append(url.split(";base64,", 1)[1])
    return out


def chat(payload, cancel):
    """Stream one reply. Closing on `cancel` releases a blocked read at once."""
    try:
        response = _session().post(URL + "/api/chat", json={**payload, "stream": True}, stream=True,
                                   timeout=(5, 300))
    except requests.RequestException:
        raise model_provider.ProviderError(NOT_RUNNING) from None
    if response.status_code != 200:
        try:
            reason = str(response.json().get("error", ""))[:200]
        except ValueError:
            reason = ""
        response.close()
        if "not found" in reason:
            raise model_provider.ProviderError(f"The local model {payload['model']} isn't installed.")
        raise model_provider.ProviderError("The local model couldn't answer" + (f": {reason}." if reason else "."))
    done = threading.Event()

    def watch():
        while not done.wait(.1):
            if cancel.is_set():
                response.close()
                return
    threading.Thread(target=watch, daemon=True, name="local-cancel").start()
    try:
        for line in response.iter_lines():
            if cancel.is_set():
                return
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                raise model_provider.ProviderError("The local model returned a stream I couldn't read.") from None
            if event.get("error"):
                raise model_provider.ProviderError("The local model stopped with an error.")
            yield event
    except (requests.RequestException, OSError, AttributeError):
        if not cancel.is_set():
            raise model_provider.ProviderError("The local model stream disconnected.") from None
    finally:
        done.set()
        response.close()


HISTORY_TURNS = 10


def history(messages):
    """The owner's side of the recent conversation, and Jarvis's last question so a bare "yes" still makes sense.

    The model's own earlier replies are left out on purpose. Measured 2026-11-12: with Jarvis's real prompt it
    called the right tool 6 times in 6 on its own, but 1 in 6 with four earlier replies in front of it, and 0 in 2
    on the workshop with only the last one, because those replies narrated builds it never started and it copies
    them. Marking them as "no tool ran" didn't help (1 in 6)."""
    items = model_provider.text_history(messages)
    if not items:
        return []
    *earlier, current = items
    out = [m for m in earlier if m["role"] == "user"][-(HISTORY_TURNS - 1):]
    for message in reversed(earlier):
        if message["role"] == "assistant":
            last = message["content"].strip().split("\n")[-1]
            question = re.split(r"(?<=[.!?])\s+", last)[-1]
            if question.endswith("?"):
                out.append({"role": "assistant", "content": question})
            break
    return out + [current]


class Conversation:
    """Same shape as openai_api.Conversation.ask."""

    def ask(self, model_name, system, messages, all_tools, run_tool, delta, cancel):
        items = [{"role": "system", "content": privacy.redact(system) + NOTE}]
        items += history(messages)
        tools = definitions(all_tools)
        answer = []
        for _ in range(TOOL_ROUNDS):
            if cancel.is_set():
                raise InterruptedError()
            text, calls = [], []
            for event in chat({"model": model_name, "messages": items, "tools": tools, "think": False,
                               "keep_alive": KEEP_ALIVE, "options": {"num_ctx": CONTEXT}}, cancel):
                message = event.get("message") or {}
                piece = message.get("content") or ""
                if piece:
                    text.append(piece)
                    answer.append(piece)
                    if not cancel.is_set():
                        delta(piece)
                calls.extend(message.get("tool_calls") or [])
            if cancel.is_set():
                raise InterruptedError()
            items.append({"role": "assistant", "content": "".join(text), **({"tool_calls": calls} if calls else {})})
            if not calls:
                return "".join(answer)
            if answer and not answer[-1][-1:].isspace():  # say what came before the tools now, and don't glue the
                answer.append("\n")                       # next round's first sentence onto it ("sleep.There you go")
                delta("\n")
            for number, call in enumerate(calls[:16]):
                if cancel.is_set():
                    raise InterruptedError()
                function = call.get("function") or {}
                name, arguments = function.get("name", ""), function.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = None
                if name not in TOOLS or not isinstance(arguments, dict):
                    content, images = f"No tool {name!r} with those arguments this session.", []
                else:
                    result = run_tool(SimpleNamespace(name=name, id=call.get("id") or f"local-{number}",
                                                      input=arguments))
                    content, found = model_provider.tool_output(result["content"])
                    images = _images(found)
                items.append({"role": "tool", "tool_name": name, "content": privacy.redact(content),
                              **({"images": images} if images else {})})
        raise model_provider.ProviderError("The local model needed too many tool rounds.")


def validate(model):
    if model not in models():
        raise model_provider.ProviderError(f"The local model {model} isn't installed, or the service isn't running.")
    answer = Conversation().ask(model, "Reply briefly.", [{"role": "user", "content": "Reply with OK."}], [],
                                None, lambda text: None, threading.Event())
    if not answer.strip():
        raise model_provider.ProviderError("The local model returned no answer.")
    return answer


def release(model):
    """Unload it from the graphics card, which the voice and speech recognition share."""
    try:
        with _session() as session:
            session.post(URL + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=15)
    except requests.RequestException:
        pass
