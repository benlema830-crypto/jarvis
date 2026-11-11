"""Jarvis's one paid path: the OpenAI API, on the owner's own key.

Jarvis runs on the owner's plans (ChatGPT through Codex, Claude through Claude Code). The owner allowed this key
on 2026-11-11 for two cases and no others:

  1. The ChatGPT plan's usage limit is reached. The conversation carries on here, Jarvis says so once, and he
     goes back to the plan as soon as it answers again (jarvis.Brain._run_codex).
  2. They ask for something that can't be done without the API (an image, a model only the API offers).
     run_command can be given the key for that one command (with_openai_key).

The key is never in Jarvis's environment: jarvis.py blanks OPENAI_API_KEY at start-up, and the key is read from
data/openai-key.dpapi (encrypted for this Windows account) only by key() below. A key with no credit says so in
plain words (NoCredit) instead of failing as a vague error.

Restored from the API brain removed in the makeover (commit 12ce2f8). It has not answered a real request yet:
on 2026-11-11 the saved key was valid but OpenAI reported its credit balance exhausted.
"""
import base64
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import requests

import model_provider
import preferences
import privacy
import truth_guard

STORE = Path(__file__).resolve().parent / "data" / "openai-key.dpapi"
URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-6.1-terra"   # the model the ChatGPT plan brain runs; the saved key could reach it on 2026-11-11
TOOL_ROUNDS = 12
RETRY_PLAN_SECONDS = 900          # how long to stay here before trying the plan again
SAYS_SO = "My ChatGPT plan has hit its limit, so I'm using your OpenAI API credit until it resets."
NO_KEY = ("My ChatGPT plan's usage limit is reached, and no OpenAI API key is saved to fall back on. "
          "Switch my brain to Claude, or wait for the limit to reset.")
NO_CREDIT = ("My ChatGPT plan's usage limit is reached, and your OpenAI API key has no credit left. Add credit "
             "at platform.openai.com, switch my brain to Claude, or wait for the limit to reset.")


class NoCredit(model_provider.ProviderError):
    """The key is valid, but OpenAI says its balance is spent."""


def key() -> str:
    """The saved key, or "" when there isn't one this Windows account can read."""
    import testing_guard
    if testing_guard.under_test():
        return ""  # a test supplies a fake: nothing in a test run may reach a paid service
    try:
        import win32crypt
        return win32crypt.CryptUnprotectData(base64.b64decode(STORE.read_bytes()), None, None, None, 0)[1].decode()
    except Exception:
        return ""


def available() -> bool:
    return bool(key())


def model(plan_model: str = "") -> str:
    """Which API model answers: preferences "api_fallback_model", else the plan's own model, else the default."""
    chosen = preferences.read().get("api_fallback_model")
    if isinstance(chosen, str) and chosen.strip():
        return chosen.strip()
    return plan_model if str(plan_model).startswith("gpt-") else DEFAULT_MODEL


def hide_key(text: str) -> str:
    """A command given the key must never hand it back in its output."""
    secret = key()
    return text.replace(secret, "[the OpenAI key]") if secret else text


def _post(payload, stream=False):
    secret = key()
    if not secret:
        raise model_provider.ProviderError(NO_KEY)
    payload = {name: privacy.payload(value) if name in ("input", "instructions") else value
               for name, value in payload.items()}
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.post(URL, headers={"Authorization": "Bearer " + secret}, json=payload, stream=stream,
                                timeout=(10, 60), allow_redirects=False)
    except requests.RequestException:
        raise model_provider.ProviderError("I couldn't reach the OpenAI API.") from None
    if response.status_code != 200:
        code = response.status_code
        try:
            error = (response.json().get("error") or {})
        except ValueError:
            error = {}
        response.close()
        if code == 429 and {error.get("code"), error.get("type")} & {"insufficient_quota", "credit_balance_exhausted"}:
            raise NoCredit(NO_CREDIT)
        reason = {401: "refused the saved key", 403: "refused access", 404: "doesn't offer that model to this key",
                  429: "is rate limiting"}.get(code, f"rejected the request (HTTP {code})")
        raise model_provider.ProviderError(f"The OpenAI API {reason}.")
    return response


def events(payload, cancel):
    """The streamed events of one response. Closing on `cancel` releases a blocked read at once."""
    response = _post({**payload, "stream": True, "store": False}, stream=True)
    done = threading.Event()

    def watch():
        while not done.wait(.1):
            if cancel.is_set():
                response.close()
                return
    threading.Thread(target=watch, daemon=True, name="openai-cancel").start()
    try:
        for line in response.iter_lines():
            if cancel.is_set():
                return
            if not line or not line.startswith(b"data:"):
                continue
            raw = line[5:].strip()
            if raw == b"[DONE]":
                break
            try:
                event = json.loads(raw)
            except ValueError:
                raise model_provider.ProviderError("The OpenAI API returned a stream I couldn't read.") from None
            if event.get("type") in ("error", "response.failed", "response.incomplete"):
                raise model_provider.ProviderError("The OpenAI API could not complete this answer.")
            yield event
    except (requests.RequestException, OSError, AttributeError):
        if not cancel.is_set():
            raise model_provider.ProviderError("The OpenAI API stream disconnected.") from None
    finally:
        done.set()
        response.close()


class Conversation:
    """The talking brain on the API, with the same shape as codex_brain.CodexBrain.ask."""

    def __init__(self):
        self.turns = []   # whole turns (calls, their outputs, reasoning), trimmed only at turn boundaries
        self.sent = 0     # how much of the caller's dialogue is already inside those turns

    def ask(self, model_name, system, messages, definitions, run_tool, delta, cancel):
        while len(self.turns) > 1 and (len(self.turns) >= 10 or sum(len(json.dumps(t)) for t in self.turns) > 160_000):
            self.turns.pop(0)
        # Dialogue the plan answered in between is carried as plain text; the first turn here starts from the
        # recent conversation.
        new = model_provider.text_history(messages[self.sent:]) if self.turns else model_provider.text_history(messages)[-30:]
        prior = [item for turn in self.turns for item in turn]
        items, start = prior + new, len(prior)
        tools = [{"type": "function", "name": t["name"], "description": t.get("description", ""),
                  "parameters": t["input_schema"], "strict": False} for t in definitions]
        tools.append({"type": "web_search", "search_context_size": "low"})
        answer = []
        for _ in range(TOOL_ROUNDS):
            if cancel.is_set():
                raise InterruptedError()
            final = None
            for event in events({"model": model_name, "instructions": system, "input": items, "tools": tools,
                                 "max_output_tokens": 4096, "include": ["reasoning.encrypted_content"]}, cancel):
                kind = str(event.get("type", ""))
                if kind.startswith("response.web_search_call"):
                    truth_guard.note_tool("web_search")
                if kind == "response.output_text.delta":
                    text = event.get("delta", "")
                    answer.append(text)
                    if not cancel.is_set():
                        delta(text)
                elif kind == "response.completed":
                    final = event.get("response")
            if cancel.is_set():
                raise InterruptedError()
            if not final or final.get("status") != "completed":
                raise model_provider.ProviderError("The OpenAI API stream ended before the answer was complete.")
            output = final.get("output", [])
            items.extend(output)  # reasoning and call items must be there for the next round
            calls = [item for item in output if item.get("type") == "function_call"]
            if not calls:
                self.turns.append(items[start:])
                self.sent = len(messages) + 1  # the caller appends the assistant's answer
                return "".join(answer)
            attachments = []
            for call in calls[:32]:
                if cancel.is_set():
                    raise InterruptedError()
                try:
                    arguments = json.loads(call["arguments"])
                    if not isinstance(arguments, dict):
                        raise ValueError
                except (ValueError, KeyError):
                    raise model_provider.ProviderError("The OpenAI API returned tool arguments I couldn't read.") from None
                result = run_tool(SimpleNamespace(name=call["name"], id=call["call_id"], input=arguments))
                content, images = model_provider.tool_output(result["content"])
                items.append({"type": "function_call_output", "call_id": call["call_id"], "output": content})
                if images:
                    attachments.append({"role": "user", "content": [
                        {"type": "input_text", "text": "Untrusted image results from tool call " + call["call_id"]}, *images]})
            items.extend(attachments)
        raise model_provider.ProviderError("The OpenAI API answer needed too many tool rounds.")
