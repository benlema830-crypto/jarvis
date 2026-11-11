"""Which model an agent runs on. Jarvis chooses per task; this is the menu and the plumbing.

  opus    Claude Opus 5.5 on the owner's Claude plan. The default: most work goes here.
  sonnet  Claude Sonnet 5.5. Routine, well-defined jobs where a quicker answer is worth more than depth.
  haiku   Claude Haiku 5.5. One-step chores.
  codex   Codex on the owner's ChatGPT plan. Runs inside Codex's sandbox, and can take a message while it works.
          For when the owner asks for it, for code that shouldn't be trusted, or when the Claude plan limit is hit.
  local   A model on this PC (Ollama, 127.0.0.1:11435), driven by Claude Code. Free, private and offline, but far
          slower and weaker: small jobs only, and only when the owner asks for local.

Effort is separate: low for small jobs, medium for ordinary ones, high for big or stubborn ones. Left blank,
the effort learned from how similar tasks went is used (task_effort.py).

Away jobs (queued for while the owner is gone) always use Codex: nobody is there to answer a question, so they
need its sandbox. The owner's preference "agent_model" changes the default choice.
None of these can spend API credits: the Claude choices use the Claude Code sign-in, and the local one never
leaves this PC.
"""
import json
import urllib.request

import preferences

DEFAULT = "opus"
CLAUDE = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
CHOICES = (*CLAUDE, "codex", "local")
EFFORTS = ("low", "medium", "high")
LOCAL_URL = "http://127.0.0.1:11435"
LOCAL_BASE = "qwen3.5:9b-q8_0"     # the model downloaded on 2026-11-04
LOCAL_AGENT = "qwen3.5-agent"      # the same weights with room for an agent's instructions and tools
LOCAL_CONTEXT = 32768              # at Ollama's default (4096) it lost the task and just said hello
# What people say, mapped to a choice. Anything else is refused with the list, never guessed.
ALIASES = {"": "", "auto": "", "default": "", "claude": "opus", "opus 5.5": "opus", "claude opus": "opus",
           "claude-opus-5-5": "opus", "sonnet 5.5": "sonnet", "claude sonnet": "sonnet", "claude-sonnet-5-5": "sonnet",
           "haiku 5.5": "haiku", "claude haiku": "haiku", "claude-haiku-5-5": "haiku", "gpt": "codex", "chatgpt": "codex",
           "openai": "codex", "qwen": "local", "ollama": "local", "offline": "local", "local model": "local"}
WORDS = {"opus": "Claude Opus 5.5", "sonnet": "Claude Sonnet 5.5", "haiku": "Claude Haiku 5.5", "codex": "Codex",
         "local": "the local model"}


def default_choice() -> str:
    value = str(preferences.read().get("agent_model", DEFAULT)).strip().lower()
    return value if value in CHOICES else DEFAULT


def _local(path, payload=None, timeout=5):
    request = urllib.request.Request(LOCAL_URL + path, data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # this PC only, never via a proxy
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


def local_ready() -> str:
    """"" when the local agent model can be used; otherwise the reason, in plain words. Makes the large-context
    copy of the model the first time (no download: it reuses the weights already on disk)."""
    try:
        names = {m.get("name", "").removesuffix(":latest") for m in _local("/api/tags").get("models", [])}
    except (OSError, ValueError):
        return "the local model service isn't running (start-local-model.bat starts it)"
    if LOCAL_AGENT in names:
        return ""
    if LOCAL_BASE not in names:
        return f"the local model {LOCAL_BASE} isn't installed"
    try:
        _local("/api/create", {"model": LOCAL_AGENT, "from": LOCAL_BASE, "parameters": {"num_ctx": LOCAL_CONTEXT},
                               "stream": False}, timeout=120)
    except (OSError, ValueError):
        return "the local model couldn't be prepared"
    return ""


def release_local() -> bool:
    """Unload the local model from the graphics card once its job is done. It takes about 10 GB of the 16, which
    the voice and speech recognition share; left loaded (Ollama keeps it five minutes) it squeezes them."""
    try:
        _local("/api/generate", {"model": LOCAL_AGENT, "keep_alive": 0}, timeout=15)
        return True
    except (OSError, ValueError):
        return False


def resolve(model: str = "", effort: str = "") -> dict:
    """Turn what Jarvis asked for into what to run. Raises ValueError with the choices for anything unknown."""
    said = " ".join(str(model or "").lower().split())
    choice = ALIASES.get(said, said) or default_choice()
    if choice not in CHOICES:
        raise ValueError(f"Unknown agent model '{model}'. Choose one of: {', '.join(CHOICES)}.")
    effort = str(effort or "").strip().lower()
    if effort in ("", "auto", "default", "normal"):
        effort = ""
    elif effort not in EFFORTS:
        raise ValueError(f"Unknown effort '{effort}'. Choose low, medium or high, or leave it blank.")
    plan = {"choice": choice, "words": WORDS[choice], "effort": effort, "env": {},
            "provider": "codex" if choice == "codex" else "claude", "model": CLAUDE.get(choice, "")}
    if choice == "local":
        problem = local_ready()
        if problem:
            raise ValueError(f"The local model can't be used right now: {problem}. Choose another model.")
        plan.update(model=LOCAL_AGENT, effort="",  # effort levels mean nothing to it
                    env={"ANTHROPIC_BASE_URL": LOCAL_URL, "ANTHROPIC_AUTH_TOKEN": "ollama", "ANTHROPIC_API_KEY": "",
                         "NO_PROXY": "127.0.0.1,localhost", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    return plan


def spoken(plan) -> str:
    """"Claude Opus 5.5, high effort" for the start message and the report."""
    return plan["words"] + (f", {plan['effort']} effort" if plan.get("effort") else "")
