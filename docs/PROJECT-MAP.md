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
| `desktop_orb.py` | Uses 7781 | Jarvis Orb desktop shortcut / More menu | Native WebView2 orb; always on top when compact, expands to full Brain workspace |
| VoiceStudio app | 3900 | the user / Jarvis on voice warm-up | Default voices (VoiceStudio profiles), GPU synthesis |
| `qwen_fast_worker.py` | — | the assistant, when the Qwen voice is chosen | Local Qwen voice synthesis in `models\qwen-voice` |
| HOLO `server.py` (optional) | 4890 | "Jarvis, open HOLO" | The separate hand-gesture notes app |
| Isolated `ollama.exe serve` (optional) | 11435 | `start-local-model.bat` | Local-only conversation models; idle until a model is requested |
| Home Assistant OS (Raspberry Pi 5, separate device) | 80 at `HA_URL` (Ethernet 192.168.0.44) | always on | Smart-home devices and automations; runs even when the PC is off |

## Source components

| Area | Files |
| --- | --- |
| Main loop, prompt, turn handling | jarvis.py |
| Conversation providers | codex_brain.py (Codex + live web search), ollama_brain.py (optional local models), router.py (quick requests -> local qwen3:4b-instruct, else the selected brain), model_provider.py, model_credentials.py |
| Tools the AI can call | tools.py (registry), plus tasks.py, documents.py, dictation.py, direct_files.py, app_audio.py, window_control.py, desktop.py |
| Voice and hearing | voice.py, voicestudio_voice.py, qwen_voice.py, qwen_fast_worker.py, ears.py, voice_health.py, enroll_voice.py |
| Knowledge vault | knowledge.py, knowledge_events.py, semantic_search.py (local embeddings) |
| Project continuity and routines | project_memory.py, routines.py, hud/productivity.js |
| Digests, privacy and file tools | digests.py, privacy.py, artifacts.py, hud/automation.js |
| Response preferences | response_settings.py, jarvis.py next-turn refresh, tools.py response_style, hud/automation.js |
| Brain page | hud/brain.html, hud/brain.css, hud/brain.js (graph, inspector, reactor, chat), hud/panels.js (dialogs), hud/modes.js (Eyes/Watch/Holo/Focus) |
| Brain server | brain.py, graph_organization.py (project neighborhoods, display labels and relationship evidence), eyes.py, visual_modes.py, integration_status.py, workspace.py |
| Classic HUD | hud.py, hud/index.html |
| Phone and gestures | telegram_bridge.py, holo_bridge.py |
| Smart home | home_assistant.py (HA_URL + HA_TOKEN in .env; no locks/alarms/covers), tools.py home_control / home_status |
| Proactive | reminders.py, nudges.py, activity.py, daily_review.py (Briefs/ in the vault, once a day on Codex) |
| Research | research.py (start_research: background Codex web research -> Research/ in the vault), digests.py (scheduled) |
| Email | gmail.py (read-only Gmail API, DPAPI tokens in data/gmail.enc), scripts/setup_gmail.py, docs/GMAIL.md |
| Memory and continuity | memory.py (core facts, history on update), working_memory.py (where things stand, every turn; project briefs for agents; data/project_log.jsonl), memory_proposals.py (journal proposes, owner approves; Decisions/Decision log.md) |
| Performance | performance.py (data/turn_metrics.jsonl, scorecard), task_effort.py, scripts/benchmark_models.py |
| MCP armory | mcp_connections.py (encrypted store and tool transport), mcp_oauth.py (browser authorization and token lifecycle) |
| Agents | agent_sessions.py, terminal.py, agent.py, cc_guard.py, approvals.py, task_effort.py (learned per-task effort) |
| Direct terminal | direct_tools.py (run_command, read_file, search_text, edit_file, write_file: the conversation's own shell and file tools, through cc_guard) |
| Away work | away_jobs.py (queue for builds and research the owner asked for; private copies, its own test re-run, Telegram progress, spoken summary on return) |
| Truthfulness | truth_guard.py (ClaimGate holds an unbacked "I've done it" and makes the brain answer again; agent OUTCOME lines; which tools ran this turn). home_assistant.control reads each device back before reporting |
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

## Don't Wake the Giant (added 2026-11-02)

A separate configured project at `C:\Users\Lemab\Documents\Don't Wake the Giant`.
The project catalog is shared by agent sessions and handoffs; daily review includes
registered projects. The Project tools, routines and Resume selectors include it.
Use `open_agent_session(name="Giant Builder", project="Don't Wake the Giant")` or
`project_handoff(project="Don't Wake the Giant", ...)` after restarting Jarvis/Brain.
The vault project note is `Projects/Don't Wake the Giant.md`.

Giant Builder retains its saved Codex thread ID, task, report and timeline. Only
project and working-directory fields were reassigned. A guarded migration in
`data/session-project-migrations.json` also applies on the next manager load, so
an older running process cannot permanently restore the former Rocket Frontier
association. The migration checks the original thread ID and project. It does not
start an agent task or rewrite provider conversation files. A real provider
continuation has not been launched as a setup test; resume uses the existing
thread ID with the new working directory.

The existing OneDrive `Dont Wake the Giant v2.rbxl` is referenced only. It and all
Rocket Frontier files/places were left untouched. No game export/build/publish or
Studio sync was performed. Source/build workflow is not established by setup.

## How agents run (2026-11-04)

Small jobs don't use agents: the conversation runs commands and edits files itself (`direct_tools.py`).
Agents are for long jobs. `agent_sessions.SessionManager` holds saved sessions; each running task is a
`Worker`. Up to 4 run at once, but only one may change a given folder at a time. `message_agent` delivers
words to a running Codex agent through `turn/steer` without stopping it (Claude sessions can't take this).
A turn ending doesn't mean the job is done: agents end their report with `OUTCOME: done|partial|blocked|failed`,
which sets `ok`, the spoken status and the project log. `entry["evidence"]` is what Jarvis itself watched
happen, kept separate from what the report claims. `terminal_task` starts a clean conversation unless it's
a follow-up (`continue_previous`), and can work in any folder.

`data/claim_checks.jsonl` records each sentence the claim gate stopped, for checking how well it's working.
`"local_router": {"enabled": false}` in preferences turned off the local quick-request model on 2026-11-04
(slower to first words than the brain on similar turns, and it reported actions it hadn't checked).

## Work while the owner is away (2026-11-04)

`queue_away_job` puts a build or research job in `data/away_jobs.json`. It starts right away, survives a restart, and
never waits for anyone. `away_jobs` is the status, stop and resume tool.

A build runs one at a time in `~/Documents/Jarvis Builds/<name>-<id>`: a local clone with its remote removed, or a new
repo. Its agent is the `Away Builder` session, flagged `unattended`: approval policy `never` in the Codex sandbox, no
outside tools, no web search, no secrets in its environment, and no spoken questions. `.git` is read-only to the agent, so
Jarvis commits for it (with hooks off) and fetches the result into the owner's repo as `jarvis/<name>-<id>`. He never merges.

The agent saying done isn't enough. Jarvis re-runs the tests through `codex sandbox`, because the agent wrote them, and
never falls back to running them outside it. Only failures that weren't there before the agent began count: Jarvis's own
DPAPI tests always fail in the sandbox. Failures go back to the agent, for up to 4 rounds of up to 30 minutes each.

A project needs git and at least one commit to get a private copy, or it's refused. A copy is made from the last commit,
so uncommitted files aren't in it; Jarvis says so at the start and the end.
