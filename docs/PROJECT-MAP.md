# Jarvis CEO project map

Jarvis CEO is the active project, previously named Jarvis Brain. The workspace at
`C:\Users\Lemab\Documents\Jarvis Agent` contains the `Jarvis CEO` project folder; it is the only
Jarvis (the older variants were deleted on 2026-10-26). Open **Jarvis CEO** on the desktop for the app
and **JARVIS Workspace** for the active project's files.

| Jarvis CEO folder | Contents |
| --- | --- |
| 01 Launchers | Jarvis CEO app and Codex development launchers |
| 02 Knowledge | Link to the existing Obsidian vault |
| 03 Development/Jarvis CEO Source | Link to the main repository at `C:\Users\Lemab\jarvis` |
| 04 Plans | Link to this repository's docs/plans |
| 05 Reports | Link to this repository's data/reports |
| 06 References | Video screenshots and earlier UI previews |

The Start menu "Jarvis" launcher uses the same source as CEO; it is not a separate codebase.

Directory links organize the projects without relocating installed repositories,
virtual environments, models, credentials or the registered Obsidian vault.
Jarvis speaks with voices saved in the VoiceStudio app (local, 127.0.0.1:3900); any saved voice
appears in the Brain page's voice picker. The Qwen voice's environment, model cache and voice
reference live in `models\qwen-voice` (gitignored).
Move records and original shortcut backups are in `data/reports/ceo-separation-2026-10-22`.

## Processes

| Process | Port | Started by | Role |
| --- | --- | --- | --- |
| `jarvis.py` (the assistant) | 7778 (classic HUD + event stream) | `open_brain.py`, `run.bat` | Ears, voice, brain, tools, Telegram bridge, HOLO watcher, calendar heads-ups |
| `brain.py` (Brain companion) | 7781 | `open_brain.py` | Serves the Brain page, the graph data, Eyes frames and Watch/Focus sessions; proxies chat/status to 7778 |
| VoiceStudio app | 3900 | the user / Jarvis on voice warm-up | Default voices (VoiceStudio profiles), GPU synthesis |
| `qwen_fast_worker.py` | — | the assistant, when the Qwen voice is chosen | Local Qwen voice synthesis in `models\qwen-voice` |
| HOLO `server.py` (optional) | 4890 | "Jarvis, open HOLO" | The separate hand-gesture notes app |
| Isolated `ollama.exe serve` (optional) | 11435 | `start-local-model.bat` | Local-only conversation models; idle until a model is requested |

## Source components

| Area | Files |
| --- | --- |
| Main loop, prompt, turn handling | jarvis.py |
| Conversation providers | codex_brain.py (Codex + live web search), ollama_brain.py (optional local models), model_provider.py, model_credentials.py |
| Tools the AI can call | tools.py (registry), plus tasks.py, documents.py, dictation.py, direct_files.py, app_audio.py, window_control.py, desktop.py |
| Voice and hearing | voice.py, voicestudio_voice.py, qwen_voice.py, qwen_fast_worker.py, ears.py, voice_health.py, enroll_voice.py |
| Knowledge vault | knowledge.py, knowledge_events.py, semantic_search.py (local embeddings) |
| Project continuity and routines | project_memory.py, routines.py, hud/productivity.js |
| Digests, privacy and file tools | digests.py, privacy.py, artifacts.py, hud/automation.js |
| Response preferences | response_settings.py, jarvis.py next-turn refresh, tools.py response_style, hud/automation.js |
| Brain page | hud/brain.html, hud/brain.css, hud/brain.js (graph, inspector, reactor, chat), hud/panels.js (dialogs), hud/modes.js (Eyes/Watch/Holo/Focus) |
| Brain server | brain.py, eyes.py, visual_modes.py, integration_status.py, workspace.py |
| Classic HUD | hud.py, hud/index.html |
| Phone and gestures | telegram_bridge.py, holo_bridge.py |
| Proactive | reminders.py, nudges.py, activity.py |
| MCP armory | mcp_connections.py (encrypted store and tool transport), mcp_oauth.py (browser authorization and token lifecycle) |
| Agents | agent_sessions.py, terminal.py, agent.py, cc_guard.py, approvals.py, task_effort.py (learned per-task effort) |
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

Response preferences live in `data/response-settings.json`. The development continuation for a native
Linux port and the 58-item improvement backlog is `docs/plans/CLAUDE-LINUX-HANDOFF.txt`.
Git excludes personal data, voices and models; the handoff documents separate migration requirements.

`data/digests.json` stores schedules and attempts; `data/digests/` stores silent reports.
`data/privacy.json` stores selected text filters; `memory.json.epoch` invalidates pre-edit model context.
The Brain process owns the digest scheduler. XLSX/PDF/PPTX outputs live alongside Word documents in
`Documents/JARVIS Documents`; no Office process or account is required to create them.
