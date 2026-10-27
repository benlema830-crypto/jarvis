# Foundation hardening — 2026-10-22

Implementation of `docs/plans/JARVIS_CODEX_TERMINAL_HANDOFF_2026-10-22.md` (phases A–D), built on branch
`foundation-hardening` on top of `b873a2b`, **fast-forwarded into `main` and live Jarvis restarted on 2026-10-22**
(both approved by the owner). After the restart: startup ready, mic receiving, voice lock on, Codex active,
and the live HUD rejects foreign origins (403). No live data was migrated or rewritten; the real Obsidian
vault was never opened. Measurements use the synthetic fixture in `tests/retrieval_fixture.py`.

## What changed

| Commit | Phase | Behaviour change |
|---|---|---|
| `30d7b65` | A1–A3 | Harmless `remember()` no longer wipes the conversation; forget/correct/scrub/privacy changes still do. The turn in which a forget happens is saved only as a placeholder. Full memory refuses instead of evicting. Prompt memory is budgeted (4,000 chars); `recall_memory` searches every fact. |
| `50efd63` | B1, C3 | Vault search = keyword + embeddings merged by reciprocal rank fusion, exact-ID boost, `status: superseded` demotion, keyword-only fallback. Word-level BM25 replaces substring counting. Credentials redacted in `search_knowledge` output. 27-question benchmark. |
| `bffd60a` | B2 | Scan cache (mtime+size), in-memory numpy vectors, stale-vector purge, 4 s embedding budget per query with background backfill, corrupt cache set aside and rebuilt. |
| `7be4e02` | B3 | `JARVIS_EMBED_KEEP_ALIVE` (default `2m`, measured), reused loopback HTTP session. |
| `280b8cd` | C1 | `correct_memory` replaces a fact in place (no superseded archive). `forget`/`correct` refuse ambiguous matches. |
| `2ba681a` | C2 | `update_knowledge_note`: section/frontmatter edits of existing notes, sha256-checked, diff preview, spoken approval. `create()` unchanged. |
| `a749857` | C3 | Benchmark floors enforced in the unit suite. |
| `40cf195` | D | Approval-gated tools ask *after* the turn (fixes a deadlock in `named_routine run`). |
| `5658929` | D | HUD server rejects foreign `Origin` headers. |
| `29ac40f` | D | Encoded/string-built commands and script-language deletes need approval. |
| `8bd111c` | D | Agents cannot write approval records or guard code; file writes limited to allowed roots. |

### New or changed model tools
- `remember(fact, core=False)` — `core` keeps identity facts in every prompt.
- `recall_memory(query)` — read-only lexical lookup over all saved facts.
- `correct_memory(old, new)` — replaces an outdated fact; old wording removed everywhere.
- `update_knowledge_note(path, action, target, content, expected_sha256)` — needs the user's spoken yes.
- `read_knowledge_note` now returns `sha256`; `search_knowledge` results may carry `modified` and `status`.

### Memory record format (backward compatible)
Legacy `{fact, t}` records load unchanged. New optional fields: `core: true`, `updated: <epoch>`.
No migration was run or is needed.

## Measurements (same PC, same fixture)

Vault search, 27 questions (24 answerable):

| | recall@1 | MRR | credential leaks | deleted-note hits | p50 / p95 per query |
|---|---|---|---|---|---|
| Original, keyword (Ollama off) | 0.792 | 0.882 | 3 | 0 | 19.8 / 23.9 ms |
| Now, keyword (Ollama off) | **0.917** | **0.938** | **0** | 0 | 1.5 / 1.7 ms |
| Original, semantic (Ollama on) | 0.958 | 0.979 | 5 | 0 | 1,741 / 5,323 ms |
| Now, hybrid (Ollama on) | **1.000** | **1.000** | **0** | 0 | **22.8 / 39.5 ms** |

Cold/warm matrix with Ollama on (model forced out of memory and verified unloaded before each "model cold"
measurement; `scripts/memory_benchmark.py`, same fixture, same harness run against `b873a2b` and this branch):

| | Original | Now |
|---|---|---|
| Index cold + model cold (first search) | 3,736 ms | 2,024 ms |
| Index warm + model cold (median of 3) | 1,598 ms | 1,508 ms |
| Index warm + model warm, p50 / p95 | 1,699 / 1,748 ms | 22 / 38 ms |
| Repeat query, p50 / p95 | 1,707 / 1,744 ms | 21 / 23 ms |

The original never reaches "model warm": `keep_alive: 0` reloads the model on every query. A model cold
start (~1.5 s) remains unavoidable; it now happens only after two idle minutes. An earlier 37.8 s first
search was the first model load after boot with an empty disk cache, so it is not comparable.

Overhead at 1,000 synthetic notes (fake embedder, isolates Jarvis's own cost): p50 1,231 ms → 41 ms
(scan 730 → 28 ms, similarity 338 → 3 ms, keyword 117 → 5 ms). `knowledge.index()` for the Brain graph: 729 → 44 ms.

Embedding keep-alive: unload-after-each-request costs ~1,684 ms per embed; warm embeds take ~6 ms; the
loaded model holds 654 MiB VRAM (GPU had ~6.8 GB free with Qwen loaded).

Memory with 200 facts: injected prompt 24,406 → 4,120 chars; oldest fact kept (was silently evicted);
fact recall 7/7 including corrected and deleted cases; 0 false memories.

Caveats: the fixture is small and was used while tuning stop words, stemming and tie-breaking, so the
1.0 hybrid score overstates real-vault quality. Offline recall@5 fell from 1.0 to 0.958: the old code
found "who advises us on engines" only through a substring accident. Time to first spoken response
and Qwen speech latency were not measured.

## Security review (phase D)

Verified and fixed:
1. **Approval deadlock.** `named_routine run` waited for approval inside the model turn on the main
   loop, which is also the loop that speaks the question and routes the answer, so it always timed
   out to "no". It now uses the same post-turn pattern as `call_mcp_tool`.
2. **HUD Origin.** `POST /command` (which can answer approvals) accepted any `Origin`. Browsers were
   already stopped by the JSON-only rule, but the server now refuses foreign origins like `brain.py` does.
3. **Guard bypasses.** `-EncodedCommand`, `iex`, base64 payloads and `os.remove`/`shutil.rmtree`/`fs.rmSync`
   were treated as ordinary work and could be auto-accepted for Codex sessions.

4. **Self-approval and allowed roots** (`8bd111c`). A Claude Code terminal task could write
   `data/cc_approvals.json` (the grant file the guard trusts), edit `cc_guard.py`, or write `C:\Windows`,
   the Startup folder, `.ssh`, `.codex`/`.claude` config or PowerShell profiles with no pause. Writes to
   Jarvis's approval records and guard code are now blocked; file writes outside your user folder, or into
   autostart/credential/agent-config places inside it, need spoken approval (paths resolved first; an
   unreadable drive fails closed). Codex file-change auto-approval applies the same rules. Codex shell
   commands are confined by its sandbox (writable root = the project folder, no network); Claude Code shell
   commands still rely on the keyword guard (that path is unused in subscription-only mode).

Pre-existing usability note: in research mode Codex wraps even read-only searches in a compound PowerShell
command, which isn't recognised as read-only, so those requests come to you for approval.

Approval channels (documented, unchanged): owner voice, the local console (`--text`), and the local
HUD/Brain text box. Model output, tool/MCP results, Telegram, HOLO, reminders and agent reports
arrive as dict items and never reach `approvals.answer()`.

Proposed as a separate change, then **approved by you and merged** (`a8b8777`):
- **Native Codex MCP/app tools.** Verified live: every Codex process Jarvis starts (the conversational
  brain and both session modes) sees `Roblox_Studio` (28 tools, `execute_luau` auto-approved) and the built-in
  `codex_apps` (104 tools incl. site deploy/delete, app uninstall, parental controls), outside Jarvis's
  approvals. Change `a66d3ec` (write-up: `docs/PROPOSAL-CODEX-MCP-LEAST-PRIVILEGE.md`): conversation and
  research get no native MCP/app tools (verified live after merging: 0 visible), work sessions keep your setup.
  The live 5-turn Codex conversation passes with isolation on. Roll back with `git revert -m 1 a8b8777`.
- **Keyword guard limits.** `cc_guard` cannot see intent (e.g. `Set-Content` emptying a file, uploads
  via `Invoke-WebRequest -Method Post`). For Codex sessions the real boundary is the platform sandbox
  (workspace-write to the project folder, no network). **Verified 2026-10-26** with a harmless probe
  run through `codex sandbox` (codex-cli 0.163.0, `[windows] sandbox = "elevated"`): under `:workspace`,
  writes succeeded only in the project folder and %TEMP%; a sibling folder, Jarvis's `data` and Documents
  were blocked, and so was the network. Under `:read-only` every write and the network were blocked.
  Reads outside the project are allowed in both, by design. The user's own `~/.codex/config.toml`
  defaults to `danger-full-access`; Jarvis requests its sandbox explicitly per thread and turn, which
  should override that default. The probe did not drive a full Jarvis agent turn through the app-server.
- **Local processes.** Any program running as you can POST `/command` (including "yes"). This is the
  accepted local-trust model; a per-launch token would close it but touches every HUD client.
- `agent_sessions` one-job-at-a-time guard is untouched, as required.

## Handoff section 7 checklist

- [x] **No silent loss of facts beyond 200.** `tests/test_memory_capacity.py`; benchmark: 200 stored, overflow
  refused, oldest kept (the original code evicted it).
- [x] **A harmless fact doesn't erase working context.** `tests/test_memory_continuity.py`; live Codex: "Kestrel"
  recalled after a `remember`, 4 messages kept.
- [x] **Forget/correct removes stale context from prompts, history and cache.** Continuity, correction and
  privacy tests (including the forget turn itself and restart); live Codex: context cleared after `forget`.
- [x] **Active prompt memory is bounded; other facts retrievable.** 24,406 → 4,120 chars at 200 facts;
  `recall_memory` finds non-injected facts (tests and live).
- [x] **Exact and semantic vault questions both work online, with offline fallback.** recall@1 1.0 hybrid,
  0.917 keyword-only (was 0.958 / 0.792); live Codex search answered in both modes.
- [x] **Edited/deleted notes never appear as stale results.** 0 deleted hits and 0 stale excerpts in every
  run; vector purge tests.
- [x] **Path security and create-only semantics intact; the edit API is version-checked.**
  `tests/test_knowledge.py` unchanged and passing; `tests/test_knowledge_edit.py`, `tests/test_approval_flow.py`.
- [x] **Synthetic benchmark runs with before/after results.** `scripts/memory_benchmark.py`, reports in
  `data/reports/`, floors enforced by `tests/test_retrieval_benchmark.py`.
- [x] **No voice/model/MCP/agent-session regressions in the tested paths.** 365 unit tests, plus live checks:
  Codex conversation, Qwen→Whisper, wake word, MCP list/call and both MCP sign-ins (Zapier 17 tools, GitHub 46),
  a Codex research session, the Claude Code terminal guard, and a restarted Jarvis reporting mic receiving and
  output active. **Still pending with you:** saying "Jarvis, what time is it?" to hear the full mic→speaker loop.
- [x] **An honest report lists changes, tests and remaining risks.** This document.

## Allowed roots and tools per agent (review result)

| Who | Files it can write | Network | Shell | Native Codex MCP/apps | Approval route |
|---|---|---|---|---|---|
| Conversational brain (Codex) | none (read-only sandbox) | Codex web search only | disabled | none (isolated) | Jarvis tools; MCP via `call_mcp_tool` asks every time |
| Research session (Codex) | none (read-only sandbox) | none | read-only commands; anything else asks you | none (isolated) | `agent_sessions._approval` → spoken approval |
| Work session (Codex) | project folder only (`writableRoots`) | none | sandboxed to the project; guard-flagged commands ask | your Codex config (Roblox Studio) | same, plus guard rules for file changes |
| Terminal task (Claude Code; unused in subscription-only mode) | user folder, minus autostart/credential/agent config (ask); Jarvis approval/guard files blocked | unrestricted | keyword guard only | n/a | `cc_guard` hook → spoken approval, 15-minute grants |
| Jarvis MCP (`call_mcp_tool`) | n/a | the connected server | n/a | n/a | spoken approval per call |

Remaining gap: Claude Code shell commands have no platform sandbox, so the keyword guard is their only check.
That path is off in subscription-only mode; give it an OS sandbox before ever enabling it for unattended work.

## Remaining work

**Next safe milestone (foundation):**
1. Owner check: say "Jarvis, what time is it?" to confirm the mic→speaker loop after the restart.
2. Start the local embedding server with Jarvis (today it needs `start-local-model.bat`, otherwise search runs keyword-only).
3. Research-mode usability: Codex wraps read-only searches in compound PowerShell commands, so they come to you
   for approval. Recognise safe read-only command shapes instead.
4. Optional per-tool Roblox Studio policy for work sessions (`execute_luau` still runs without asking there).
5. A larger, realistic benchmark (anonymised copies of real note shapes) to replace the small tuned fixture.
6. Telegram pairing when you want it (`scripts/setup_telegram.py`); the bridge works against a simulated Bot API, but only you can create the bot.
7. A per-launch token for `/command` if other local programs should not be able to answer approvals.

**Later, optional AI-CEO features (deliberately not started):** durable task queue with IDs, cancellation and
budgets; per-job workspace isolation; worker limits; parallel Codex/Claude workers; a sandbox for Claude Code
shell commands; role-specific tool allow-lists. The one-job-at-a-time guard in `agent_sessions` stays until those exist.

## Open by owner decision (2026-10-22)
The owner chose to defer these; they need a person, a device or an account only the owner controls:
- Hearing the mic→speaker loop ("Jarvis, what time is it?"). Automated: restarted Jarvis reports mic receiving and
  output active; synthetic wake-word and Qwen→Whisper round trips pass.
- Starting HOLO (turns on the webcam). Code unchanged; unit tests pass.
- Pairing a real Telegram bot. The bridge passes a full simulated exchange.
- Paid Claude/OpenAI paths: not called, by the owner's subscription-only rule.
- Claude Code shell sandbox: Claude Code's OS sandbox is not available on native Windows; the path stays off in
  subscription-only mode and is guarded by the hook (live-tested) until a sandboxed runner exists.

## Tests per milestone
Command: `.venv\Scripts\python.exe -m unittest discover -s tests` (no failures or skips at any milestone; one
junction test skips only where neither a symlink nor a junction can be created).

| Milestone | Commit | Tests run | Result |
|---|---|---|---|
| Baseline (before any change) | `b873a2b` | 266 | all passed |
| A1–A3 memory continuity, capacity, prompt budget | `30d7b65` | 289 | all passed |
| B1 hybrid search + benchmark | `50efd63` | 301 | all passed |
| B2 incremental index | `bffd60a` | 311 | all passed |
| B3 keep-alive | `7be4e02` | 314 | all passed |
| C1 corrections | `280b8cd` | 323 | all passed |
| C2 note edits | `2ba681a` | 337 | all passed |
| C3 benchmark floors | `a749857` | 340 | all passed |
| D approvals after the turn | `40cf195` | 346 | all passed |
| D HUD origin | `5658929` | 349 | all passed |
| D guard: encoded commands | `29ac40f` | 352 | all passed |
| D guard: self-approval + allowed roots | `8bd111c` | 360 | all passed |
| D Codex tool isolation (merged) | `a8b8777` | 365 | all passed |

Each new test file was run against the code before its fix and failed there (except control cases that
assert unchanged behaviour). Headless browser checks: `check_brain_browser.py` passes; `check_hud_browser.py`
times out in headless Edge before and after (environmental).

## Privacy and data persistence
- No migration was run. `data/memory.json`, `recent_conversation.json`, preferences and the vault were not
  modified (timestamps checked at the end); every test and live check used temporary copies.
- `memory.json` records may gain two optional fields, `core` and `updated`; legacy `{fact, t}` records load
  unchanged and older code ignores the new fields.
- A turn in which a forget/correction happened is stored in `recent_conversation.json` as a fixed placeholder
  sentence instead of its words.
- Corrections replace the fact in place; no superseded copy, archive or change log holding old wording exists.
- `vault-vectors.sqlite3`: same keys as before; new vectors are stored rounded to 7 digits; vectors of deleted or
  edited notes are purged when the vault changes; a corrupt file is renamed to `*.corrupt-<time>` (kept, not
  deleted) and rebuilt. Vectors also live in process memory while Jarvis runs.
- `search_knowledge` output (to the model and the HUD source cards) is now credential-redacted.
- New files: benchmark reports in `data/reports/memory-benchmark-*.json` (synthetic paths and timings only);
  `update_knowledge_note` writes a short-lived hidden `.jarvis-edit-*.tmp` beside the note during a write.
- No new network destinations. Codex processes for conversation/research now see fewer tools, not more.

## Exercised vs not verified

| Path | Status | Evidence |
|---|---|---|
| Codex conversation (`jarvis.Brain` → your ChatGPT sign-in) | **Exercised live** | 5 turns, temp memory/vault: all 62 tool definitions accepted; follow-up after a harmless `remember` kept context; `search_knowledge` called through Codex and answered from the note; `forget` cleared context; the model used `recall_memory` on its own |
| Local embeddings (Ollama 11435) | **Exercised live** | benchmark and cold/warm matrix above; server started for the measurement and stopped afterwards |
| Codex app-server startup and MCP inventory | **Exercised live** | `scripts/check_codex_mcp_isolation.py` (proposal branch), no model turns |
| Brain UI | Headless check | `tests/check_brain_browser.py` passes |
| Classic HUD page | Not verified | `tests/check_hud_browser.py` times out in headless Edge before and after these changes (environmental) |
| Voice: Qwen synthesis → Whisper recognition | **Exercised live** | Jarvis's `qwen_voice` + `ears.Transcriber` (GPU), rendered to memory, never played: 4.5 s of audio; Whisper heard "The Orion Launch Tower bracket is torqued to 25Nm" |
| Wake word → Whisper → command routing | **Exercised live** (synthetic audio) | Qwen-rendered "Hey Jarvis, what time is it?" through the real `hey_jarvis_v0.1` model: score 1.00, routed as "what time is it"; "What time is it?" without the name: score 0.00, ignored in wake mode |
| Microphone capture, speaker playback, barge-in, voice lock | Not exercised | Needs a person at the headset; no voice/ears/Qwen/dictation file changed; in `jarvis.py` only `Brain` and the system-prompt text changed |
| Jarvis MCP (`list_mcp_tools`, `call_mcp_tool`) | **Exercised live** up to approval | Real catalog through `run_tool`: Zapier MCP 17 tools, GitHub 46; a call queued, asked for approval, and after "no" never contacted the server |
| MCP sign-in (OAuth/bearer) | **Exercised live** | read-only `tools/list` with your saved credentials: Zapier MCP 17 tools, GitHub 46 tools |
| Telegram bridge | **Exercised end to end against a local fake Bot API** | Real `telegram_bridge` polling + `respond_telegram` + Codex + Qwen + Whisper: a stranger's chat ignored; owner text answered ("ready"); owner voice note transcribed and answered from the vault note as text and as a 55 KB Opus voice note. Your real bot is not paired yet (Jarvis reports `available`), so Telegram's own servers were not contacted |
| HOLO | Installed, not started | Starting it turns on the webcam; code unchanged, unit tests pass |
| Codex agent session (research mode) | **Exercised live** | Temp session store; connected, ran, routed one approval request (declined in the test) and reported honestly in 9 s. Original and new guard give the same verdict for that command |
| Claude Code terminal path + guard hook | **Exercised live** | `TerminalWorker` in a temp folder with your Claude Code login: in-folder write allowed; write to `data/cc_approvals.json` blocked by the hook (file unchanged); write to `C:\Windows\Temp` paused for spoken approval, declined, nothing written; guard state files restored byte-for-byte |
| Claude / OpenAI providers | Unit-tested only | Subscription-only mode; no paid API calls were made |
| Your real vault and memory | Not touched | File timestamps unchanged; all tests and runs use temporary copies |

Jarvis was restarted on the new code with `jarvis.py --no-window --quiet-start` (no spoken briefing).

## Using it
- Semantic search needs the local embedding server, which Jarvis does not start: run
  `start-local-model.bat`. Without it, search quietly runs keyword-only (now much better than before).
- Benchmark: `.venv\Scripts\python.exe scripts\memory_benchmark.py --mode both --label <name>`
  (report in `data\reports\`, synthetic paths and timings only).
- Mark an outdated note: frontmatter `status: superseded` (also `outdated`, `archived`, `deprecated`).

## Rollback
Nothing migrated data, so every rollback is code-only and keeps your memory, history and vault:
- Everything: `git reset --hard b873a2b` on `main` would also discard uncommitted edits, so instead use
  `git revert --no-edit b873a2b..HEAD` (or check out `b873a2b` into a new branch); your HUD/README edits stay.
- One change: `git revert <commit>` from the table above (they are independent apart from B2 building on B1).
- Embedding keep-alive only: set `JARVIS_EMBED_KEEP_ALIVE=0` in `.env`.
- Vector cache: deleting `data\vault-vectors.sqlite3` is safe (derived data; rebuilt on the next search).

## Follow-up (same day): paid providers enabled as options
At the owner's request: `subscription_only` set to false in `data/preferences.json` (only that key changed;
previous file kept in the session scratchpad). Codex remains the active default; Claude and OpenAI are selectable
in the Brain's Model control. Key checks: Claude API OK (`claude-haiku-5-5`); ElevenLabs OK (free account endpoint);
OpenAI key valid (127 models visible) but the account returned `credit_balance_exhausted`, so add credit before
choosing OpenAI. Commit `4911bce` keeps terminal tasks on sandboxed Codex sessions even with paid APIs on
(`terminal_provider: "claude"` opts into Claude Code) and fixes terminal status/stop for Codex tasks. Jarvis was
restarted quietly and reports ready. To go back: set `"subscription_only": true` in `data/preferences.json`.
