# Memory & autonomy: audit and plan (2026-10-28)

Source: the owner's "Memory & Autonomy Upgrade" brief (written with ChatGPT, which knows Jarvis only
partly). Each suggestion below is checked against the code and the real data on this PC.

## Audit: what the data says

Measured on 2026-10-28 over ~10 days of use (8 transcript days, 504 user turns):

| Store | What it holds | Reality |
| --- | --- | --- |
| `data/memory.json` (facts) | User facts, core flag, in every prompt | **5 facts.** `remember` was called 6 times in 504 turns. |
| `data/recent_conversation.json` | Last 20 turns, in every prompt | Works. Raw dialogue, not understanding. |
| Vault `Journal/` | Codex summary per day: Done, Decisions, Open threads | Works and is good. **Never read back by Jarvis.** |
| Vault `Reports/` | One note per finished agent task | Works. **Never read back.** |
| Vault `Projects/`, `Decisions/`, `Plans/` | Hand-written notes | 2 + 2 + 2 notes. Found only if Jarvis searches. |
| `Tasks.md` | To-do checkboxes | Works; `list_tasks` used 3 times. Not in the prompt. |
| `data/handoffs/` | Project handoffs with git evidence | Jarvis only; 3 handoffs; `project_handoff` used 0 times. |
| `data/agent_sessions.json` | Agent sessions, last task and report | Works. Not in the prompt; Jarvis must ask for it. |
| `data/task_effort.jsonl` | Per-task effort, time, outcome | 25 records. A start on performance tracking. |
| `semantic_search.py` | Local embeddings over the vault | Works when Ollama runs; Ollama is not auto-started. |

### 1. What exists and works
- Obsidian vault as the human-readable knowledge base (keep it; no reason to change).
- Automatic daily journal and task reports in the vault, summarized on the Codex subscription.
- Fact memory with exact-duplicate checks, never-guess forget/correct, privacy redaction, file locks.
- Vault search (keyword + local embeddings), project handoffs with git evidence, pause/resume of
  agent sessions, approvals and guard rules, model routing and provider switching.

### 2. Partial or unreliable
- **Fact memory is effectively unused.** The design relies on the model choosing to call `remember`;
  in practice it almost never does.
- **Semantic search** depends on Ollama, which isn't started with Jarvis.
- **Project continuity** exists (`project_handoff`, `resume`) but nothing calls it automatically.
- **Proactivity** is limited to calendar heads-ups, reminders and focus nudges. Digests exist but are off.

### 3. Biggest memory weakness
Jarvis has no **working memory**. Each turn's prompt holds the personality, 5 facts and recent dialogue.
It does not hold: what agents are running or just finished, open to-dos, open threads from recent days,
or where each project was left. All of that is recorded, but in places Jarvis never looks unless asked.
That is why he doesn't "know where we left off".

### 4. Do agents share knowledge and keep continuity?
Partly. Agents write reports (agent_sessions.json, vault Reports), and a Codex session keeps its own
thread. But a new task gets only the request plus the project's AGENTS.md; it never receives what other
agents found, the journal's open threads or recent decisions. Writes are one-way.

### 5. Overlap and unnecessary complexity
State is spread over seven stores (facts, journal, reports, handoffs, sessions, Tasks.md, digests) with
nothing tying them together. The fix is one reader that assembles them, not a new store.
`data/` also holds many leftover preview PNGs and one-off scripts (cleanup, low priority).

## The brief's suggestions, addressed

- **"200-fact limit and silent eviction"**: already fixed. At 200, `remember` refuses and evicts nothing;
  the prompt shows a 4,000-character selection and `recall_memory` searches the rest. With 5 facts the
  limit is irrelevant today. The real problem is capture (above). Raise the cap when consolidation lands.
- **Version history when updating**: conflicts with a deliberate privacy rule. Today `correct_memory`
  erases the old wording everywhere. Plan: split the two cases. "Things changed" (new priority, new job)
  keeps the old fact as dated history. "That's wrong" and "forget that" still erase completely.
- **Three levels of memory**: Core = saved facts (core flag exists). Long-term = the vault + search
  (exists). **Working = missing.** Build only the missing level.
- **Scheduled maintenance with local Ollama**: the nightly journal already does extraction on the
  Codex subscription, which costs nothing extra and is far more reliable than the local 4B model.
  Use Codex for consolidation and keep Ollama for embeddings and quick routing. Ollama only where it is
  good enough, not for judgment calls about what is true.
- **AI assumptions must not become verified facts**: agreed. Consolidation will only *propose* facts,
  labeled with their source; the owner approves them, and only approved ones join core memory.
- **Shared agent knowledge without overwrites**: give each agent task a project brief on the way in, and
  write its result to the record on the way out (append-only, under the existing locks).
- **Co-CEO capabilities, model benchmarking, self-improvement**: valuable, but each depends on working
  memory and a reliable record of work. They come after it, in that order.
- **Model independence**: already true. Memory is JSON + Markdown, routing is in model_provider/router.
  Keep every new piece plain-file and provider-neutral.

## Prioritized plan

1. **Working memory ("where we left off").** Assemble, with no AI call, a compact brief: running and
   recently finished agent work, open to-dos, open threads and decisions from recent journal days,
   and each project's last handoff. Jarvis's conversation gets it whenever it changes. The startup
   briefing uses it. *Biggest gain, least complexity: it reads what is already recorded.*
2. **Memory capture by consolidation.** The nightly journal proposes facts, decisions and project
   updates. Jarvis asks the owner to approve them (by voice or the Brain page). Approved items become
   core facts or Decision notes with why, alternatives and status. Add history-preserving updates.
3. **Agents share context.** Every agent task starts with the project's brief and recent findings. Its
   report updates the project's record automatically.
4. **Speed.** Saving a fact currently restarts the Codex conversation thread (slow next reply). Keep one
   warm Codex connection for agents. Measure first-word latency before and after.
5. **Proactive CEO loop.** A scheduled review, reusing the digest scheduler with its quiet hours and
   daily limits: stalled work, risks, ideas and research to start. It ends in a short spoken or
   Telegram brief, not constant interruptions.
6. **Performance and model evaluation.** Extend task_effort into a per-model scorecard (success, time,
   cost) and a small repeatable benchmark for comparing a new model before switching.
7. **Self-improvement proposals.** Jarvis proposes changes to his own workflows as plans. Applying them
   needs approval, and the guard files stay unwritable by agents.

Requirements kept throughout: approval for money, external commitments, destructive and significant
system changes; backups and git checkpoints; agents cannot change their own guard rules.

## Status (2026-10-28, end of day)

All seven steps have a first version, tested (535 tests) and running:

1. Working memory: `working_memory.py`; brief rides in the user turn when it changes.
2. Memory capture: `memory_proposals.py`; journal sections "Decisions" and "Facts to remember";
   approval by voice or the Brain page; `update_memory` keeps history; cap 1000, still never evicts.
3. Shared agent context: project brief in every agent task; results in `data/project_log.jsonl`.
4. Speed (measured first): plain replies median 1.8s, tool turns 4.8s; Codex agent startup ~1s, so no
   warm pool. Fixed: saving a fact no longer restarts the Codex thread. Removed false approval prompts.
5. Daily review: `daily_review.py`, Briefs/<day> Daily review.md after 8:00, spoken once, proposals only.
6. Performance: `performance.py` per-model turn timing and task scorecard (`performance_report` tool);
   `scripts/benchmark_models.py` for fixed-question model comparisons.
7. Self-improvement: the review's "Jarvis improvements" section; acting on it needs the owner's go and
   goes through agent sessions and the guard rules.

Known limits: reviews are only as good as the records (5 core facts today; approve proposals and state
goals). Events outside Jarvis (e.g. restarts done by hand) are unknown unless a handoff records them.
Turn timing starts collecting now; task records have no model name yet.
