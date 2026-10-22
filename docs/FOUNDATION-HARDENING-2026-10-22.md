# Foundation hardening — 2026-10-22

Implementation of `docs/plans/JARVIS_CODEX_TERMINAL_HANDOFF_2026-10-22.md` (phases A–D).
Branch `foundation-hardening`, ten commits on top of `b873a2b`. No live data was migrated,
rewritten or read beyond file timestamps; the real Obsidian vault was never opened. All
measurements use the synthetic fixture in `tests/retrieval_fixture.py`.

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

Cold first search incl. indexing, Ollama on: 37.8 s originally → 2.1 s with a model load, 0.37 s with the model warm.

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

Approval channels (documented, unchanged): owner voice, the local console (`--text`), and the local
HUD/Brain text box. Model output, tool/MCP results, Telegram, HOLO, reminders and agent reports
arrive as dict items and never reach `approvals.answer()`.

Proposed, **not implemented — needs your decision**:
- **MCP inheritance.** Jarvis-launched Codex agent sessions inherit `~/.codex/config.toml`, including
  `Roblox_Studio` with `execute_luau` set to `approval_mode = "approve"`. A Jarvis "research" session
  can therefore run Luau in Studio without asking (the read-only sandbox does not cover MCP tools).
  Option: disable MCP servers for research-mode sessions, or require Jarvis approval for MCP calls.
- **Keyword guard limits.** `cc_guard` cannot see intent (e.g. `Set-Content` emptying a file, uploads
  via `Invoke-WebRequest -Method Post`). For Codex sessions the real boundary is the platform sandbox
  (workspace-write to the project folder, no network). Whether Codex's Windows sandbox is actually
  enforced on this PC was **not verified** and should be checked once with a harmless probe.
- **Local processes.** Any program running as you can POST `/command` (including "yes"). This is the
  accepted local-trust model; a per-launch token would close it but touches every HUD client.
- `agent_sessions` one-job-at-a-time guard is untouched, as required.

## Not verified here
Live voice/Qwen/Whisper, Codex or Claude conversations, MCP OAuth, Telegram and the real vault were not
exercised. `tests/check_hud_browser.py` times out in headless Edge both before and after these changes
(environmental); `tests/check_brain_browser.py` passes. The running Jarvis still uses the old code until
restarted (`.venv\Scripts\python.exe jarvis.py --no-window --quiet-start`).

## Using it
- Semantic search needs the local embedding server, which Jarvis does not start: run
  `start-local-model.bat`. Without it, search quietly runs keyword-only (now much better than before).
- Benchmark: `.venv\Scripts\python.exe scripts\memory_benchmark.py --mode both --label <name>`
  (report in `data\reports\`, synthetic paths and timings only).
- Mark an outdated note: frontmatter `status: superseded` (also `outdated`, `archived`, `deprecated`).

## Rollback
Nothing migrated data, so every rollback is code-only and keeps your memory, history and vault:
- Everything: `git switch main` (your uncommitted HUD/README work stays in the working tree).
- One change: `git revert <commit>` from the table above (they are independent apart from B2 building on B1).
- Embedding keep-alive only: set `JARVIS_EMBED_KEEP_ALIVE=0` in `.env`.
- Vector cache: deleting `data\vault-vectors.sqlite3` is safe (derived data; rebuilt on the next search).
