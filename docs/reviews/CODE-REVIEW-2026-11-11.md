# Code review of the whole Jarvis codebase, 2026-11-11

Done by Claude Fable 5.2 after the makeover landed on `main`. The makeover's own audit asked "does each part
work, and is it used?" from logs and metrics. This review read the code itself, looking for three things: bugs
that hide between files, dead ends, and the same job done twice.

## What was read, and how closely

- **Line by line:** the main loop and prompt (`jarvis.py`), the tool registry (`tools.py`), agents
  (`agent_sessions.py`, `terminal.py`, `agent.py`, `agent_models.py`, `parallel.py`, `cc_guard.py`,
  `approvals.py`, `direct_tools.py`), away work and research (`away_jobs.py`, `research.py`), both brains
  (`claude_code_brain.py`, `codex_brain.py`, `model_provider.py`), honesty (`truth_guard.py`), speaking up
  (`attention.py`, `heartbeat.py`, `presence_greeting.py`, `morning_wakeup.py`, `daily_review.py`), memory
  (`memory.py`, `working_memory.py`, `history.py`, `decision_log.py`, `knowledge.py`, `privacy.py`,
  `vault_log.py`), the servers (`hud.py`, `brain.py`, `phone_bridge.py`, `telegram_bridge.py`), Home Assistant,
  `self_check.py`, the small settings modules, the new page code (`hud/console.js`, `hud/cards.js`) and
  `scripts/j.py`. About 12,500 of the 19,000 lines of Python.
- **A lighter pass** (lint, a scan for unused definitions, a search for risky patterns, and the makeover's diff
  where there was one): `voice.py`, `ears.py`, `music.py`, `spotify_mcp.py`, `mcp_connections.py`,
  `mcp_oauth.py`, `semantic_search.py`, `outlook_calendar.py`, `gmail.py`, `window_control.py`, the voice
  engines, and the older page code (`hud/brain.js`, `hud/holo.js`, `hud/panels.js`). These were not changed much
  by the makeover and are in daily use. A bug in them would not have been found by this review.
- **Checks run:** 856 tests passed before any change; 917 pass now, with `data/` untouched. The linter is clean.
  The browser check of the page passes.

The code is in better shape than its size suggests. The scan for unused definitions found eight names in 19,000
lines. The problems were at the joins between features built on different days.

## Fixed in this review

Each has a test in `tests/test_code_review_2026_11_11.py` unless another file is named.

| # | What was wrong | Where | Why it mattered |
| --- | --- | --- | --- |
| 1 | **Two agents could end up changing the same folder.** A fresh task goes back to the project's folder, but the clash check looked at the folder left over from that session's previous task. | `agent_sessions.py` `start` | The one rule that stops agents overwriting each other could be passed by accident, for example a terminal task after one that ran in another folder. |
| 2 | **A failed turn's error message was treated as the answer.** When the plan limit was reached, the hourly heartbeat queued "My Claude plan's usage limit is reached" as a finding, every hour, until the day's five updates were spent. A parallel job's combined answer became that same sentence, and the agents' reports were dropped. | `jarvis.py` `respond`, `heartbeat_turn`, `merge_turn` | The moment the limit is hit is the moment you most need the real reports. `respond` now says how the turn went, and a failed merge reads the reports out as written. |
| 3 | **Held updates were cleared when a greeting was written, not when it was said.** If the "welcome back" turn then failed, they were gone, and the error sentence was saved as a past greeting. | `attention.py`, `jarvis.py` main loop | Updates held while you were out could vanish without being told. They now go back on hold if the turn fails, and after a restart mid-greeting. |
| 4 | **The model picker said Jarvis "uses API credits until it resets"** when the plan limit is reached, and still offered Ollama, the Anthropic API and the OpenAI API. | `hud/panels.js` | False, and about money. The code stops at the limit and has no API path. The picker now offers the two plans and says so. |
| 5 | **Saying "stop" at the wrong instant produced "Claude subscription conversation failed. Check that Claude Code is signed in."** | `jarvis.py` `_run_claude_code`, `_run_codex` | An interruption arriving between a sentence being received and spoken was reported as a sign-in failure. |
| 6 | **The screen agent's "read-only" scripts skipped the guard entirely,** including the rule that Teams and Outlook data are off-limits, and its scripts inherited Jarvis's tokens. | `agent.py` `_powershell` | The work-data rule had a way round it. Read-only now skips only the question, never the block, and scripts get the same token-free environment as Jarvis's own commands. |
| 7 | **Searching a credentials file by name was possible** (`search_text` with the file as the "folder"), and with ripgrep installed, matches inside `.env.local`, `.pem` and `credentials.json` would have come through. Ripgrep isn't installed today, so this had not leaked anything. | `direct_tools.py` | Now refused the way `read_file` refuses it. The rule for what counts as a credentials file lives in one place (`cc_guard.SECRET_FILE`). |
| 8 | **Agents had no billing guard.** The conversation checks that Claude Code is on the plan, not an API key. Agent runs did not, and they are where most of the usage is, more so with Fable. | `terminal.py` `_claude` | An agent run now ends before its first request if Claude Code reports an API key in use. Checked against a real run: on the plan it reports `none`. |
| 9 | **Quiet hourly heartbeats were saved as recent conversation.** With a checklist in use, twenty "(quiet)" replies would have pushed every real exchange out of the list Jarvis carries across restarts. | `memory.py` `record_turn` | Also removed two prefixes for features that no longer exist. |
| 10 | **A parallel job whose agents died without reporting blocked every later parallel job** until a restart. One cause: an agent's report was lost if writing the project log raised anything but a file error. | `parallel.py`, `agent_sessions.py` | A group nothing is working on is dropped after three minutes; the log can no longer cost the report. Tested in `tests/test_parallel.py`. |
| 11 | **"Is anything running?" could miss research and queued away jobs,** because `self_check` listed only agent sessions. | `tools.py` `self_check` | That tool is what Jarvis is told to answer from. It now lists research, away jobs and the parallel job. |
| 12 | **The long-running-agent check measured the wrong thing** (the start of the agent's latest step, not of its task). | `agent_sessions.py` now records `started_at` | The heartbeat's "still running after hours" warning could not fire for a busy agent. |

Also removed: `tools.WEB_SEARCH` and `tools._brain` (unused), `jarvis.FOLLOWUP_SECONDS` (unused), stale wording
in three docstrings and one page caption. `docs/PROJECT-MAP.md` named eleven files that no longer exist and none
of the new ones; it now matches the code. That matters more than tidiness: Jarvis is told to read his own code
and docs rather than guess how he works.

## Needs your decision

These are not bugs with one right answer. Nothing was changed.

1. **"Stop", "never mind", "cancel" and "enough" stop every running agent.** `halt_tasks` cancels the screen
   agent and all sessions. That made sense when the only background work was an agent moving your mouse. Now
   "never mind" after a wake word also cancels a 25-minute parallel job and an away build. Suggested: stop words
   stop speech and the screen agent; "stop everything" and Ctrl+Alt+J stop all agents.
2. **Agents inherit Jarvis's tokens and can read `.env`.** Jarvis's own commands can't do either. Attended
   Claude and Codex agents get the full environment (Home Assistant token, Telegram token) minus the three paid
   keys. Stripping them is one line, but an agent asked to work on a Home Assistant script may need the token.
   Unattended agents already get none.
3. **`tools.TERMINAL` is a dead end.** `terminal_task` moved to agent sessions, so the old single terminal
   worker is never started, but seven places still check whether it is running, and `terminal_status` and
   `stop_terminal_task` fall back to it. Removing it would simplify all of those.
4. **ElevenLabs is still wired in** (`elevenlabs_voice.py`, `voice.py`, `switch_voice`, `elevenlabs.bat`, the
   classic page). Its key is never loaded, so it can't run. Already on the makeover's to-do list; `audio_output`
   borrows a small helper from that file, which should move first.
5. **The classic page is still served** (`hud/index.html`, 800 lines, at port 7778 and `/classic`). The plan said
   delete it and keep the event stream.
6. **The end-of-turn model now saves 0.2 seconds at most.** After your "wait a full second" decision it is only
   asked at 1.0 s, and the timer ends the phrase at 1.2 s anyway. It loads a model and runs it on the microphone
   thread for that. Either drop it, or keep it for the day you try a shorter pause.

## Smaller things, left alone

- **The same "write a JSON file safely" code exists nine times** (`agent_sessions`, `away_jobs`, `preferences`,
  `attention`, `research`, `presence_greeting`, `morning_wakeup`, `decision_log`, `conversation_settings`). Some
  retry when Windows has the file open and some don't. `research.py`'s can fail if the working-memory brief
  reads the file at the same instant. One shared helper would fix that and remove about 80 lines.
- `Brain.ask` marks the brain busy before the block that always clears it. A failure in the four lines between
  would leave every later turn refused as "already running". Nothing there fails today.
- `scripts/benchmark_models.py` still documents `--allow-paid` for API models. The brain refuses them, so it
  can't spend anything; the option is just stale.
- `model_provider.SUBSCRIPTION_PROVIDERS` and the `credential: "n/a"` field are leftovers from the API days.
- `outlook_calendar.SHORT_DATE` is unused.
- A parallel job stopped mid-run still gets a merge turn that reports the parts as stopped. Harmless.

## What this review could not tell you

- Whether the voice and hearing code is right. It was only skimmed, and it needs your ear, not a reader.
- Whether the page's older JavaScript has bugs. The browser check passes, which covers its main paths only.
- How any of this behaves under a real plan limit. Fixes 2, 3 and 8 are tested with a simulated one.
