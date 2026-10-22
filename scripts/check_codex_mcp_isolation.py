"""Live check: which native MCP tools a Jarvis-started Codex process can see. No model turn is run.

    .venv\\Scripts\\python.exe scripts\\check_codex_mcp_isolation.py

Prints server names and tool counts only (no configuration values)."""
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_sessions  # noqa: E402


def visible(isolate):
    conn = agent_sessions.Connection(str(agent_sessions.HERE), lambda event: None, threading.Event(), isolate_mcp=isolate)
    try:
        conn.call('initialize', {'clientInfo': {'name': 'jarvis_check', 'title': 'Jarvis check', 'version': '1.0'}})
        conn.send({'method': 'initialized', 'params': {}})
        data = conn.call('mcpServerStatus/list', {'detail': 'toolsAndAuthOnly'}).get('data', [])
        return {item['name']: len(item.get('tools') or {}) for item in data}
    finally:
        conn.close()


if __name__ == '__main__':
    default, isolated = visible(False), visible(True)
    print('work sessions (user config):', default)
    print('conversation and research  :', isolated)
    sys.exit(0 if not any(isolated.values()) else 1)
