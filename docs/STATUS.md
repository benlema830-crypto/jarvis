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
| 8 | Armory | Implemented | Video-style armory: built-ins, Zapier/GitHub presets with prefilled URLs, custom MCP. Saved catalogs now show configured rather than connected; no MCP connections are currently saved. OAuth-only servers (Home Assistant, some one-click apps) still unsupported. |
| 9 | Telegram / documents | Built, needs your bot token | Telegram text + voice notes both ways (Opus round trip tested). Documents: real .docx writer (opened in Word to verify). Google Docs via Zapier MCP. |
| 10 | Model switching | Implemented | Model pill + `switch_model` voice tool, validated before applying. |
| 11 | Holo | **Implemented** | Built-in MediaPipe hand control (model load verified) + bridge to the creator's HOLO app (install with `scripts/setup_holo.ps1`). |

Also added: tasks in `Tasks.md` (verified live via Codex), "good morning" briefing on demand, Ctrl+Alt+D dictation,
calendar heads-ups, speech never reads links.

## Current setup and verification

- Main installation: `C:\Users\Lemab\jarvis`; Jarvis Agent is a navigation hub.
- Saved conversation selection: Codex `gpt-6.1-sol`, subscription-only enabled.
- Calendar feed configured; not fetched during this audit.
- Telegram token/pairing absent, no saved MCP connections, separate HOLO app absent.
- Existing Qwen benchmark reports show faster warm synthesis; subjective voice quality and gaming-load performance remain owner acceptance items.
- Integration inventory does not test external services. Configured means saved settings, not a successful live request.

## Next work that does not require the owner

1. Review and checkpoint the accumulated source changes in Git, excluding personal data, credentials and generated assets. The source audit found 80 modified/untracked entries before this follow-up.
2. Continue targeted regression checks for failures found in code review, using fake services and hardware.
3. Scope MCP OAuth support: provider discovery, browser authorization, callback handling, encrypted token storage, refresh/revocation, and failure tests. Real account authorization will remain a later owner step.
4. Evaluate an optional offline conversation adapter after the core is stable; do not silently change subscription-only behavior.

## Deferred until the owner is available

- Headset wake/speak/interrupt and approval flow.
- Real-note retrieval with visible graph focus; sourced research and document/task walkthrough.
- Explicit start/stop of Eyes, Watch and Focus; real hand gestures.
- Optional Telegram pairing and one harmless approved MCP call, plus a declined call.

Automated checks: `python -m unittest discover -s tests` and `python tests/check_brain_browser.py`.
Latest result: 210 unit tests passed; headless browser check passed, including saved MCP status rendering.
These checks use inert fixtures and do not establish live camera, headset or external-account behavior.
