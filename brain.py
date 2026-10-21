"""Local knowledge graph and a companion UI for the running Blue Jarvis."""
import ast
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.getenv("JARVIS_BRAIN_PORT", "7781"))


def snapshot():
    """Real local data only: vault notes (grouped by top folder), memories, recent turns, tools.

    Edges are resolved note links or collection membership, never inferred relationships.
    """
    nodes = [{"id": "root", "label": "JARVIS", "kind": "Core", "group": "JARVIS",
              "body": "Your local assistant. Notes come from your Obsidian vault; memories and "
                      "conversations are what JARVIS saved locally."}]
    links = []

    def add(key, label, kind, body, parent="root", group=None, kind_link="collection"):
        nodes.append(dict(id=key, label=label, kind=kind, group=group or kind, body=body))
        if parent:
            links.append(dict(source=parent, target=key, kind=kind_link))
        return nodes[-1]

    def read(name):
        try:
            return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    import knowledge
    vault = knowledge.index()
    add("vault", "Obsidian vault", "Core", f"{knowledge.VAULT.name}: your Obsidian vault: editable Markdown notes. Bright links are "
        "real [[wikilinks]] or Markdown links between notes; dim links show which folder a note lives in.",
        group="JARVIS")
    folders = {}
    for note in vault["notes"]:
        top = note["path"].split("/")[0] if "/" in note["path"] else "Notes"
        if top not in folders:
            folders[top] = add("folder:" + top, top, "Folder", f"Vault folder {top}.", "vault", group=top)
        node = add("note:" + note["path"], note["title"], "Note", note["content"], "folder:" + top, group=top)
        node.update(source=note["path"], uri=note["uri"], modified=note.get("modified"))
    links.extend({"source": "note:" + link["source"], "target": "note:" + link["target"], "kind": "note-link"}
                 for link in vault["links"])

    facts = [f for f in read("memory.json")[:200] if isinstance(f, dict) and isinstance(f.get("fact"), str)]
    if facts:
        add("memory", "Long-term memory", "Memory", "Facts JARVIS saved with the remember tool.")
        for i, fact in enumerate(facts):
            add(f"memory-{i}", fact["fact"][:55], "Memory", fact["fact"], "memory")
    turns = [t for t in read("recent_conversation.json")[-20:] if isinstance(t, dict)]
    if turns:
        add("recent", "Conversations", "Conversation", "Recent exchanges saved for continuity.")
        for i, turn in enumerate(turns):
            add(f"recent-{i}", str(turn.get("user", "Conversation"))[:55], "Conversation",
                f"{turn.get('time', '')}\n\nYou: {turn.get('user', '')}\n\nJarvis: {turn.get('assistant', '')}", "recent")

    tree = ast.parse((ROOT / "tools.py").read_text(encoding="utf-8"))
    registered = set()
    for item in tree.body:
        if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TOOLS" for t in item.targets):
            registered = {n.id for n in item.value.elts if isinstance(n, ast.Name)}
    add("tools", "Tool armory", "Tool", "Capabilities JARVIS can use. These are not your knowledge.")
    for item in tree.body:
        if isinstance(item, ast.FunctionDef) and item.name in registered:
            add("tool-" + item.name, item.name.replace("_", " ").title(), "Tool",
                ast.get_docstring(item) or item.name, "tools")

    degree = {}
    for link in links:
        for end in (link["source"], link["target"]):
            degree[end] = degree.get(end, 0) + 1
    for node in nodes:
        node["degree"] = degree.get(node["id"], 0)
    return {"nodes": nodes, "links": links, "vault": {"name": knowledge.VAULT.name, "path": str(knowledge.VAULT),
            "notes": len(vault["notes"]), "skipped": vault["skipped"], "unresolved": vault["unresolved"]}}


ASSETS = {"/brain.css": ("brain.css", "text/css"), "/brain.js": ("brain.js", "text/javascript"),
          "/panels.js": ("panels.js", "text/javascript"), "/modes.js": ("modes.js", "text/javascript"),
          "/": ("brain.html", "text/html")}
# Read-only pass-through to the assistant's own HUD server (port from voice-profile.json).
PROXY = {"GET": {"/events", "/status", "/voice-health", "/settings", "/sessions", "/classic", "/models", "/intel"},
         "POST": {"/command", "/stop", "/settings", "/models"}}


def notify_assistant(event):
    """Focus drift/completion -> the assistant, which turns it into a short spoken callout."""
    import urllib.request
    from instance_config import HUD_PORT
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{HUD_PORT}/notify", data=json.dumps(event).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(request, timeout=3).close()
    except OSError:
        pass  # the assistant may be offline; the Brain still shows the count


def serve():
    # Separate listener: never starts another microphone or AI worker.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import urllib.request
    import urllib.error
    from instance_config import HUD_PORT
    from visual_modes import controller as visuals
    from eyes import controller as eyes
    visuals.on_event = notify_assistant

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, result, code=200, content_type="application/json"):
            body = result if isinstance(result, bytes) else json.dumps(result).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def payload(self, limit):
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= limit:
                raise ValueError("Request is empty or too large.")
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object.")
            return value

        def local(self, route):
            """JSON routes served by this companion: (body, status), or None when the path isn't one."""
            get, post = self.command == "GET", self.command == "POST"
            if route == "/brain-data" and get:
                return snapshot(), 200
            if route == "/visual-modes" and (get or post):
                if get:
                    return visuals.snapshot(), 200
                return visuals.request(self.payload(1000)), 200
            if route == "/focus-apps" and get:
                from visual_modes import running_apps
                return {"apps": running_apps()}, 200
            if route == "/eyes" and (get or post):
                if get:
                    return eyes.snapshot(), 200
                request = self.payload(900_000)
                if request.get("action") == "coach":  # periodic glance, only while Eyes are on
                    if eyes.snapshot()["on"]:
                        notify_assistant({"event": "eyes_check"})
                    return eyes.snapshot(), 200
                return eyes.request(request), 200
            if route == "/tasks" and get:
                import tasks
                return {"tasks": tasks.items()}, 200
            if route == "/eyes/frame" and get:
                if self.headers.get("Origin"):
                    raise PermissionError()
                try:
                    jpeg, age = eyes.latest()
                except LookupError as error:
                    return {"error": str(error)}, 404
                import base64
                return {"jpeg": base64.b64encode(jpeg).decode(), "age": age}, 200
            if route == "/holo" and get:
                import holo_bridge
                return holo_bridge.status(), 200
            if route == "/integration-status" and get:
                import integration_status
                return integration_status.snapshot(), 200
            if route == "/workspace" and get:
                import workspace
                return {"folders": workspace.catalog()}, 200
            if route == "/workspace/open" and post:
                import workspace
                try:
                    return workspace.open_folder(self.payload(1000).get("id", "")), 200
                except (ValueError, OSError):
                    return {"error": "Could not open the selected workspace folder."}, 400
            if route == "/mcp" and (get or post):
                import mcp_connections
                try:
                    result = {"connections": mcp_connections.connections()} if get else mcp_connections.manage(self.payload(16000))
                    return result, 200
                except ValueError:
                    raise
                except Exception:
                    return {"error": "Could not access the local connection store. "
                                     "No credentials are included in this response."}, 500
            if route == "/mcp/oauth" and post:
                import mcp_oauth
                return mcp_oauth.manage(self.payload(16000)), 200
            if route == "/build-plan" and get:
                plan = ROOT / "docs" / "plans" / "NIGHT-BUILD-PROMPT.txt"
                return {"text": plan.read_text(encoding="utf-8") if plan.is_file() else ""}, 200
            return None

        def dispatch(self):
            if self.headers.get("Host") not in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}:
                return self.send_error(403)
            if self.command == "POST" and self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send_error(400)
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}:
                return self.send_error(403)
            route = self.path.split("?")[0]
            if self.command == "GET" and route in ASSETS:
                name, content_type = ASSETS[route]
                return self.reply((ROOT / "hud" / name).read_bytes(), content_type=content_type + "; charset=utf-8")
            try:
                handled = self.local(route)
                if handled:
                    return self.reply(*handled)
            except PermissionError:
                return self.send_error(403)
            except (ValueError, UnicodeError) as error:
                return self.reply({"error": str(error)}, 400)
            if route == "/stop" and self.command == "POST":
                visuals.stop()  # Brain's Stop also ends local observation, even with the assistant offline
            if self.path not in PROXY.get(self.command, set()):
                return self.send_error(404)
            self.proxy()

        def proxy(self):
            try:
                size = int(self.headers.get("Content-Length", 0))
                if size < 0 or size > 16000:
                    return self.send_error(400)
                body = self.rfile.read(size) if self.command == "POST" else None
                path = "/" if self.path == "/classic" else self.path
                request = urllib.request.Request(f"http://127.0.0.1:{HUD_PORT}{path}", data=body,
                                                 headers={"Content-Type": "application/json"}, method=self.command)
                upstream = urllib.request.urlopen(request, timeout=25)
            except urllib.error.HTTPError as exc:
                # An older running assistant has no diagnostics endpoint yet.
                return self.send_error(502 if self.path == "/voice-health" and exc.code == 404 else 503,
                                       "Assistant diagnostics unavailable" if self.path == "/voice-health" else "Assistant unavailable")
            except (OSError, ValueError, urllib.error.URLError):
                return self.send_error(503, "JARVIS is offline. Open the JARVIS Brain shortcut to start him.")
            with upstream:
                self.send_response(200)
                self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    if self.path == "/events":
                        while line := upstream.readline():
                            self.wfile.write(line)
                            self.wfile.flush()
                    else:
                        self.wfile.write(upstream.read())
                except OSError:
                    pass

        do_GET = dispatch
        do_POST = dispatch

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    finally:
        visuals.stop()
        eyes.request({"action": "stop"})
        server.server_close()


if __name__ == "__main__":
    serve()


