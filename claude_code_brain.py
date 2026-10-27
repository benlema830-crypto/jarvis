"""Conversation through Claude Code on the owner's Claude subscription (no API credits).

Works like codex_brain.py: Jarvis keeps his own tools and approvals. The tools are served to
Claude Code from inside this process (an in-process MCP server), so every call still goes
through tools.run_tool. Claude Code's own shell/file tools are off; only live web search and
fetch are allowed. The owner's Claude Code settings, hooks and project memory are not loaded.

One Claude Code process stays connected between turns so replies don't pay a start-up cost.
Billing guard: ANTHROPIC_API_KEY is blanked for the subprocess, and each new session checks that
Claude Code reports no API key in use; otherwise the turn is refused rather than billed.
"""
import asyncio
import atexit
import base64
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import privacy

HERE = Path(__file__).resolve().parent
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
SERVER = "jarvis"
STALL_SECONDS = 180   # no message from Claude Code for this long ends the turn
MAX_TURNS = 20        # model turns (tool rounds) per reply, like Codex's tool cap


class LimitReached(RuntimeError):
    """The Claude plan's usage limit is reached (or billing refused)."""


class WouldBillAPI(RuntimeError):
    """Claude Code would have used an API key instead of the subscription."""


def _mcp_content(content):
    """Jarvis tool_result content -> MCP content blocks (text and images)."""
    if isinstance(content, str):
        return [{"type": "text", "text": privacy.redact(content)}]
    blocks = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            blocks.append({"type": "text", "text": privacy.redact(str(block.get("text", "")))})
        elif block.get("type") == "image" and block.get("source", {}).get("type") == "base64":
            source = block["source"]
            blocks.append({"type": "image", "data": source["data"], "mimeType": source.get("media_type", "image/png")})
    return blocks or [{"type": "text", "text": "No content returned."}]


def render(messages) -> str:
    """Dialogue to send as one prompt. A single new user message is sent as-is."""
    if len(messages) == 1 and messages[0]["role"] == "user":
        return messages[0]["content"]
    *earlier, last = messages
    lines = [("User: " if m["role"] == "user" else "You said: ") + m["content"] for m in earlier]
    context = "Conversation so far (for context):\n" + "\n".join(lines)
    if last["role"] == "user":
        return f"{context}\n\nThe user now says: {last['content']}"
    return context + "\n\nContinue from here."


class ClaudeCodeBrain:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="claude-code-brain").start()
        self.client = None
        self.model = self.system = None
        self.sent_messages = 0
        self.run_tool = None
        self.tool_count = 0
        self.cancel = None
        atexit.register(self.close)

    def _sync(self, coroutine, timeout=None):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    # ---------- tools ----------

    def _call_tool(self, name, args):
        self.tool_count += 1
        if (self.cancel is not None and self.cancel.is_set()) or self.tool_count > MAX_TURNS or not self.run_tool:
            return {"content": [{"type": "text", "text": "Tool execution stopped."}], "is_error": True}
        output = self.run_tool(SimpleNamespace(name=name, id=f"cc{self.tool_count}", input=args))
        return {"content": _mcp_content(output.get("content", "")), "is_error": bool(output.get("is_error"))}

    def _server(self, definitions):
        from claude_agent_sdk import create_sdk_mcp_server, tool
        tools = []
        for definition in definitions:
            name = definition["name"]

            async def handler(args, name=name):
                return await asyncio.to_thread(self._call_tool, name, args if isinstance(args, dict) else {})
            tools.append(tool(name, definition.get("description", ""), definition["input_schema"])(handler))
        return create_sdk_mcp_server(SERVER, tools=tools)

    # ---------- session ----------

    async def _connect(self, model, system, definitions):
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system,
            tools=["WebSearch", "WebFetch"],          # no shell, files or subagents
            allowed_tools=[f"mcp__{SERVER}", "WebSearch", "WebFetch"],
            permission_mode="dontAsk",                # anything not allowed above is denied
            mcp_servers={SERVER: self._server(definitions)},
            strict_mcp_config=True,                   # not the owner's own MCP servers
            setting_sources=[],                       # not the owner's settings, hooks or CLAUDE.md
            include_partial_messages=True,            # stream text so Jarvis speaks as it arrives
            effort="low",                             # quick replies, like the API conversation path
            max_turns=MAX_TURNS,
            cwd=str(HERE),
            env={"ANTHROPIC_API_KEY": ""},            # use the claude.ai login, never the API key
        )
        client = ClaudeSDKClient(options)
        await client.connect()
        # Checked before any message is sent: with an API key in play the account reports
        # apiKeySource "ANTHROPIC_API_KEY"; on the subscription it reports the plan instead.
        account = ((await client.get_server_info()) or {}).get("account") or {}
        if account.get("apiKeySource") not in (None, "none"):
            await client.disconnect()
            raise WouldBillAPI(f"Claude Code would use an API key ({account['apiKeySource']}).")
        return client

    async def _disconnect(self):
        client, self.client = self.client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    def close(self):
        try:
            self._sync(self._disconnect(), timeout=10)
        except Exception:
            pass
        self.model = self.system = None

    # ---------- one turn ----------

    async def _turn(self, prompt, delta, cancel):
        from claude_agent_sdk import AssistantMessage, RateLimitEvent, ResultMessage, StreamEvent, SystemMessage
        await self.client.query(prompt)
        answer, interrupted = [], False
        stream = self.client.receive_response().__aiter__()
        while True:
            step = asyncio.ensure_future(stream.__anext__())
            deadline = time.monotonic() + STALL_SECONDS
            while not step.done():
                await asyncio.wait({step}, timeout=0.1)
                if cancel.is_set() and not interrupted:
                    interrupted = True
                    await self.client.interrupt()
                if not step.done() and time.monotonic() > deadline:
                    step.cancel()
                    raise TimeoutError("Claude Code conversation stalled.")
            try:
                message = step.result()
            except StopAsyncIteration:
                break
            if isinstance(message, SystemMessage) and message.subtype == "init":
                source = message.data.get("apiKeySource", "none")
                if source != "none":
                    await self.client.interrupt()
                    raise WouldBillAPI(f"Claude Code would use an API key ({source}).")
            elif isinstance(message, StreamEvent) and message.parent_tool_use_id is None:
                event = message.event
                if event.get("type") == "content_block_delta" and event.get("delta", {}).get("type") == "text_delta":
                    text = event["delta"].get("text", "")
                    answer.append(text)
                    if not cancel.is_set():
                        delta(text)
            elif isinstance(message, RateLimitEvent) and message.rate_limit_info.status == "rejected":
                raise LimitReached("Claude plan usage limit reached.")
            elif isinstance(message, AssistantMessage) and message.error in ("rate_limit", "billing_error"):
                raise LimitReached(f"Claude plan unavailable ({message.error}).")
            elif isinstance(message, ResultMessage):
                if interrupted:
                    raise InterruptedError()
                if message.is_error and message.subtype != "error_max_turns":
                    text = (message.result or "").lower()
                    if re.search(r"usage limit|rate limit|limit reached|out of extra usage", text):
                        raise LimitReached(message.result or "Claude plan usage limit reached.")
                    raise RuntimeError(f"Claude Code could not complete the turn ({message.subtype}).")
        if interrupted:
            raise InterruptedError()
        return "".join(answer)

    def ask(self, model, system, messages, definitions, run_tool, delta, cancel):
        """Same contract as CodexBrain.ask: streams text to `delta`, returns the full answer."""
        import model_provider
        system = privacy.redact(system)
        self.run_tool, self.cancel, self.tool_count = run_tool, cancel, 0
        fresh = self.client is None or self.model != model or self.system != system
        try:
            if fresh:
                self._sync(self._disconnect())
                self.client = self._sync(self._connect(model, system, definitions), timeout=120)
                self.model, self.system = model, system
                history = model_provider.text_history(messages)[-30:]
            else:
                history = model_provider.text_history(messages[self.sent_messages:]) or \
                    model_provider.text_history(messages)[-1:]
            answer = self._sync(self._turn(render(history), delta, cancel))
            self.sent_messages = len(messages) + 1  # the caller appends the assistant answer
            return answer
        except BaseException:
            self.close()  # never reuse an interrupted or failed session
            raise


def validate(model):
    brain = ClaudeCodeBrain()
    try:
        answer = brain.ask(model, "Reply briefly.", [{"role": "user", "content": "Reply with OK."}], [],
                           None, lambda text: None, threading.Event())
        if not answer.strip():
            raise RuntimeError("Claude Code returned no answer.")
        return answer
    finally:
        brain.close()
