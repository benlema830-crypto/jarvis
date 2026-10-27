> **Update 2026-10-26:** this checklist was last audited on 2026-10-21 and is out of date. Since then:
> Codex became the default brain (Claude via Claude Code is selectable), VoiceStudio became the default
> voice with Kokoro as fallback, the second brain gained task reports, a daily journal and meaning search,
> Spotify playback pops up the Miniplayer, the hologram became a 3D sphere that can swap with the graph,
> and the old Jarvis variants were deleted. See docs/PROJECT-MAP.md for current processes.

# Status against the reference checklist

IDs follow [plans/JARVIS-TARGET.txt](plans/JARVIS-TARGET.txt). Updated 2026-10-21 (source audit and automated verification).
Live verification, historical reports, and automated checks are distinguished below. A mock or browser
fixture verifies implementation behavior, not real hardware or account connectivity. Older overnight
reports describe earlier builds; this checklist tracks the current source.

| ID | Area | Status | Evidence / what's left |
| --- | --- | --- | --- |
| 1 | Visual fidelity | **Implemented** | Brain rebuilt to the 1:30 frame: graph-dominant force layout, compact left inspector/hubs/forces, top toolbar, right filter + reactor + modes, bottom dock. Screenshots compared at 1660×896. Remaining: your own taste pass on colours/density with a larger vault. |
| 2 | Second brain | Implemented, needs live test | Vault notes grouped by folder, real links only, inspector with excerpt/full note/Obsidian link/depth/neighbours, shift-click path, right-click reader. |
| 3 | Voice conversation | Implemented; startup health checked | Read-only diagnostics report active INZONE mic/output, listener alive and no output error. Logs record Qwen warm-up. Actual wake/speak/interrupt reliability still needs owner testing. |
| 4 | Knowledge → graph | Implemented; automated checks pass | Retrieval events focus and centre the node; camera follows it while the layout settles. |
| 5 | Research | Previously verified live | Prior build report: Codex live web search enabled; a real query returned in 8.8 s with 8 sources shown and no URLs spoken. |
| 6 | Eyes / Watch / Focus | Implemented; needs live hardware test | Fake-camera tests cover the Eyes round trip and cleanup. Focus implements app-switch tracking, spoken drift callouts, completion summaries and voice commands. Real hardware acceptance is pending. |
| 7 | Reactor | Implemented | RING / CUBE / FACE; motion from real audio level only. |
| 8 | Armory | Implemented; account acceptance pending | Bearer tokens plus OAuth public clients with PKCE, discovery, browser callback, encrypted storage, refresh/rotation, and revocation. Fake-service and browser checks cover success and failures. Saved catalogs show configured, not live-connected. No real MCP accounts are connected yet. |
| 9 | Telegram / documents | Built, needs your bot token | Telegram text + voice notes both ways (Opus round trip tested). Documents: real .docx writer (opened in Word to verify). Google Docs via Zapier MCP. |
| 10 | Model switching | Implemented | Model pill + voice tool, validated before applying. Optional Ollama adapter uses only loopback/local weights and existing tool guards. Codex remains selected; paid APIs stay disabled. |
| 11 | Holo | Implemented and installed; camera test pending | Separate HOLO installed at `C:\Users\Lemab\holo`, revision `55626ff`, configured for the existing vault. Its inert gesture probe passes 26/26 checks with synthetic notes. No real camera test performed. |

Also added: tasks in `Tasks.md` (verified live via Codex), "good morning" briefing on demand, Ctrl+Alt+D dictation,
calendar heads-ups, speech never reads links.

## Current setup and verification

- Main installation: `C:\Users\Lemab\jarvis`; Jarvis Agent is a navigation hub.
- Saved conversation selection: Codex `gpt-6.1-sol`, subscription-only enabled.
- Calendar feed configured; not fetched during this audit.
- Telegram token/pairing absent; no saved MCP connections. Account setup remains an owner action.
- HOLO installed and configured; its real server/camera have not been launched by this workday pass.
- Isolated Ollama v0.40.7 and qwen3:4b installed under `data/local-brain`; archive SHA256 verified. Real synthetic inference and a tool round trip passed on this PC (8.66 seconds for the latter, one tool execution). See `data/local-brain/setup-result.json`.
- Quietly activated the workday build after confirming no active turn/job or visual mode. Post-restart diagnostics: listener ready, mic active, no speech pending/output error; Codex still selected. Local model discovery enabled at `127.0.0.1:11435`; service idle with zero models loaded.
- Existing Qwen benchmark reports show faster warm synthesis; subjective voice quality and gaming-load performance remain owner acceptance items.
- Integration inventory does not test external services. Configured means saved settings, not a successful live request.

## Workday changes completed without owner testing

1. Saved the existing implementation in local Git checkpoint `7628f2e`. Runtime data, credentials, voice identity, audio, downloaded models and environments are excluded.
2. Implemented and tested OAuth. Public-client scope and compatibility limits are documented in SETUP-TOMORROW.md. Authentication never replaces the existing per-tool approval checks.
3. Added a cross-process store lock so the assistant and Brain companion cannot overwrite rotating OAuth refresh tokens.
4. Implemented an optional local conversation provider, model validation, streaming, cancellation, and native tool round trips through the existing dispatcher. No silent provider switch or paid fallback.
5. Installed HOLO and added an inert browser probe. Fixed the setup script so failed downloads/configuration cannot report success.
6. Added `scripts/verify_project.py` to run inert checks and save results. Fixed rapid close/reopen cancellation in the OAuth dialog.
7. Real local inference exposed duplicate tool requests from the small model. Identical calls within a local turn now reuse the first result instead of executing an action again; regression and real-model checks pass.
8. Fixed an intermittent Windows HTTP reset on rejected requests: small unread request bodies are drained with a short timeout so clients receive the intended error. Settings remain unchanged on rejection.

## Deferred until the owner is available

- Headset wake/speak/interrupt and approval flow.
- Real-note retrieval with visible graph focus; sourced research and document/task walkthrough.
- Explicit start/stop of Eyes, Watch and Focus; real hand gestures.
- Optional Telegram pairing and one harmless approved MCP call, plus a declined call.

Automated checks: `python -m unittest discover -s tests` and `python tests/check_brain_browser.py`.
Latest expanded unit suite: 266 tests. See the repeatable verification report at `data/reports/project-verification.json` for pass/fail evidence, Brain UI and HOLO probe results.
These checks use inert fixtures and do not establish live camera, headset or external-account behavior.

## Response settings and Linux continuation (2026-10-21)

- Response preferences implemented: humor, directness, explanation length, tone, pushback and use of
  "sir". More > Response settings and voice tools persist changes across restarts; next-turn refresh
  retains text dialogue. Truthfulness and action approvals are independent of style.
- All reviewed existing features retained. Classic HUD removed from the selectable menu; the assistant
  HTTP/event backend remains required. Latest feature checkpoint: `dfbf487`.
- Native Linux dual boot is planned by the owner; no Linux installation, disk changes or Linux hardware
  acceptance has occurred. Detailed current-state handoff, migration boundaries, phased implementation
  and all 58 proposed improvements: [Claude/Linux handoff](plans/CLAUDE-LINUX-HANDOFF.txt).

## Project continuity additions (2026-10-21)

- Project memory and handoffs: read-only recall for Jarvis/Rocket Frontier, current Git evidence,
  attributed status/validation files, agent reports, dated persistent handoffs, unresolved items,
  relevant files and next actions. Available through voice tools and More > Project tools.
- Local semantic vault retrieval: installed `embeddinggemma:300m`, incremental SQLite vectors,
  bounded vault-only chunks, invalidation on edit/delete/model/root changes, and explicit keyword
  fallback. Real synthetic inference ranked a persistence note first for "player progress between
  visits" (0.5129 vs unrelated cooking note 0.1680). The actual vault indexed seven chunks in 8.34 s.
  This verifies local retrieval, not spoken delivery or subjective search quality across a large vault.
- Named routines: editable Development mode and Wrap up templates; exact-step previews and one-use
  approvals, expiry/change invalidation, stop-on-error and cancellation between steps. UI supports
  choosing/reordering steps; voice runs ask for approval. Tests execute injected effects only.
  No real routine, Focus session, project agent or account operation was started during this build.
- Conversation remains on Codex. Local embeddings are separate from the optional conversation model.
- Quiet activation passed: live project recall, routine list/preview (cancelled without running),
  semantic search and new UI asset all responded. Assistant returned ready/listening with its listener
  alive, mic active, no speech pending/output error, and Codex `gpt-6.1-sol` still selected.

## Digests, privacy and file tools (2026-10-21)

- Scheduled daily research/progress digests implemented with timezone, quiet hours, daily attempt caps,
  persisted reservations, restart recovery and visible failures. Nothing is scheduled/enabled by default.
  Research smoke test: real Codex run, 35.69 seconds, four searches, two cited URLs corroborated by source
  events. The report explicitly said current publication dates could not be verified and labeled older
  findings. Saved at `data/reports/scheduled-research-smoke.json`; this proves sourced execution, not that
  blocked Roblox pages can always be read or that every generated claim is correct.
- Memory viewer supports version-checked fact edits/deletions, recent-dialogue inspection/clearing, and
  optional exact-phrase/email/phone filters. Recognizable credentials/SSNs filtered by default at owned
  model-text boundaries and memory saves. Active and restarted conversations exclude pre-edit context.
  Detection is imperfect; images, independent coding-tool file reads, old exports/logs/backups and
  provider-side retention are not covered. Full boundaries documented in SETUP-TOMORROW.md.
- Local XLSX/PDF/PPTX generation implemented with budget totals, trackers, tables and editable/vector
  charts. Real sample outputs created and reopened. PDF rendered and inspected; fixed chart baseline so
  the smallest category remains visible. Office application acceptance is not claimed.
- Expanded browser fixture exercises the three panels and verifies opening them never runs a digest or
  enables a schedule. Regression checks cover redaction boundaries, stale memory edits, restart/daily caps,
  failures, source filtering, formula injection, chart persistence, PDF text and slide continuation bounds.
- Activated quietly after checking the assistant and project workers were idle. Live memory/file panels
  responded; a manual progress-digest test completed with two local sources and zero AI calls, and its
  temporary disabled schedule was removed. Zero schedules remain enabled. Assistant health returned
  ready/listening, listener alive, mic active, no output error/speech pending; Codex remains selected.
  Evidence: `data/reports/workday-456-activation.json`. Default filters were applied to saved facts and
  recent dialogue without logging their contents.
