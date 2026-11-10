# Jarvis makeover: brief

You're taking over Jarvis, my personal AI assistant. The repo is `C:\Users\Lemab\Jarvis` (Windows 11, Python, about 20k lines across 45+ modules, 87 test files). I don't want it polished. I want a complete makeover. Assume nothing in it is worth keeping until you've shown it is. Then rebuild it into the best personal assistant you can make with the systems the strongest teams are using right now.

## What Jarvis is today

- **Processes:** `jarvis.py` (port 7778) is the assistant itself: wake word, ears, voice, brain, tools, and the Telegram bridge. `brain.py` (port 7781) serves the Brain page in `hud/`, a dark, graph-heavy web UI built around my Obsidian vault, with a chat panel and the Eyes, Watch, Focus and Holo modes. `desktop_orb.py` is a WebView2 orb.
- **Brain:** you can switch providers (Codex via my ChatGPT sign-in, Claude Code, local Ollama). The current choice is saved in `data/preferences.json`.
- **Voice:** local cloned voices through VoiceStudio (port 3900) and Qwen in `models\qwen-voice`, plus a wake word and interruptible speech.
- **Reach:** Telegram, my iPhone through a Tailscale bridge (port 7782), Home Assistant on a Raspberry Pi 5, Gmail (read-only), Outlook calendar, Spotify, MCP connections, and Chrome.
- **Work:** delegated agent sessions (`agent_sessions.py`, up to 4 in parallel), away jobs that keep running while I'm gone and text me progress (`away_jobs.py`), and direct shell and file tools (`direct_tools.py`).
- **Memory:** core facts, working memory, project memory, memory proposals that I approve, and semantic search over the vault.
- **Honesty:** `truth_guard.py` and device read-backs, added because Jarvis used to claim things he hadn't done.

Read `docs/PROJECT-MAP.md`, `docs/STATUS.md` and `docs/plans/` before anything else. `docs/plans/JARVIS-TARGET.txt` says to copy one YouTube demo and "do not substitute a new dashboard concept". **That rule is lifted for this work.** The demo is now one reference among many. A completely different UI is allowed if it's better.

## What's wrong (my words and past findings)

- He has said untrue things, like "TV turned on" when nothing checked the TV.
- Delegated agents felt slower than just asking Claude in a terminal. Measurements showed about 90% of agent time is the model generating and about 10% is tools, so faster plumbing alone won't fix it. I want Jarvis to be a real replacement for the terminal.
- The personality changes depending on which brain is running.
- The project has grown by adding things over time. I suspect there's dead weight, overlapping systems (several memory layers, several voice paths, two UIs), and features nobody uses.
- Long-term goal: Jarvis works on his own while I'm away and eventually helps run an automated AI business that brings in income.

## Your job, in phases

### Phase 1: Audit what exists (read-only, based on evidence)

For every subsystem, find out whether it works, whether it gets used, and whether it's as good as it can be. Don't trust docs or comments. Run things, read the logs and metrics (`data/turn_metrics.jsonl`, `performance.py`, the activity and chat history in `data/`), run the tests, and trace the code paths.

For each subsystem, give:
- **Status:** works / partly works / broken / unused, with the evidence.
- **Quality:** how it compares to the best current way of doing the same job.
- **Verdict:** keep as is / improve / replace / delete, with one line of reasoning.

Measure the things I feel directly: time from the wake word to the first spoken word, time from a typed message to the first token, how well interruptions work, how often tools fail, and how often he claims something that wasn't verified.

### Phase 2: Find out what the best are doing now

Your training data is out of date for this. Search the web and use sources from the last few months, with dates. Check:

- **Open-source and commercial personal assistants:** the most-starred "Jarvis"-style and personal-agent projects on GitHub, OpenClaw-style always-on agents and whatever has overtaken them, and the assistant products from the big labs. What can they do that Jarvis can't? What do they do better than he does?
- **Voice:** realtime speech-to-speech compared with an STT → LLM → TTS pipeline, full-duplex conversation and barge-in, turn detection, wake word, and expressive local TTS. What gets latency under one second?
- **Agents and tools:** current MCP practice, sandboxing, computer use and browser use, background agents, sub-agent orchestration, and how other projects keep agents honest (checking results, not just trusting the model's report).
- **Memory:** what's beating "facts file + vector search" now for a single user's assistant that lasts for years.
- **Proactivity and ambient computing:** presence, context, how to interrupt only when it's worth it, and phone and watch surfaces.
- **UI:** how the best assistant interfaces look and behave now (canvases, generative UI, ambient or minimal modes, mobile-first), and whether a graph-first dashboard is even the right center.
- **Local versus cloud:** which jobs my hardware should run locally (RTX GPU with about 16 GB VRAM) and which belong in the cloud.

### Phase 3: Propose the makeover, then STOP

Write `docs/plans/MAKEOVER-PLAN.md` with:

1. The audit table from Phase 1.
2. The gap list: what others do that we're missing, ranked by how much it would improve my daily use.
3. The target architecture: what the new Jarvis is, what gets cut, and what gets merged. Include a diagram.
4. The UI direction: at least two clearly different concepts, each with a mockup (HTML is fine), and your recommendation.
5. A build order in phases. Every phase leaves Jarvis working (voice, wake word, Telegram, phone and Home Assistant must not go dark), and every phase has measurable acceptance checks.
6. Costs: any paid API, subscription or hardware a choice needs, with monthly estimates.

Then stop and wait for me to approve before building.

### Phase 4: Build (after I approve)

- Work on a `makeover` branch and commit each finished step there. Don't push and don't merge to main without asking me.
- Restart Jarvis with `scripts/restart_jarvis.py` using the quiet start (a normal start speaks a briefing through my headset). Code changes only take effect after a restart.
- After each phase, re-run the Phase 1 measurements and show the before and after numbers.
- Delete what the plan says to delete. Don't leave dead code behind "just in case".

## Hard rules

- **Never claim an action happened without checking that it did.** That applies to Jarvis's behavior and to your own reports to me. If something fails, say so and include the output.
- **Money:** don't silently switch providers or add paid fallbacks. Away work must never fall back to paid API keys. Say what it costs whenever you recommend something paid.
- **Ask me first** before anything that sends, deletes, pays, publishes, or touches credentials or sign-ins. Routine installs are fine.
- **Keep my data private:** the vault, `data/`, `.env`, and the DPAPI files stay local. Never put my personal details into web searches or outside requests.
- **Don't rename my things:** this is the only Jarvis, the desktop shortcut is "Jarvis CEO", and the Obsidian vault stays where it is.
- **Be decisive:** recommend one option instead of listing ten. Keep explanations plain. I care about what changes for me, not internal jargon.

## Definition of done

Jarvis responds faster than I can get an answer by opening a terminal myself. He never claims something he didn't do. He keeps working usefully while I'm away. His UI is one I'd choose over any other assistant I've seen. The codebase is smaller and clearer than it is today, and every remaining part has a reason to exist that you can back with evidence.
