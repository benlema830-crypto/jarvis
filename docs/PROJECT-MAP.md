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
| Conversation brains | claude_code_brain.py (Claude on the owner's Claude plan, the default), codex_brain.py (Codex on the ChatGPT plan), local_brain.py (a local model on this PC through Jarvis's own Ollama, added 2026-11-11: free and offline, the everyday tools only, much weaker), model_provider.py (which one talks). The only paid path is openai_api.py, below |
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
| Desk lights and screens | pc_lights.py (`pc_lights` tool: the keyboard, case and graphics card lights through OpenRGB, the monitor backlights through Home Assistant, and the screens' power; off for sleeping while work carries on), scripts/rgb_flow.py (the colour flow it stops and starts), screen_sync.py (`screen_sync`: the backlights following the screens) |
| Sleep and stale requests | suspend_watch.py (notices the PC was asleep; a turn that slept five minutes or more is not spoken and its actions are refused, tools.stale_request) |
| Proactive | reminders.py, nudges.py, activity.py, daily_review.py (Briefs/ in the vault, once a day on Codex), heartbeat.py (half-hourly plain checks and the owner's checklist), attention.py (say it now or hold it; five unprompted updates a day), presence_greeting.py, morning_wakeup.py |
| Research | research.py (start_research: background Codex web research -> Research/ in the vault) |
| Watching videos | video_watch.py (`watch_video` tool: timed still frames plus captions of a YouTube link or a video file, shown to the brain as pictures), vendor/claude-video (the skill's scripts, unchanged) |
| Creator watch | creator_watch.py (Zubair Trabzada's YouTube feed and GitHub every 6 hours; new Jarvis videos written up by Codex -> Research/Zubair watch/ in the vault; `creator_watch` tool) |
| Workshop | workshop_refs.py (photographs of the real thing, looked up by Codex), workshop.py (`workshop` tool: Fable writes a 3D scene in steps; changes, pull-apart, undo, render), hud/workshop.js (the bench around the stage), hud/workshop-frame.html (the sandboxed three.js stage), hud/vendor/three.module.js, brain.py `/workshop/*` (picture, snapshot, files), hud.py `/workshop` (state) |
| Screen pointer | screen_pointer.py (`point_at_screen`: a click-through ring and label over a control) |
| Meeting prep | meeting_prep.py (`meeting_prep` tool, and a brief half an hour before an event when the vault, facts or tasks hold something on it -> Briefs/Meetings/ in the vault) |
| Reply language | reply_language.py (`reply_language` tool; a line in the brain's instructions and the language given to the voice; preferences `reply_language`) |
| Teardowns | teardown.py (`reverse_engineer` tool: an agent session with the REA toolkit -> Research/Teardowns/ in the vault), scripts/setup_rea.py (installs REA in vendor/rea and connects it for data/teardowns only) |
| Email | gmail.py (Gmail API: reads, and sends after the owner's yes; DPAPI tokens in data/gmail.enc), scripts/setup_gmail.py, docs/GMAIL.md |
| Memory and continuity | memory.py (core facts, history on update), working_memory.py (where things stand, every turn; project briefs for agents; data/project_log.jsonl), decision_log.py (the journal's decisions go to Decisions/Decision log.md; no approval queue), history.py (search past conversations; the readable copy of memory in the vault) |
| Performance | performance.py (data/turn_metrics.jsonl, scorecard), task_effort.py, scripts/benchmark_models.py |
| MCP armory | mcp_connections.py (encrypted store and tool transport), mcp_oauth.py (browser authorization and token lifecycle) |
| Where the owner is | whereabouts.py (out of the room: the phone is away from home, or the bedroom sensor and the PC have both been quiet for 30 minutes; decides whether Jarvis texts or speaks) |
| Paid fallback | openai_api.py (the OpenAI API on the owner's key: the conversation when the ChatGPT plan is at its limit, and one command at a time on request) |
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

## Texts, updates and the paid fallback (2026-11-11, later)

Three more decisions from the owner the same day.

**Texts only when they are out of their room** ("i only want jarvis to respond over text if im not in my room aka
phone location and or bedroom sensor for more then 30 minutes, or i text him myself"). `whereabouts.out_of_room()`
is true when the phone is away from home, or when the bedroom sensor has been clear for thirty minutes and the PC
untouched for as long (the desk is in the sensor's blind spot). It gates the texts Jarvis starts himself: an
approval question (`jarvis.text_question`) and an away job's texts (`away_jobs._wanted_by_text`). A message they
sent is always answered where it came from, and so is a job they queued by text. In the room they hear it
instead; the spoken summary of away work no longer says "I've texted you" unless he did.

**No daily limit on updates, but only what matters.** `attention.DAILY_CAP` is `None`. Before an update is said
or texted, Jarvis makes the short version himself (`jarvis.brief_update`): the outcome in a sentence or two and
anything that needs the owner, or nothing at all when he judges they don't need it. Short reports and things he
wrote himself go as they are. If that turn fails, the first sentences are said as before. Someone in the room
but away from the keyboard now hears an update (`whereabouts.can_hear`), except at night.

**The OpenAI key as a fallback.** When Codex reports `usageLimitExceeded`, the conversation carries on through
`openai_api.Conversation`, on the key in `data/openai-key.dpapi`. He says so once, stays there for fifteen
minutes at a time, and goes back when the plan answers. Any other Codex failure spends nothing. `run_command` can
be given the key for one command (`with_openai_key`) when the owner asks for something the API alone can do; the
key is cut out of the output. Not proven with a real request: on 2026-11-11 the key was valid but OpenAI
reported its credit exhausted, and he says exactly that when it happens.

## Creator watch (2026-11-11)

The owner wants Jarvis to keep up with what Zubair Trabzada (the YouTuber whose Jarvis ours follows) adds to his.
`creator_watch.py` checks his channel's public feed and his GitHub repos every 6 hours (`preferences
"creator_watch": {"enabled", "hours"}`), with no AI and no cost. The first look only records what exists. A new video
about Jarvis gets its transcript (`youtube-transcript-api`) and 30 still frames (`video_watch.py`, below) written up by Codex: what's new, how he built it, what we
have, what's worth adding. That goes in `Research/Zubair watch/` and is announced through attention.py. If captions aren't up yet
it tries again for two days. Other videos and repo changes go in one plain "updates" note. Links to his paid community are
dropped. The write-ups are proposals; nothing is built from them unless the owner asks. State: `data/creator_watch.json`.
The first build brief from it: `docs/plans/ZUBAIR-FABLE-5.2-WORKSHOP.md`.

## Watching videos (2026-11-11)

The owner asked for the "watch" skill from github.com/bradautomates/claude-video inside Jarvis. Its scripts are
vendored unchanged in `vendor/claude-video` (MIT, commit in ORIGIN.txt) and `video_watch.py` runs them as a separate
process: yt-dlp fetches the video and captions, ffmpeg picks frames at scene changes. The `watch_video` tool hands
the brain up to 40 stills, each stamped with its time, plus the captions, the same way `look_at_screen` hands it
a screenshot, so Codex or Claude sees them itself. It is stills and captions, never motion or sound.

- Nothing is uploaded: always the skill's local engine with no speech fallback, and keys are kept out of its process.
  A video with no captions comes back as frames only.
- `start`/`end` give a part of the video with denser frames. `timestamps` gives just those moments at 1024 px
  wide, sharp enough to read small on-screen text (the usual 512 px is not).
- Added to the skill, each from a real run: English captions asked for by name (it chose Bangla on an auto-dubbed
  video); a quarter of the frames kept back to fill the widest gaps (scene changes left a five-minute hole in a
  slow screen recording); `youtube-transcript-api` when YouTube refuses yt-dlp the captions.
- The video is downloaded into `data/video_watch/` and deleted as soon as the frames are read. One video at a time.
- Measured on this PC: 17-minute video, 40 frames, about 25 seconds; exact moments about 17 seconds.
- Needs yt-dlp, ffmpeg and Deno on the PATH (`winget install yt-dlp.yt-dlp Gyan.FFmpeg DenoLand.Deno`). yt-dlp must be
  kept current (`winget upgrade yt-dlp.yt-dlp`): YouTube breaks old versions.
- YouTube limits caption requests per address. After about a dozen in a row both caption sources are refused for
  some hours; frames still work and the tool says the captions are missing.
- The creator watch gives Codex 30 frames with each new Jarvis video's transcript (`vault_log.codex_once(images=)`).

## The workshop, and what else came from Zubair's videos (2026-11-11)

Built from `docs/plans/ZUBAIR-FABLE-5.2-WORKSHOP.md` (five items) and `docs/plans/ZUBAIR-GAPS.md` (gaps 1-5).

**Workshop** (`workshop.py`, third main view on the Jarvis page). "Build yourself a body", a picture dropped, pasted
or chosen on the bench, or "build what's on my screen" goes to Claude Fable 5.2 through Claude Code on the Claude
plan (never an API key; `preferences "workshop": {"model", "effort", "edit_effort"}`). Fable answers with a script:
`TITLE`, a `SETUP` block of shared helpers, named `STEP` blocks and a `SPOKEN` line. Each step is sent to the page as
soon as the next one starts, so the object appears piece by piece. The code runs in `hud/workshop-frame.html`, a frame
sandboxed without same-origin access: it can't reach the Jarvis page, its storage or its requests, and brain.py refuses
its origin for everything except the three.js file. Scene code gets `THREE` and `api.part(name, description, object,
explode)`, `api.add`, `api.onTick`. A step that throws is reported back and sent to Fable once for repair.
- A change sends the script back and gets only the changed steps (`=== STEP` to replace or add, `=== REMOVE`,
  `=== NOTE` for the list on screen). Earlier versions are kept for `undo` (12).
- "Pull it apart" moves each part by its `explode` offset and labels it. The part list goes into the note Jarvis
  keeps of the build, so he can answer "what is the main logic board?".
- "Render it" asks the page for a picture of the 3D view as the owner has it turned, and has Codex's image generation
  (ChatGPT plan, `codex exec --image`) make a realistic picture from it, about a minute. Only when asked.
- The page tells Jarvis every few seconds that it is there and whether the workshop is the view on screen
  (`workshop.on_screen`). When none is, he opens the Jarvis page on the workshop, and if it still isn't showing his
  tool result says NOT CONFIRMED so he tells the owner instead of claiming it is up. Added after 2026-11-11, when a
  page left open from before the workshop existed showed nothing and he said the model was on screen.
- An open page reloads itself when the files it is made of change (`/ui-version`, checked every 30 s and when
  Jarvis comes back), unless something is typed in the prompt.
- Parts can be picked: a click on the model, the PARTS list, or `workshop(action="focus")` by voice (names are
  matched loosely, since speech recognition hears "bass tube" for "base tub"). Picked parts stay as they are and
  the rest turn faint, or vanish with "only". The page tells Jarvis what is picked, so "make this one red" changes
  that part. Focus changes the view, never the model.
- Real things are built as they are: the builder is told never to invent internals a product doesn't have, and
  `api.print` gives it a canvas to draw lettering and labels on. Before that a tin came out as embossed shapes,
  and a render of it, dragged onto the bench by accident, was rebuilt as a gadget with a made-up circuit board.
  Dragging something already on the page no longer counts as putting a picture on the bench.
- **Accuracy and detail** (added after an iPhone came out as an empty shell). Three things happen around a build:
  a photo scout (`workshop_refs.py`: Codex with web search on the ChatGPT plan, about two minutes, in the
  background) saves up to four photographs of the real thing in `refs/`; the builder is told to build the parts a
  thing really has, inside and out, and never ones it doesn't; and after the build a check pass shows Fable four
  views of its own model on one sheet plus the photographs and has it correct, complete and detail the model
  (`_check`, the patch format). Jarvis speaks once, at the end. `api.photo(n, [x, y, w, h])` puts a region of a
  photograph on a face, so a real label is the real label. "Add more detail" runs the same pass on request, on the
  selected parts if any (`detail`). `preferences "workshop": {"check": false, "references": false}` switch them off.
  A real product now takes three to six minutes.
- **Building from the screen** sends one capture per monitor (both monitors in one picture left the product about
  100 pixels tall, and the wrong one was built). The photo scout is shown the same captures, so it starts from the
  page the owner has open. A change can refer to the screen too (`edit` with `picture="screen"`), and every
  change is shown the owner's picture and the photographs. A change asked for while the bench is busy is queued
  and made when the job ends, where it used to be refused and forgotten.
- **Moving parts**: `api.motion(name, fn)` in the scene code; `move` plays or resets one by voice, and asks the
  builder to add it when the model can't do it yet. They are listed under MOVES in the parts panel.
- **Measuring**: `measure` shows a box with the real width, height and depth (metric and inches), something
  familiar beside the model for scale (a quarter, a bank card, a drinks can or a person, by size), and a ruler
  between two clicked points. The page reports the sizes to Jarvis so he can say them. They are the model's
  sizes, only as right as the model.
- **Cut-away**: `cut` slices the model on one axis with a slider (clipping planes on the parts' materials).
- **Variants**: `variants` asks for two to four versions as patches and stands them side by side; `choose` (or a
  click) keeps one, with undo.
- **Files**: `export` saves an STL (millimetres, Z up, for a slicer or Fusion's Insert Mesh) or a GLB with colours;
  `video` records one turn of the model (MediaRecorder in the page, converted to MP4 with ffmpeg) and can text it.
  Both land in `Documents\Jarvis Workshop`. The page makes them and uploads them through brain.py `/workshop/upload`.
- **Hands**: with HOLO on, the gestures that turn the graph turn the model instead while the workshop is up
  (`hud/workshop.js` wraps `J.camera`): pinch and move to turn, quick pinch to pick a part, two hands apart to
  zoom and, past a point, pull it apart. Not tried with real hands yet.
- Scenes live in `data/workshop/<id>/` (script, picture, renders); `bench.json` remembers which one is on the bench
  across a restart.
- Measured: a product build about 90-120 s at low effort (half of it thinking), a change about 20 s, a floor plan
  about 3.5 minutes, a render about a minute.

**Fable as the talking brain**: `claude-fable-5-2` is in `claude_code_brain.MODELS`; "switch your brain to Fable".
Measured 2026-11-11 on short questions with a short prompt and no tools (three runs each): first words after 0.4 s
against 0.5 s for Opus. Not measured with Jarvis's full prompt and tools.

**Screen agent** (`agent.py`): each `computer` call carries a `saying` line, spoken through `Agent.on_narrate` only into
silence and only when the owner spoke in the last ten minutes or the room sensor shows someone; otherwise it is shown
in the Console. A watcher thread ends the task when the pointer moves more than 30 px, a button is clicked or a key is
down between the agent's own actions ("you took over the mouse"). `preferences "agent_narration"` and
`"agent_takeover"` (both true unless set to false).

**Pointer** (`screen_pointer.py`): `look_at_screen` records how its picture maps onto the desktop; `point_at_screen`
turns a point in that picture into a real one and draws a ring and label there for a few seconds in a layered,
click-through, never-focused window.

**Telegram files**: `send_telegram(text, file)`; pictures up to 10 MB as photos, anything up to 50 MB as a document,
only ever to the paired chat, never a credentials file.

**Meeting prep** (`meeting_prep.py`): no AI call unless a vault note, saved fact or open task names the event's own
words. Codex writes the brief; it never guesses attendees or agenda.

**Reply language** (`reply_language.py`): the owner keeps speaking English. Checked with the VoiceStudio voice by
transcribing its speech back: Spanish, German, French and Hindi. The wording-based honesty checks (`truth_guard`
claim gate) only read English, so they don't fire in another language; receipts still do.

**Teardowns** (`teardown.py`): REA 6.8.0 (228 tools) is a local stdio MCP server. It is registered with Claude Code at
local scope for `data/teardowns`, so only an agent session started in that folder loads it. Jarvis's own MCP client
is HTTP only and doesn't see it. `scripts/setup_rea.py --remove` disconnects it.


**Blueprints** (`blueprint.py`, `fusion_link.py`, tool `blueprint`; added 2026-11-12): for real things the owner will
build or fit, where the workshop is for looking. One `spec.json` per project (`data/blueprints/<id>/`, mm, Z up,
origin at the centre of the footprint) is the single source of truth; every part is one physical piece with shape
(box, cylinder, tube, sphere, cone, or none for hardware), position, rotation, holes, material, make/buy, product,
cost, mass, volts/watts, where its sizes came from and how sure. Fable reads the photos into it (`SYSTEM_READ`:
scale from things of known size, and four to ten lettered measurements drawn on the photos); "A is 24 1/2 in"
records the real number and Fable reworks the spec around it; `upgrade` designs a change (new parts with datasheet
sizes, brackets to make, wiring, power, software, steps, risks). Each round: Fusion builds it through its own MCP
(`fusion_link.run_script`, port 27182; a direct-modelling design, a component per part inside a component per
group, NEW/CHANGE prefixes and colours, four pictures, STEP and .f3d; it rebuilds into the same never-saved design
and never touches one the owner saved), then a check pass sends Fusion's pictures back to Fable beside the photos,
the bench preview is made from the spec with no model call, and the packet goes to `Documents\Jarvis Blueprints\
<name>\` (build-packet HTML + PDF through headless Chrome, parts list CSV + XLSX, measuring photos, spec, STEP).
`checks()` finds clashes, floating parts, estimates, power headroom (30 %), weight and cost without a model call.
Fusion built a 10-part test machine in 3-5 s.

Motion (2026-11-13): the spec has `joints` (revolute or slider; the parts that move together, the part it is `on`,
an axis through a real axle or pin, min/max from the pose modelled, the motor that drives it). A joint on a part of
another joint rides on it. In Fusion each joint is a top-level "Moves - <name>" component with an "Axis" sketch line;
after the bodies are made the design switches to parametric (as-built joints need history; a rebuild switches it
back to direct first), the fixed groups are grounded in a rigid group, and each joint is an as-built joint made
with `JointGeometry.createByCurve` on that line and `ZAxisJointDirection` (`createByPoint` with a custom direction
turned about the wrong axis). The script then plays every joint through its range for 48 frames, framed on the
whole sweep, and `_gif` makes `motion.gif` for the packet. `motion_checks()` sweeps each joint on its own and finds
the first place a moving part's box runs into another (separating-axis test; a wheel spinning on its own axle is
skipped).

## Fixes from reading real conversations (2026-11-13)

Three days of transcripts (11-11 to 11-13) were read for what went wrong, and each fix has a test in
`tests/test_improvements_2026_11_13.py`.

- **A request that slept is dropped.** "Pause everything, I'm going to bed" was still waiting on the local model
  when the PC slept. Six hours later the turn finished, spoke to a sleeping room and put the PC back to sleep five
  minutes before the alarm. `suspend_watch` sees the clock jump; `Brain.ask` then says nothing and `run_tool`
  refuses every tool except look-ups. A Telegram conversation still gets its late answer.
- **Sleep tells the truth.** `sleep_computer` lists the work it will pause (`tools.running_work`).
- **Lights out without sleeping** is `pc_lights`.
- **Side conversations.** In continuous listening, words with no "Jarvis" in them reach the brain ending in
  `[no name said]` (`jarvis.Overheard`, `heard_as`). The prompt lets it answer `(quiet)` when they were plainly for
  someone else, and the main loop then says nothing. Tried on thirteen real lines: Claude Opus and Codex Terra 13
  right each, the local model 11 (it went quiet on "pull it apart"), so the local brain is not given the note.
- **Fillers.** "Um...", "wait" or "hold on" said over him stops him and listens; said into silence it is ignored
  (`jarvis.is_filler`). They used to be sent to the brain as requests.
- **"Good night" and "go to sleep" are speech, not exit.** They used to end the program, and with it the alarm.
  "Shut down", "power down", "exit", "quit" and "goodbye" still do.
- **Advice** has its own paragraph in the prompt: the pick first, the reasons that decide it, built on what he
  knows about the owner, in a few spoken sentences.
- **Weather** gives feels-like, wind, snow or rain, and a plain word for cold ("below freezing"), after a morning
  briefing suggested a light jacket at 21 degrees.
- **Sentences.** No split after "Mr." or an initial; text either side of a tool call is separated on every brain,
  which also means the sentence before a tool is spoken before the tool runs.
- **The page.** Home tiles show a light group once, without WLED's option switches or the bulbs of an unreachable
  group (`home_assistant.tiles`); the workshop's start card sits in the middle of the stage.
- **Logs.** A calendar outage is one line; creator watch uses the uploads playlist when the channel feed is 404.
