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
| `brain.py` (Brain companion) | 7781 | `open_brain.py` | Serves the Jarvis page (3D model, graph, Console) and the graph data; proxies chat/status to 7778 |
| `desktop_orb.py` | Uses 7781 | Jarvis Orb desktop shortcut / More menu | Native WebView2 orb; always on top when compact, expands to full Brain workspace |
| VoiceStudio app | 3900 | the user / Jarvis on voice warm-up | Default voices (VoiceStudio profiles), GPU synthesis |
| `qwen_fast_worker.py` | — | the assistant, when the Qwen voice is chosen | Local Qwen voice synthesis in `models\qwen-voice` |
| HOLO `server.py` (optional) | 4890 | "Jarvis, open HOLO" | The separate hand-gesture notes app |
| Isolated `ollama.exe serve` (optional) | 11435 | `start-local-model.bat` | Vault search by meaning, and the local agent model (`qwen3.5-agent`); idle until asked for |
| Home Assistant OS (Raspberry Pi 5, separate device) | 80 at `HA_URL` (Ethernet 192.168.0.44) | always on | Smart-home devices and automations; runs even when the PC is off |

## Source components

| Area | Files |
| --- | --- |
| Main loop, prompt, turn handling | jarvis.py |
| Conversation brains | claude_code_brain.py (Claude on the owner's Claude plan, the default), codex_brain.py (Codex on the ChatGPT plan), model_provider.py (which one talks). There is no paid API path: the API, local chat and router code was removed on 2026-11-10 |
| Tools the AI can call | tools.py (registry), plus tasks.py, dictation.py, direct_files.py, app_audio.py, window_control.py, desktop.py |
| Voice and hearing | voice.py, voicestudio_voice.py, qwen_voice.py, qwen_fast_worker.py, ears.py, voice_health.py, enroll_voice.py |
| Knowledge vault | knowledge.py, knowledge_events.py, semantic_search.py (local embeddings) |
| Project continuity | project_memory.py, hud/productivity.js |
| Privacy | privacy.py (redaction before anything goes to a model), hud/automation.js |
| Response preferences | response_settings.py, jarvis.py next-turn refresh, tools.py response_style, hud/automation.js |
| Jarvis page | hud/brain.html, hud/brain.css, hud/brain.js (3D model, graph, inspector, chat), hud/console.js (the Console view: turns, tools and receipts), hud/cards.js (cards with their buttons), hud/panels.js (dialogs), hud/modes.js (Holo hand control) |
| Brain server | brain.py, graph_organization.py (project neighborhoods, display labels and relationship evidence), integration_status.py, workspace.py |
| Classic HUD | hud.py, hud/index.html |
| Phone and gestures | telegram_bridge.py, holo_bridge.py |
| Smart home | home_assistant.py (HA_URL + HA_TOKEN in .env; no locks/alarms/covers), tools.py home_control / home_status |
| Proactive | reminders.py, nudges.py, activity.py, daily_review.py (Briefs/ in the vault, once a day on Codex), heartbeat.py (half-hourly plain checks and the owner's checklist), attention.py (say it now or hold it; five unprompted updates a day), presence_greeting.py, morning_wakeup.py |
| Research | research.py (start_research: background Codex web research -> Research/ in the vault) |
| Email | gmail.py (Gmail API: reads, and sends after the owner's yes; DPAPI tokens in data/gmail.enc), scripts/setup_gmail.py, docs/GMAIL.md |
| Memory and continuity | memory.py (core facts, history on update), working_memory.py (where things stand, every turn; project briefs for agents; data/project_log.jsonl), decision_log.py (the journal's decisions go to Decisions/Decision log.md; no approval queue), history.py (search past conversations; the readable copy of memory in the vault) |
| Performance | performance.py (data/turn_metrics.jsonl, scorecard), task_effort.py, scripts/benchmark_models.py |
| MCP armory | mcp_connections.py (encrypted store and tool transport), mcp_oauth.py (browser authorization and token lifecycle) |
| Agents | agent_sessions.py (sessions and workers), terminal.py (a Claude Code run), agent.py (the screen agent), agent_models.py (which model a job runs on), parallel.py (several agents on one job, with an optional lead), cc_guard.py (what an agent may do), wsl_sandbox.py and sandbox/ (the Linux sandbox an unattended Claude agent runs in), approvals.py, task_effort.py (learned per-task effort) |
| Direct terminal | direct_tools.py (run_command, read_file, search_text, edit_file, write_file: the conversation's own shell and file tools, through cc_guard) |
| Away work | away_jobs.py (queue for builds and research the owner asked for; private copies, its own test re-run, Telegram progress, spoken summary on return; Codex by default, Claude Fable 5.2 when asked) |
| Truthfulness | truth_guard.py (a receipt for every action; ClaimGate holds an unbacked "I've done it" and makes the brain answer again; agent OUTCOME lines; which tools ran this turn). home_assistant.control reads each device back before reporting |
| Setup scripts | scripts/setup_telegram.py, scripts/setup_holo.ps1, scripts/setup_local_brain.py, scripts/setup_phone.py, scripts/setup_wsl_sandbox.py |
| Checks | scripts/run_tests.py (the unit tests, and proof they left data/ alone); scripts/verify_project.py; ruff.toml (lint for likely bugs); tests/check_brain_browser.py, tests/check_holo_browser.py (inert browser checks); scripts/measure.py (speed scorecard); docs/reviews/ (code reviews) |

## Runtime data

`data/` is git-ignored and holds memories, preferences, logs, encrypted credentials
(MCP tokens, Telegram and phone tokens), voice identity, reports and backups.
`data/backups/pre-polish-ui-2026-10-21.zip` keeps the previous Brain UI scripts.
Documents JARVIS writes go to `Documents\JARVIS Documents`; to-dos live in the vault's `Tasks.md`.
The isolated Ollama runtime, weights, log, and synthetic inference report live in
`data/local-brain/`. OAuth credentials share the encrypted MCP store in `data/`;
pending authorization codes and PKCE verifiers are never saved to disk.

Project handoffs are dated JSON entries in `data/handoffs/`. The local semantic index is
`data/vault-vectors.sqlite3`, rebuilt incrementally from the selected vault with the installed
`embeddinggemma:300m` model. These files contain personal context and are not committed.

Response preferences live in `data/response-settings.json`. The development continuation for a native
Linux port and the 58-item improvement backlog is `docs/plans/CLAUDE-LINUX-HANDOFF.txt`.
Git excludes personal data, voices and models; the handoff documents separate migration requirements.

`data/privacy.json` stores selected text filters; `memory.json.epoch` invalidates pre-edit model context.
`data/attention.json` holds the updates being held and today's count; `data/parallel/` keeps long agent
reports whole for a parallel job's lead to read.

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
outside tools, no web search, no secrets in its environment. A question it does raise is texted to the owner (below). `.git` is read-only to the agent, so
Jarvis commits for it (with hooks off) and fetches the result into the owner's repo as `jarvis/<name>-<id>`. He never merges.

The agent saying done isn't enough. Jarvis re-runs the tests through `codex sandbox`, because the agent wrote them, and
never falls back to running them outside it. Only failures that weren't there before the agent began count: Jarvis's own
DPAPI tests always fail in the sandbox. Failures go back to the agent, for up to 4 rounds of up to 30 minutes each.

A project needs git and at least one commit to get a private copy, or it's refused. A copy is made from the last commit,
so uncommitted files aren't in it; Jarvis says so at the start and the end.

## Parallel work and its lead (2026-11-11)

`parallel_agents` splits one job into 2 to 4 parts and runs an agent on each at once (`parallel.py`). All or
nothing, one parallel job at a time, and parts that change files each need their own folder.

A big job can be given a lead (`lead="fable"`, or `"opus"`). The lead is one agent conversation, the
`Parallel Lead` session, used twice. First it plans: it reads Jarvis's draft split and the folder and returns the
split to run as JSON, with a full brief, a model and an effort for each part, or the advice not to split. Then
the parts run on the models it named. Last it gets every report with what Jarvis observed each agent do, checks
what a quick look can settle, and writes the one answer the owner hears. It only reads, and it is not running
while the parts are, so it takes no agent slot.

If the lead fails at either step the job carries on without it: Jarvis's own split runs, and Jarvis's own brain
combines the reports (`merge_turn`). If that turn fails too, the reports are read out as written.

## Fable for away work (2026-11-11)

`queue_away_job(model="fable")` runs an away job on Claude Fable 5.2 instead of Codex. The owner asked for it
to have files and tools, not web reading only. A Fable build goes through every step of the build pipeline. Fable
research is a full agent in an empty folder of its own: web, the owner's files to read, commands, files it
writes there, and a `REPORT.md` that is saved to the vault under Research.

Claude Code has no sandbox on Windows. Without one, the protection is `cc_guard.unattended`, switched on by
`JARVIS_UNATTENDED_ROOT` in the agent's environment: whatever would need a yes is refused rather than asked, the
file tools write only inside the job's folder, deleting stays inside it, the shell can't be moved out of it,
credentials files can't be read, and the environment carries no tokens and no connected services. Tested with a
real agent on 2026-11-11: an outside write, a `git push` and an outside delete were each refused. These rules
judge what the agent asks to do. A program it writes and runs is not held by them.

## The Linux sandbox for Fable away jobs (2026-11-11)

Claude Code does have a sandbox on Linux, and Windows can run a small Linux (WSL2). The owner asked for it the
same day, so a Fable away job now runs there whenever it is ready (`wsl_sandbox.py`, files in `sandbox/`, made
by `scripts/setup_wsl_sandbox.py`):

- **A distro of its own, `JarvisSandbox`** (Ubuntu 24.04). No Windows drive is mounted in it and it can't start
  Windows programs. The agent is an ordinary user with no sudo. The whole VM is capped at 4 GB (`~/.wslconfig`).
- **One folder shared in per job.** Before each run Jarvis, as root, mounts the job's folder at `/work/<name>`,
  and for research the owner's Documents at `/owner/Documents`, read-only. Nothing else of the PC is visible.
  After each run the distro is shut down, so nothing the agent started carries on and its memory is returned.
- **Claude Code's own sandbox inside**, from a settings file the agent can't change: every shell command is
  held to the job's folder and to PyPI, GitHub and npm, with no way to run one unsandboxed. `cc_guard.py` still
  runs before every tool call, because that sandbox doesn't cover Claude's file tools.
- **Nothing of Jarvis's is in there:** no tokens, no connected services, and Jarvis's own ports don't answer.

Checked for real on 2026-11-11, as the agent user: no drive visible, `sudo`, `su` and `mount` refused, a write
and a delete in the read-only share refused by Linux, a Windows program copied into the job's folder would not
start, and Jarvis's ports 7778, 7781, 7782 and 11435 were closed from inside.

Then with a real agent, started the way an away job starts one. A program it ran could write only in its own
folder: its home folder, the rules in `/opt/jarvis` and Documents were each "Read-only file system". The same
program could not read Claude's sign-in file, reach example.com ("host is not on the allow list"), reach Jarvis's
port or any address by number, and could reach PyPI. A script the agent wrote itself was held the same way. Its
Write tool outside the folder and `git push` were refused by `cc_guard.py`. A second round continued the same
conversation, and a run on Fable at high effort worked. One thing to know: `cc_guard.py` reads shell commands
for Windows paths, so on Linux it let `rm` of a file in Documents through, and it was Linux that refused it.
Inside the sandbox the guard is what holds Claude's file tools, and the operating system is what holds commands.

What it does not do. The agent can still read the web and whatever was shared in, so a job's folder and, for
research, Documents could be sent somewhere by an agent that a web page talked into it. A build of a
Windows-only project (Jarvis itself) can't run its tests inside; Jarvis's own re-run on Windows settles those.

Two steps are the owner's: installing WSL (administrator, then a restart) and signing Claude Code in inside the
sandbox, once. Until it is ready a Fable job runs under the rules above, and its first text says so and why.
`away_jobs.AwayQueue._claude_setup` decides once per job; `wsl_sandbox.problem()` re-checks the lockdown before
every job, so a sandbox someone loosened by hand is not trusted. Codex stays the default for away work.

## Fewer rules (2026-11-11)

The owner: "its annoying how much he cant do something or says we should do something because of the rules.
there should be little to no rules". His transcripts showed where it came from: 27 "May I proceed?" questions,
a long word list that made harmless requests ask, a caution after every web search, and instructions telling him
to treat his own ideas as proposals. What was decided, row by row, and where it lives:

- **What still waits for a yes: two things.** Spending money, and sending a message to other people in the
  owner's name (`approvals.ASKS`). Deleting, installing, system settings, startup and settings folders, git
  resets and pushes, encoded commands and edits anywhere now run without a question, for Jarvis's own commands
  and for every agent (`cc_guard.RISKY` holds one pattern, for commands that message people).
- **No word list.** Requests are no longer scanned for words like send, share, remove, order or token. An
  outside tool is judged by its name alone (`approvals.tool_kind`).
- **Only email makes a later change ask.** After `check_email` or `read_email` in a turn, a change needs a yes
  and away work can't be queued, because a stranger wrote that text. Web search, the clipboard and the screen
  no longer count (`truth_guard.UNTRUSTED_TOOLS`).
- **A yes can come from the phone.** Every question is spoken and texted to Telegram
  (`jarvis.text_question`); a yes or no sent from Telegram or the phone answers it
  (`jarvis.answer_from_phone`). Away from the PC the owner gets ten minutes, not two.
- **Away jobs ask instead of being refused.** An away agent that needs a yes has the question texted. It still
  keeps to its own folder. Inside the Linux sandbox a yes can't reach the guard and there is nothing to send
  from, so there it is told no and reports what is waiting.
- **His instructions.** Small ideas of his own he just does and reports; big ones he asks once. "Opening a
  session doesn't authorize work" and "find the next task means look, never do" are gone. He is told not to
  lecture or cite rules, to name a real risk once and then do the thing, never to ask whether the owner has
  permission, and to keep a doubt to a few words.
- **Agents' instructions** say the same: everything the task needs is authorized; ask only before money or a
  message to other people (`terminal.RULES`, `agent_sessions.INSTRUCTIONS`, `agent.SYSTEM`).
- **Teams is unblocked**, with Outlook. Work-safe mode is now opt-in: `JARVIS_BLOCK_WORK_APPS=teams,outlook`
  in `.env` brings it back (`worksafe.py`).
- **Jarvis can send email** (`send_email`, `gmail.send`), after the owner's yes to the exact text. It needs
  one new sign-in with the sending scope: `scripts/setup_gmail.py --renew`.

Kept on purpose: credentials files are never read into the conversation, an agent can't rewrite its own guard
or approval records, and the honesty rules (no claiming what a tool didn't do) are unchanged.

The cost, said to the owner before the change: he reads web pages, and with these questions gone a page that
tricked him could get him to delete or push something. The questions that remain cover money, messages to
other people, and anything after reading email.
