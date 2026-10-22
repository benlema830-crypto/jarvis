# JARVIS CEO — CODEX / CLAUDE TERMINAL IMPLEMENTATION HANDOFF

**Date:** 2026-10-22  
**Target:** The existing, working **Jarvis CEO** Windows project, not a new project.  
**Origin:** External static review of a sanitized source export dated 2026-10-22. The live local repository may differ.  
**Primary objective:** Make Jarvis more dependable at remembering, retrieving, correcting, and explaining information **before** building a larger AI CEO / multi-agent organization.

> **For the terminal agent:** Treat this file as an implementation brief, not as proof that the live project has every described problem. Inspect the actual current code and tests; confirm each issue; implement incremental fixes that preserve existing behavior. Do not replace Jarvis, Obsidian, the voice stack, the model providers, MCP integrations, or the Brain UI with a new framework.

---

## 0. REQUIRED OPERATING RULES

1. **Work locally in the existing Jarvis CEO repository.** Read `README.md`, `docs/PROJECT-MAP.md`, any `AGENTS.md` and active handoff, then inspect the modules below. Follow higher-priority repository policies.
2. **Do not upload, log, display or transmit** the live `.env`, tokens, OAuth credentials, Obsidian vault contents, voice samples, personal memory, or any employer/customer data. Never paste secret-containing output into a report. Read only the minimum live configuration necessary to verify integration behavior.
3. **Protect live data.** Develop and test using `tempfile`, mocks, synthetic Markdown vaults and isolated SQLite fixtures. Do not migrate or rewrite real `data/memory.json`, recent conversations or the user's Obsidian vault without explicit approval and a tested rollback plan. Do not delete or archive sensitive records in new places without respecting the existing forget/privacy model.
4. **Check Git state** (`git status --short`, current branch, existing diffs). The live repository may contain uncommitted work. Do not overwrite it, discard it, force reset, or mix unrelated changes. Before a risky refactor, make a reversible checkpoint using the user's established workflow; ask before potentially destructive Git operations.
5. **No surprise infrastructure.** Prefer Python standard library, SQLite and existing dependencies. Do not introduce CrewAI, LangGraph, Paperclip, cloud vector DBs, new hosted APIs, a Docker stack, or a new Obsidian plugin merely to implement these fixes. Request approval before machine-wide installation, new paid dependencies, firewall/network changes, publishing or deployment.
6. **Keep core features working:** PowerShell/Windows launchers; Codex and Claude model paths; local Ollama embedding model on `127.0.0.1:11435`; Qwen voice/Whisper; MCP tool permissions; Telegram; desktop automation; voice and typed input; existing Obsidian graph and note links; safe refusal on forbidden paths.
7. **Treat privacy as an invariant.** Removing/correcting a memory must not cause deleted or superseded content to reappear from active chat history, restored history, summaries, vector indexes, UI caches, logs or newly introduced archives. A privacy-related reset may be intentional. Never fix perceived continuity issues by disabling privacy invalidation.
8. **One bounded change at a time.** For each step: inspect → write regression test → make small change → run targeted tests → run full suite if practical → summarize results. Stop and report a blocker if a step would risk personal data or break critical behavior.
9. **Do not claim green tests unless executed.** Report exact commands/results, skip reasons, tests that need a Windows GPU/voice stack, and manual checks required.
10. **Do not start an AI-company rewrite in this pass.** We are fixing the assistant and specifying future agent infrastructure, not deploying unattended autonomous employees.

## 1. BASELINE: VERIFY THE LIVE PROJECT FIRST

Read at minimum: `jarvis.py`, `memory.py`, `semantic_search.py`, `knowledge.py`, `tools.py`, `privacy.py`, `model_provider.py`, `codex_brain.py`, `agent_sessions.py`, `approvals.py`, `terminal.py`, `cc_guard.py`, `knowledge_events.py`, `tests/test_recent_memory.py`, `tests/test_knowledge.py`, `tests/test_jarvis.py`, and `tests/test_agent_sessions.py`.

- List preexisting modifications and relevant module versions.
- Run the existing unit tests using the project's venv if installed, e.g. `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` from the repository root. Adapt to the actual shell/path; don't install dependencies just to satisfy unrelated tests without permission.
- Collect current baseline test failures and separate environment-specific ones from regressions.
- Establish a **synthetic test vault** with: exact part-number note, synonym/rephrasing note, conflicting old/current preference notes, a deleted note, duplicate titles, and a note containing malicious prompt-like text. Include at least one private-looking fake credential in fixtures to ensure it is not emitted.
- Set a baseline for search quality and latency using the local machine if Ollama is present. Do not claim speed gains without measurement.
- Before changing APIs, find every call site; especially the memory revision path, provider-specific conversation history, voice report path and search-knowledge formatting.

## 2. PHASE A — CRITICAL CORRECTNESS (IMPLEMENT FIRST)

### A1. Preserve chat continuity on benign memory additions; preserve privacy on deletion

**Observed in source export:** `jarvis.py` `Brain.ask()` checks `memory.revision()`. Any revision change rebuilds the system prompt, sets `self.messages = []`, resets OpenAI turn state and closes the Codex adapter. `memory.remember()` changes `memory.json`, so a normal remembered fact can trigger this reset on the next turn. In contrast, `memory.forget()` and `memory.edit()` write a `memory.json.epoch` marker intentionally used to filter old recent history.

**Implementation:**
- Separate **benign data refresh** from **privacy invalidation / deletion / correction**. Refresh persistent fact context without silently erasing otherwise valid conversation context on ordinary `remember()`.
- Adapt or reinitialize provider adapters correctly when the system context changes. Do not leave stale system prompts inside a persistent Codex session or replay incompatible tool call pairs.
- Explicitly preserve the current privacy behavior when forgetting, clearing or scrubbing, and when editing facts in a way that supersedes old sensitive content. Do **not** reintroduce removed data via `recent_prompt()` or model conversation messages.
- Examine whether the existing epoch marker gives sufficiently clear semantics. Add a minimal explicit privacy revision/version if needed, maintaining migration compatibility.

**Regression tests:**
1. User discusses a project; Jarvis remembers an unrelated benign fact; next follow-up still resolves the project reference.
2. Remembering the same fact twice does not cause unnecessary disruption.
3. Forget/correction prevents the old value from entering **both** the system prompt and conversation history after the next turn and restart.
4. Model provider switch and response-style changes preserve safe text continuity and never leave unmatched tool messages.
5. Repeated turns don't endlessly duplicate `recent_prompt()` into working history.

**Acceptance:** Benign memory writes no longer unexpectedly reset the conversation; forget/correction still invalidate all stale personal context.

### A2. Stop silent loss of facts at MAX_FACTS

**Observed:** `memory.py` has `MAX_FACTS = 200` and `remember()` saves `items[-MAX_FACTS:]`, silently evicting the oldest fact beyond the cap.

**Implementation:**
- Maintain backward compatibility with existing `data/memory.json` records (`fact`, `t`) and current `facts()`, `snapshot()`, `edit()`, `revision()`, `prompt_section()` callers.
- Remove silent eviction. **Safest first fix:** if full, do not lose any data; return a clear, actionable capacity message or add a safe compaction path only if its semantics and privacy handling are proven. Do not silently increase the cap and inject hundreds of additional facts into every prompt.
- If adding archiving/undo, ensure explicit user deletion also removes the content from that archive; avoid creating a hidden second source of truth.
- Deduplicate carefully; never conflate unrelated facts solely because of fuzzy text similarity.

**Tests:** insert >200 unique synthetic facts; previously saved items remain intact, overflow behavior is explicit, duplicate inserts do not count twice, and concurrent writes remain atomic.

**Acceptance:** No automatic loss of stored personal facts, including at the cap.

### A3. Introduce a bounded active memory prompt (without losing searchability)

**Observed:** `memory.prompt_section()` inserts the full fact list into `SYSTEM_PROMPT` in `jarvis.py`. There is no strict prompt budget and saved facts are mixed with conversational context.

**Implementation:**
- Add a small, deterministic, **budgeted** active-memory section; keep all durable facts stored and discoverable without injecting everything in every prompt.
- Prefer a curated durable profile and recently active topics; if you cannot choose relevance safely without new dependencies, use a conservative deterministic ranking and **explicitly document the tradeoff**. Do not pretend a fact is forgotten merely because it isn't in the injected prompt.
- Add a narrow, authorized way to retrieve additional relevant memory on demand. Reuse existing tools or add one safe read-only memory lookup, subject to privacy redaction; avoid duplicating full-vault retrieval logic.
- Preserve the existing no-instruction-from-untrusted-data rule. Never treat retrieved web notes as authoritative user directives.

**Tests:** measure capped characters/tokens, exact query on a non-injected fact still finds it, injected context does not include deleted/superseded facts, and known core preferences remain available.

**Acceptance:** Bounded prompt size + full-memory retrievability + no regression in privacy.

## 3. PHASE B — BETTER OBSIDIAN RECALL (IMPLEMENT AFTER A)

### B1. Hybrid keyword + semantic search

**Observed:** `semantic_search.search()` runs vector similarity when Ollama works, and uses `knowledge.search()` only on an exception. Exact filenames, drawing numbers, acronyms and proper names can benefit from lexical search even when embeddings are available. `tools.search_knowledge()` currently returns only the result list and hides search-mode metadata.

**Implementation:**
- Combine lexical and semantic candidates on successful Ollama queries, and return lexical-only results when Ollama fails. Deduplicate by normalized vault-relative path and prefer results with the best available specific excerpt.
- Use a simple explainable fusion technique such as **reciprocal rank fusion (RRF)**, with an explicit exact title/path match boost; do not confuse incompatible raw scores.
- Retain compatibility for existing callers that expect `results` entries with `path`, `title`, `uri`, `excerpt`, `search_mode`. Preserve the response size limit and safe path validation.
- Allow diagnostics (`mode=hybrid/keyword`, reason, top source paths, rank contributions) for local troubleshooting without printing personal contents or exposing secrets.
- Handle empty vault, embeddings disabled/missing, model mismatch, corrupt index and zero keyword hits correctly. Avoid returning stale vectors from deleted/edited notes.

**Tests:** (1) exact technical ID; (2) paraphrased question; (3) both query types together; (4) offline embeddings; (5) deleted note excluded; (6) stable ordering and no duplicate source; (7) prompt injection inside note never becomes an instruction.

**Acceptance:** At least baseline semantic recall, materially improved exact-term recall, and graceful local-model failure.

### B2. Make indexing independent of interactive query latency (incrementally)

**Observed:** `semantic_search.search()` currently calls `knowledge.index()` and scans/rebuilds the chunk list on every query, reconciles SQLite vectors, embeds missing chunks and runs cosine similarity in Python. `knowledge.index()` also calculates graph links.

**Implementation:**
- First add **instrumentation**: p50/p95 total retrieval time, index refresh time, embedding time, and query time using synthetic notes. No private query bodies in metrics.
- Reuse/extend the local SQLite vector store with file path + modification fingerprint, model identity, chunks and last-indexed time. Refresh changed files incrementally in a bounded/background job or on demand with clear stale-index policy; use thread/process locking appropriate to local Windows launches.
- Avoid coupling graph visualization/backlink recomputation to every semantic search; preserve `knowledge.index()` and its current graph behavior for UI callers.
- Deletion, edit and rename must invalidate prior chunks before they can appear in a search result. Never trade correctness or deletion semantics for speed.
- Don't add a hosted search service or heavy vector database at this scale.

**Tests:** unchanged note avoids re-embedding; edit only reindexes affected note; deleted note is never returned; restart/recovery and concurrent requests are safe. Measure **before/after** with the same fixture and machine.

**Acceptance:** Search remains correct; fewer avoidable re-embeddings/re-scans; observed latency doesn't regress.

### B3. Tune Ollama keep-alive, do not blindly change it

**Observed:** `semantic_search.embed()` sends `keep_alive: 0`, causing the embedding model to be unloaded after a request. The live GPU also hosts speech and may be memory-constrained.

**Implementation:** Measure cold and warm embedding query times, GPU utilization or VRAM pressure if safely available, and speech latency while Qwen is active. Make keep-alive configurable (current `0` remains safe default until evidence indicates otherwise). No perpetual GPU residency without measurement.

**Acceptance:** Choose and document a setting based on **real measurements** on this PC, with easy rollback.

## 4. PHASE C — TRUSTWORTHY LIVING MEMORY (SAFE, SMALL ADDITIONS)

### C1. Provenance, contradictions and supersession

**Observed:** `memory.remember()` stores basic `{fact,t}` records, with exact-string deduplication but no first-class subject, source, status, or supersession. `memory.edit()` exists for manual editing.

**Implementation:**
- Propose a backward-compatible **optional** metadata schema: `id`, `fact`, `created_at`, `updated_at`, `source_type` (`user`, `note`, `tool`), `source_ref`, `status` (`active`, `superseded`), `supersedes`, and user confirmation status. Add only fields the application will actually use.
- Keep explicit user statements authoritative over inferred/web content; do not auto-promote external text into personal truths. Do not automatically overwrite facts based on ambiguous similarity.
- Support a clear user-initiated correction that updates the active fact and invalidates the old value from prompts, search, cached sessions and restart history. Keep a privacy-safe change log that cannot resurrect explicitly forgotten details.
- If the schema would require a risky live migration, build tests and an isolated migration plan, then request approval before running it on live data.

**Tests:** outdated/current project priority, two similarly worded but unrelated facts, correction, deletion, reload of legacy records, and privacy scrub.

**Acceptance:** Jarvis can distinguish current from superseded personal information without hidden duplication.

### C2. Safe targeted edits for existing Obsidian notes

**Observed:** `knowledge.create()` is intentionally create-only (`open('x')`), and `read()` / `note_path()` have careful path checks. Do not weaken them.

**Implementation:**
- Introduce a **separate** note-update API that edits a named section/frontmatter field or applies a specified diff with expected content hash/mtime. Never change `create()` to overwrite existing notes.
- Reject symlinks, junction escapes, hidden folders, non-Markdown paths, oversized files, stale hashes and ambiguous headings. Use safe atomic writes and a readable preview/diff. Offer an explicit user approval step for destructive replacements.
- Respect Obsidian's edits: on conflict, stop and ask rather than replacing newer manual changes. Preserve formatting outside the target section and line-ending behavior where reasonable.
- Prefer a small local implementation; evaluate Obsidian Local REST API only if the user's existing MCP already supplies these semantics, to avoid redundant plugins.

**Tests:** target-section-only change; unrelated content preserved; stale expected hash rejected; traversal/symlink/junction attacks rejected; notes deleted between read/write are not silently recreated; concurrent edits conflict safely.

**Acceptance:** Living project summaries can be edited safely, visibly and reversibly.

### C3. Memory/search observability and private benchmarking

**Implementation:**
- Add a small local `tests/fixtures` or generated temporary-vault benchmark of **at least 25 questions** spanning exact terms, paraphrases, note citations, outdated vs corrected facts, temporal questions, missing facts, prompt injection and deletion.
- Track retrieval recall@k, exact-source correctness, false-memory rate, response prompt size, search latency p50/p95, and—only where practical—time to first spoken response. Run with and without Ollama.
- A UI diagnostics panel is optional. Start with a CLI-friendly **redacted report** that shows mode, timings, and source paths for synthetic test data. Do not stream the real user's memory contents into test logs.

**Acceptance:** There is a repeatable baseline proving whether each memory improvement helps.

## 5. PHASE D — SECURITY & AGENT READINESS (REVIEW, THEN SMALL FIXES)

These are important but are **not** permission to rewrite the whole terminal executor or turn on unattended multi-agent work.

- **Approvals:** Inspect `approvals.py`, voice/text input handlers in `jarvis.py`, UI control paths and `tests/test_approval_speech.py`. Explicitly document which channels can approve actions. Ensure the model, a tool result, web content, a remembered fact, or another agent cannot self-approve. If typed owner input is intentionally allowed, retain it but bind it to a trusted local user-initiated channel rather than relying on free text alone. Test ambiguity, timeouts, cancellation, no-pending-action, and replay.
- **Terminal safeguards:** Inspect `terminal.py`, `cc_guard.py`, `agent_sessions.py` and tool dispatch. Enforce agent-specific allowed roots/tools and explicit approval for destructive, outbound, machine-wide and permission-changing actions. Do not use brittle keyword matching as the sole permission boundary, especially for compound PowerShell commands. Prefer platform sandboxing and allowlisted operations where feasible.
- **Local Brain API:** Confirm loopback binding in `brain.py`, `hud.py` and any related servers. Assess CSRF, Origin checks, browser-to-localhost risks, and API authentication tradeoffs. Don't break localhost-only behavior or invent a cloud authentication dependency.
- **MCP:** Review least privilege and prompt-injection boundaries, confirm tools are not automatically shared across future workers, and preserve existing approval checks. No changes to installed MCP credentials without approval.
- **Agent sessions:** `agent_sessions.py` currently serializes active project jobs. **Do not remove this guard** until a proper durable queue, per-job workspace isolation, task IDs, cancellation, worker limits, permissions and budget/timeout controls are designed and tested.

**Deliverable for this phase:** Verified security findings, targeted regression tests and any safe low-risk fixes. Put major security changes in a **separate proposed change** for explicit review.

## 6. WHAT NOT TO BUILD IN THIS PASS

- No CEO organizational chart, employee spawning, infinite self-reflection loops or autonomous spending.
- No parallel Codex/Claude employees until state, workspace, permission and queue semantics exist.
- No rewrite of `jarvis.py` into a new framework unless a demonstrated bug cannot be solved locally.
- No replacement of Obsidian with another database. SQLite may support search indices and future task state while Obsidian remains the human-readable knowledge vault.
- No giant new UI dashboard, voice redesign, model shopping or installation of multiple new MCP servers.
- No automatic edit of the user's actual Obsidian knowledge base without an explicit request and a verified backup.

## 7. DEFINITION OF DONE

This phase is done when the terminal agent can truthfully demonstrate:

- [ ] No silent loss of facts beyond 200.
- [ ] Adding a harmless long-term fact doesn't unexpectedly erase safe working conversation context.
- [ ] Forgetting/correcting a personal fact still removes stale context from prompts/history/cache.
- [ ] Active prompt memory is bounded and additional stored facts remain retrievable.
- [ ] Exact phrase/filename and semantic vault questions both work with Ollama online, with safe fallback offline.
- [ ] Edited/deleted vault notes cannot appear as stale current search results.
- [ ] Existing path security and create-only note semantics remain intact; any new edit API is version-checked and tested.
- [ ] Local synthetic memory benchmark runs and emits useful before/after results.
- [ ] No voice/model/MCP/agent-session regressions in the tested paths.
- [ ] An honest report lists changes, tests and remaining known risks.

## 8. REQUIRED FINAL TERMINAL REPORT

At each completed milestone, report:

1. **Confirmed issue** versus findings from the sanitized export that no longer apply.
2. **Modified files** and a brief description of each behavior change.
3. **Tests added and executed**, exact command and passing/failing/skipped counts.
4. **Performance evidence** for retrieval changes (same machine, same fixture, cold/warm distinguished).
5. **Privacy/security implications** including any memory migration or data persistence changes.
6. **How to use and roll back** the changes without destroying prior user data.
7. **Remaining work** grouped into next safe milestone vs larger optional CEO features.
8. **Do not claim voice recognition, Qwen, MCP OAuth, live Obsidian, Codex or Claude integrations were verified unless actually exercised.**

**Recommended implementation order:** A1 → A2 → A3 → B1 → benchmark baseline/diagnostics (C3) → B2 → B3 → C1 → C2 → security review (D). Break into reviewable commits or checkpoints; stop if risky migration or security-sensitive behavior needs approval.

---

## Minimal kickoff message to paste into Codex / Claude

> Please read `JARVIS_CODEX_TERMINAL_HANDOFF_2026-10-22.md` in the current Jarvis CEO repo and follow it as the implementation brief. Start by inspecting the live code and existing Git changes, running the baseline tests, and fixing **Phase A** with new regression tests. Preserve my Qwen voice, Obsidian vault, Codex/Claude paths, MCP integrations, UI and all live data. Do not access or modify unrelated employer files or upload private configuration. Fix issues one by one, then continue through Phase B and C only after tests pass. Give me a precise changelog, test results, rollback instructions and any blockers. Do not start the AI CEO multi-agent rebuild yet.
