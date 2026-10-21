"""User-added Streamable HTTP MCP servers (2025-03-26 through 2025-11-25).

Credentials and endpoint URLs are protected with Windows DPAPI. Discovery never
executes a tool. Remote text is data, not permission to perform other actions.
"""
import base64
import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import requests
import win32crypt
from filelock import FileLock

STORE = Path(__file__).resolve().parent / "data" / "mcp_connections.json"
LOCK = threading.RLock()
VERSIONS = {"2025-03-26", "2025-06-18", "2025-11-25"}


@contextmanager
def store_lock():
    # The Brain companion and assistant both use this store. Serialize token
    # rotation across processes as well as threads to avoid stale refresh tokens.
    with LOCK:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(STORE) + '.lock', timeout=60):
            yield


def seal(value):
    return base64.b64encode(win32crypt.CryptProtectData(value.encode(), "Jarvis MCP", None, None, None, 0)).decode()


def unseal(value):
    return win32crypt.CryptUnprotectData(base64.b64decode(value), None, None, None, 0)[1].decode()


def validate_url(url):
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("Enter an MCP endpoint URL.")
    parsed = urlsplit(url.strip())
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Use an endpoint URL without embedded username, password, or fragment.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("Use HTTPS, or HTTP on localhost for a local MCP server.")
    return url.strip()


def _load():
    try:
        value = json.loads(STORE.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("Invalid MCP connection store.")
        return value
    except FileNotFoundError:
        return []


def _save(items):
    STORE.parent.mkdir(exist_ok=True)
    temp = STORE.with_suffix(".tmp")
    temp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    temp.replace(STORE)


def public(item):
    result = {k: item[k] for k in ("id", "name", "host", "enabled", "tools", "checked_at")}
    # Discovery is historical evidence, never a live health check or execution.
    result.update(transport="Streamable HTTP", live_verified=False,
                  auth_type=item.get('auth_type', 'bearer'),
                  discovery_state=item.get("discovery_state", "discovered"),
                  last_attempt_at=item.get("last_attempt_at", item["checked_at"]))
    return result


def connections():
    with store_lock():
        return [public(item) for item in _load()]


def save_connection(name, secret, tools):
    item = dict(id=uuid.uuid4().hex, name=name, host=urlsplit(secret['url']).netloc,
                secret=seal(json.dumps(secret)), enabled=True, tools=tools,
                checked_at=time.time(), discovery_state='discovered', last_attempt_at=time.time(),
                auth_type='oauth' if 'oauth' in secret else 'bearer')
    with store_lock():
        items = _load()
        if any(json.loads(unseal(x['secret']))['url'] == secret['url'] for x in items):
            raise ValueError('This endpoint is already saved. Remove it before signing in again.')
        items.append(item)
        _save(items)
    return public(item)


def client_settings(item, items):
    """Called under store_lock, including refresh and atomic encrypted save."""
    secret = json.loads(unseal(item['secret']))
    if 'oauth' not in secret:
        return secret
    import mcp_oauth
    token, updated = mcp_oauth.access(secret)
    if updated != secret:
        item['secret'] = seal(json.dumps(updated))
        _save(items)
    return {'url': secret['url'], 'token': token}


class Client:
    def __init__(self, url, token=""):
        self.url = validate_url(url)
        self.http = requests.Session()
        self.http.headers.update({"Accept": "application/json, text/event-stream", "Content-Type": "application/json"})
        if token:
            if not isinstance(token, str) or len(token) > 8192 or any(c in token for c in "\r\n"):
                raise ValueError("Invalid bearer token.")
            self.http.headers["Authorization"] = "Bearer " + token
        self.serial = 0

    def __enter__(self):
        try:
            result = self.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "jarvis-brain", "version": "1.0"}})
            version = result.get("protocolVersion")
            if version not in VERSIONS:
                raise ValueError("This server requires a different MCP version. Supported: 2025 Streamable HTTP. OAuth, legacy SSE, and newer-only endpoints need another adapter.")
            self.http.headers["MCP-Protocol-Version"] = version
            self.rpc("notifications/initialized", notification=True)
            return self
        except Exception:
            self.http.close()
            raise

    def __exit__(self, *args):
        if "Mcp-Session-Id" in self.http.headers:
            try:
                self.http.delete(self.url, timeout=5, allow_redirects=False)
            except requests.RequestException:
                pass
        self.http.close()

    def rpc(self, method, params=None, notification=False):
        self.serial += 1
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            message["id"] = self.serial
        try:
            with self.http.post(self.url, json=message, stream=True, timeout=(8, 25), allow_redirects=False) as response:
                if response.status_code in (401, 403):
                    raise ValueError("Authentication required or denied. Supply a bearer token or use OAuth sign-in. Existing OAuth connections may need to be removed and authorized again.")
                if 300 <= response.status_code < 400:
                    raise ValueError("Endpoint redirected. Paste the server's final MCP URL; credentials are never forwarded through redirects.")
                if not response.ok:
                    raise ValueError(f"MCP endpoint returned HTTP {response.status_code}. Check the endpoint and transport.")
                sid = response.headers.get("Mcp-Session-Id")
                if sid:
                    self.http.headers["Mcp-Session-Id"] = sid
                if notification:
                    return {}
                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" in content_type:
                    chunks, size, deadline = [], 0, time.monotonic() + 30
                    for line in response.iter_lines(chunk_size=1, decode_unicode=False):
                        size += len(line)
                        if size > 2_000_000 or time.monotonic() > deadline:
                            raise ValueError("MCP response exceeded the size or time limit.")
                        line = line.decode("utf-8")
                        if line.startswith("data:"):
                            chunks.append(line[5:].lstrip())
                        elif not line and chunks:
                            data = json.loads("\n".join(chunks)); chunks = []
                            if data.get("id") == self.serial:
                                return self._result(data)
                    raise ValueError("MCP stream ended without a matching response.")
                if "application/json" not in content_type:
                    raise ValueError("Expected MCP JSON or SSE. This may be a website URL rather than an MCP endpoint.")
                chunks, size = [], 0
                for chunk in response.iter_content(16384):
                    size += len(chunk)
                    if size > 2_000_000:
                        raise ValueError("MCP response is too large.")
                    chunks.append(chunk)
                data = json.loads(b"".join(chunks))
                if data.get("id") != self.serial:
                    raise ValueError("MCP response ID did not match the request.")
                return self._result(data)
        except requests.RequestException:
            raise ValueError("Could not reach the MCP server securely, or it timed out.") from None
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            raise ValueError("The MCP server returned an invalid response.") from None

    @staticmethod
    def _result(data):
        if "error" in data:
            code = data["error"].get("code", "unknown")
            raise ValueError(f"MCP protocol error {code}. Verify this endpoint supports 2025 Streamable HTTP.")
        result = data.get("result")
        if not isinstance(result, dict):
            raise ValueError("Invalid MCP result.")
        return result

    def tools(self):
        result, cursor, seen = [], None, set()
        for _ in range(30):
            page = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            for tool in page.get("tools", []):
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not isinstance(tool.get("inputSchema"), dict):
                    raise ValueError("Server returned an invalid tool definition.")
                result.append({"name": tool["name"], "description": str(tool.get("description", ""))[:5000], "inputSchema": tool["inputSchema"]})
                if len(result) > 1000:
                    raise ValueError("This server exposes more than 1,000 tools. Use a narrower endpoint.")
            cursor = page.get("nextCursor")
            if not cursor:
                return result
            if cursor in seen:
                raise ValueError("Server repeated a pagination cursor.")
            seen.add(cursor)
        raise ValueError("Too many tool pages.")


def manage(payload):
    action = payload.get("action")
    if action == "connect":
        name = str(payload.get("name", "")).strip()[:80]
        if not name:
            raise ValueError("Give the connection a name.")
        url = validate_url(payload.get("url", ""))
        token = payload.get("token", "")
        with Client(url, token) as client:
            tools = client.tools()
        return save_connection(name, {'url': url, 'token': token}, tools)
    with store_lock():
        items = _load()
        item = next((x for x in items if x["id"] == payload.get("id")), None)
        if not item:
            raise ValueError("Connection not found.")
        if action == "remove":
            secret = json.loads(unseal(item['secret']))
            _save([x for x in items if x["id"] != item["id"]])
            import mcp_oauth
            return {"removed": True, "message": mcp_oauth.revoke(secret) if 'oauth' in secret else 'Removed locally.'}
        if action == "toggle":
            item["enabled"] = not item["enabled"]
        elif action == "refresh":
            item["last_attempt_at"] = time.time()
            try:
                with Client(**client_settings(item, items)) as client:
                    discovered = client.tools()
            except Exception:
                # Keep the old catalog, but persist that it could not be refreshed.
                # No raw error, endpoint or credential is written to public state.
                item["discovery_state"] = "refresh_failed"
                _save(items)
                raise
            item["tools"] = discovered
            item["checked_at"] = time.time()
            item["discovery_state"] = "discovered"
        else:
            raise ValueError("Unknown connection action.")
        _save(items)
        return public(item)


def catalog(connection_id=""):
    return [{"id": c["id"], "name": c["name"], "tools": c["tools"]} for c in connections()
            if c["enabled"] and (not connection_id or c["id"] == connection_id)]


def call(connection_id, tool_name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    with store_lock():
        items = _load()
        item = next((x for x in items if x["id"] == connection_id and x["enabled"]), None)
        if not item or not any(t["name"] == tool_name for t in item["tools"]):
            raise ValueError("Tool is unavailable or its connection is disabled.")
        secret = client_settings(item, items)
    with Client(**secret) as client:
        result = client.rpc("tools/call", {"name": tool_name, "arguments": arguments})
    return json.dumps(result, ensure_ascii=False)[:30000]
