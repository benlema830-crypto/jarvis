# JARVIS project map

`C:\Users\Lemab\Documents\Jarvis Agent` is the navigation hub. Use the desktop
**JARVIS Brain** shortcut for the app and **JARVIS Workspace** for files.

| Hub folder | Contents |
| --- | --- |
| 01 Launchers | Brain, classic assistants, Codex, voice shutdown helper |
| 02 Knowledge | Link to the actual Obsidian vault |
| 03 Development | Links to Blue, Orange, and LocalVoice installations |
| 04 Plans | Link to this repository's docs/plans |
| 05 Reports | Link to this repository's data/reports |
| 06 References | Video screenshots and earlier UI previews |

Directory links are navigation aids. Installed repositories, virtual environments,
models, credentials and the registered Obsidian vault retain their real paths.

## Processes

| Process | Port | Started by | Role |
| --- | --- | --- | --- |
| `jarvis.py` (the assistant) | 7778 (classic HUD + event stream) | `open_brain.py`, `run.bat` | Ears, voice, brain, tools, Telegram bridge, HOLO watcher, calendar heads-ups |
| `brain.py` (Brain companion) | 7781 | `open_brain.py` | Serves the Brain page, the graph data, Eyes frames and Watch/Focus sessions; proxies chat/status to 7778 |
| `qwen_fast_worker.py` | — | the assistant | Local Qwen voice synthesis in the LocalVoice environment |
| HOLO `server.py` (optional) | 4890 | "Jarvis, open HOLO" | The separate hand-gesture notes app |
| Isolated `ollama.exe serve` (optional) | 11435 | `start-local-model.bat` | Local-only conversation models; idle until a model is requested |

## Source components

| Area | Files |
| --- | --- |
| Main loop, prompt, turn handling | jarvis.py |
| Conversation providers | codex_brain.py (Codex + live web search), ollama_brain.py (optional local models), model_provider.py, model_credentials.py |
| Tools the AI can call | tools.py (registry), plus tasks.py, documents.py, dictation.py, direct_files.py, app_audio.py, window_control.py, desktop.py |
| Voice and hearing | voice.py, qwen_voice.py, qwen_fast_worker.py, ears.py, voice_health.py, enroll_voice.py |
| Knowledge vault | knowledge.py, knowledge_events.py, semantic_search.py (local embeddings) |
| Project continuity and routines | project_memory.py, routines.py, hud/productivity.js |
| Brain page | hud/brain.html, hud/brain.css, hud/brain.js (graph, inspector, reactor, chat), hud/panels.js (dialogs), hud/modes.js (Eyes/Watch/Holo/Focus) |
| Brain server | brain.py, eyes.py, visual_modes.py, integration_status.py, workspace.py |
| Classic HUD | hud.py, hud/index.html |
| Phone and gestures | telegram_bridge.py, holo_bridge.py |
| Proactive | reminders.py, nudges.py, activity.py |
| MCP armory | mcp_connections.py (encrypted store and tool transport), mcp_oauth.py (browser authorization and token lifecycle) |
| Agents | agent_sessions.py, terminal.py, agent.py, cc_guard.py, approvals.py |
| Setup scripts | scripts/setup_telegram.py, scripts/setup_holo.ps1, scripts/setup_local_brain.py, scripts/setup_openai_key.py |
| Checks | scripts/verify_project.py; tests/ (unit tests), tests/check_brain_browser.py, tests/check_holo_browser.py (inert browser checks) |

## Runtime data

`data/` is git-ignored and holds memories, preferences, logs, encrypted credentials
(OpenAI key, MCP tokens, Telegram token), voice identity, reports and backups.
`data/backups/pre-polish-ui-2026-10-21.zip` keeps the previous Brain UI scripts.
Documents JARVIS writes go to `Documents\JARVIS Documents`; to-dos live in the vault's `Tasks.md`.
The isolated Ollama runtime, weights, log, and synthetic inference report live in
`data/local-brain/`. OAuth credentials share the encrypted MCP store in `data/`;
pending authorization codes and PKCE verifiers are never saved to disk.

Project handoffs are dated JSON entries in `data/handoffs/`. Named routine definitions live
in `data/routines.json`; approval tokens stay in memory and expire. The local semantic index is
`data/vault-vectors.sqlite3`, rebuilt incrementally from the selected vault with the installed
`embeddinggemma:300m` model. These files contain personal context and are not committed.
