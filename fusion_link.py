"""Jarvis drives Autodesk Fusion through Fusion's own MCP server (http://127.0.0.1:27182/mcp, streamable HTTP).

Fusion has to be running with its MCP server switched on; the server answers on that port as soon as Fusion is up.
Only the "script" call is used: a Python script with run(_context) runs inside Fusion against the active design,
and whatever it prints comes back. An exception in the script comes back as an error, and Fusion rolls back what
that script did.

    fusion_link.available()            -> True when Fusion is answering
    fusion_link.run_script(code)       -> the script's printed output (raises FusionError on failure)
"""
import json
import threading

import requests

URL = "http://127.0.0.1:27182/mcp"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
_lock = threading.Lock()
_session = {"id": None}


class FusionError(RuntimeError):
    pass


def _answer(response):
    """The JSON-RPC reply, from a plain JSON body or from the data line of an event stream."""
    text = response.text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:") and line[5:].strip().startswith("{"):
            return json.loads(line[5:].strip())
    raise FusionError(f"Fusion gave an answer that couldn't be read ({response.status_code}).")


def _post(body, timeout, session=True):
    headers = dict(HEADERS)
    if session and _session["id"]:
        headers["mcp-session-id"] = _session["id"]
    return requests.post(URL, headers=headers, json=body, timeout=timeout)


def _connect(timeout=5):
    response = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                 "clientInfo": {"name": "jarvis", "version": "1"}}}, timeout, session=False)
    response.raise_for_status()
    _session["id"] = response.headers.get("mcp-session-id")
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout)


def available(timeout=3):
    try:
        with _lock:
            _connect(timeout)
        return True
    except (requests.RequestException, ValueError):
        return False


def _call(tool, arguments, timeout):
    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    with _lock:
        try:
            if not _session["id"]:
                _connect()
            response = _post(body, timeout)
            if response.status_code in (400, 404):      # the session ended (Fusion restarted): start a new one
                _connect()
                response = _post(body, timeout)
        except requests.ConnectionError:
            raise FusionError("Fusion isn't running, or its MCP server is off.")
        except requests.Timeout:
            raise FusionError(f"Fusion didn't answer within {timeout} seconds.")
    reply = _answer(response)
    if "error" in reply:
        raise FusionError(str(reply["error"].get("message", reply["error"]))[:2000])
    result = reply.get("result") or {}
    text = "\n".join(str(c.get("text", "")) for c in result.get("content", []) if c.get("type") == "text")
    if result.get("isError"):
        raise FusionError(text[:3000] or "Fusion reported an error.")
    return text


def _output(text):
    """Fusion wraps a script's printout in JSON; dig the printed text out when it does."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict):
        if data.get("success") is False:
            raise FusionError(str(data.get("error") or data.get("message") or text)[:3000])
        for key in ("message", "output", "stdout", "result", "text"):
            if isinstance(data.get(key), str):
                return data[key]
        if isinstance(data.get("output"), list):
            return "\n".join(str(item.get("content", item)) if isinstance(item, dict) else str(item)
                             for item in data["output"])
    return text


def run_script(code, read_only=False, timeout=300):
    """Run a Fusion API script (it must define run(_context)) and return what it printed."""
    arguments = {"featureType": "script", "object": {"script": code}}
    if read_only:
        arguments["object"]["readOnly"] = True
    text = _call("fusion_mcp_execute", arguments, timeout)
    lowered = text.lower()
    if "traceback (most recent call last)" in lowered or '"success": false' in lowered:
        raise FusionError(text[:3000])
    return _output(text)
