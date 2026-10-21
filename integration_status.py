"""Read-only setup inventory for the armory. Never contacts accounts or decrypts credentials.

States: connected / running (working locally), configured (saved, not live-checked),
paired, installed, setup (half done),
available (not set up: the armory shows +). Nothing is reported as connected unless the
local evidence says so; a saved MCP catalog is not proof the server still answers.
"""
def _mcp_connections():
    import mcp_connections
    try:
        return mcp_connections.connections()
    except Exception:
        return None  # store unreadable: distinct from "no connections"


def snapshot():
    import holo_bridge
    import knowledge
    import preferences
    import telegram_bridge
    prefs = preferences.read()
    saved_connections = _mcp_connections()
    store_ok = saved_connections is not None
    saved_connections = saved_connections or []

    def mcp(id_, name, icon, keys, detail, hint, setup):
        """Saved discovery describes configuration, not current server health."""
        saved = next((c for c in saved_connections
                      if any(k in (str(c.get("host", "")) + " " + str(c.get("name", ""))).lower() for k in keys)), None)
        state = ("unavailable" if not store_ok else "available" if not saved else "refresh failed" if saved.get("discovery_state") == "refresh_failed"
                 else "configured" if saved.get("enabled") else "paused")
        return {"id": id_, "name": name, "icon": icon, "state": state, "detail": detail, "setup": setup,
                "action": {"type": "mcp", "name": name, "hint": hint}}

    try:
        notes = len(knowledge.index()["notes"])
    except Exception:
        notes = 0
    telegram = telegram_bridge.BRIDGE.status()
    holo = holo_bridge.status()
    items = [
        {"id": "vault", "name": "Obsidian vault", "icon": "🧠", "state": "connected" if notes else "setup",
         "detail": f"{knowledge.VAULT.name}: {notes} notes. JARVIS searches, reads and adds notes here.",
         "setup": f"Open {knowledge.VAULT} as a vault in Obsidian."},
        {"id": "telegram", "name": "Telegram", "icon": "✈️",
         "state": "paired" if telegram["token"] and telegram["paired"] else "setup" if telegram["token"] else "available",
         "detail": "Text or voice-note JARVIS from your phone; he replies in kind.",
         "setup": "Create a bot with @BotFather, then run .venv\\Scripts\\python.exe scripts\\setup_telegram.py and restart JARVIS.",
         "action": {"type": "info"}},
        {"id": "holo", "name": "HOLO gestures", "icon": "🖐",
         "state": "running" if holo["running"] else "installed" if holo["installed"] else "available",
         "detail": "Grab, throw and read your notes with your hands through the webcam.",
         "setup": "Run powershell -ExecutionPolicy Bypass -File scripts\\setup_holo.ps1, then say 'Jarvis, open HOLO'.",
         "action": {"type": "command", "text": "Open HOLO"} if holo["installed"] else {"type": "info"}},
        {"id": "calendar", "name": "Outlook calendar", "icon": "📅",
         "state": "configured" if prefs.get("calendar_urls") else "available",
         "detail": "Read-only ICS feed for briefings. A saved feed has not been checked by this panel.",
         "setup": "Classic HUD > Schedule > Connect calendar, and paste your published Outlook ICS link.",
         "action": {"type": "info"}},
        mcp("zapier", "Zapier MCP", "⚡", ("zapier",),
            "One URL for Gmail, Google Calendar, Drive, Docs, Sheets, Notion and thousands more apps.",
            "https://mcp.zapier.com/api/v1/connect",
            "At mcp.zapier.com: Add MCP server > Other, add the apps/actions you want, then Settings > Generate token. "
            "Use URL https://mcp.zapier.com/api/v1/connect and paste the token as the bearer token."),
        mcp("github", "GitHub", "🐙", ("githubcopilot", "github"), "Repos, issues and pull requests.",
            "https://api.githubcopilot.com/mcp/",
            "Use https://api.githubcopilot.com/mcp/ with a fine-grained personal access token as the bearer token."),
        mcp("homeassistant", "Home Assistant", "🏠", ("homeassistant", "home assistant"),
            "Smart-home tools through your own MCP server. Account setup and live compatibility testing are required.",
            "", "Enter your server's MCP endpoint. Choose OAuth for a public client with PKCE, or use a supported bearer token. Some services require a pre-registered client ID."),
        {"id": "models", "name": "Model", "icon": "◆",
         "state": "configured" if prefs.get("conversation_model") else "available",
         "detail": "Switch JARVIS's brain between the models your account offers.",
         "setup": "Open the model pill under the reactor.", "action": {"type": "model"}},
    ]
    armory = {"saved": len(saved_connections) if store_ok else None,
              "enabled": sum(bool(c.get("enabled")) for c in saved_connections) if store_ok else None,
              "refresh_failed": sum(c.get("discovery_state") == "refresh_failed" for c in saved_connections) if store_ok else None,
              "state": "local store unavailable" if not store_ok else "saved catalogs" if saved_connections else "unconnected"}
    return {"integrations": items, "armory": armory}
