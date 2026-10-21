# Research notes (2026-10-21)

Workday implementation update: the historical backlog below has advanced. OAuth public-client
support and an optional local Ollama provider are now implemented, with fake-service regression
tests. HOLO is installed and its inert gesture probe passes. See [STATUS.md](STATUS.md) for current
evidence and [SETUP-TOMORROW.md](SETUP-TOMORROW.md) for compatibility limits and activation.
Real account authorization and hardware acceptance remain pending.

What the reference video does, what comparable open-source assistants do, which free tools are worth
adding, and how each maps onto this codebase. Reddit could not be read by the research tools (blocked for
automated access), so findings come from the video transcript, GitHub, and official docs.

## The reference video, feature by feature

Source: [I Built JARVIS with GPT-6 Astra](https://www.youtube.com/watch?v=mitzci4FsOg) (AI Workshop),
[transcript](https://prepublish.ai/youtube-transcript/mitzci4FsOg), plus the owner's screenshots in
`Documents/Jarvis Agent/06 References`.

| Video | Here |
| --- | --- |
| Colour-coded 3D second brain of notes/files | Brain graph: force-directed 3D, coloured by vault folder, real wikilinks, hubs, inspector, depth, shift-click path |
| Wake word, hands-free toggle, spoken replies | openWakeWord "hey Jarvis", wake/continuous mic button, Qwen voice clone, interruptible |
| Ask for a topic → related files open | `search_knowledge` focuses matching notes in the graph; `open_path` / Obsidian links open them |
| Right-click a folder for details | Right-click a node → reader; click → inspector |
| Web research ("cheaper alternatives to …") | Codex live web search; sources listed in the Brain |
| Eyes (camera; slouching / phone call-outs) | EYES mode + `look_through_camera`; optional 5-minute *Coach me* glance |
| Screen sharing | WATCH mode + `look_at_screen` on request |
| Focus lock for N minutes, drift tally, jokes | FOCUS mode / `focus_mode` tool; drift → spoken one-liner; completion summary |
| Ring / cube / blue face | RING / CUBE / FACE reactor (mouth driven only by real audio level) |
| Holo hands (unfinished in the video) | HOLO: built-in MediaPipe hand control of the graph + bridge to the creator's released HOLO app |
| Tool armory: Gmail, Notion, Docs, Sheets, "add your own" | Armory with built-ins, Zapier/GitHub MCP presets, custom MCP URL + token |
| Text input | Command bar |
| Telegram text + voice replies | Telegram bridge: text and voice notes in, text + Qwen voice note out |
| Branded invoice in Google Docs using existing context | `create_document` (local Word) after searching the vault; Google Docs via Zapier MCP |
| Switch brain by voice | `switch_model` tool + model pill |

The creator's follow-up ("[JARVIS Now Has Tools](https://videohighlight.com/v/dCKBxcYGkoE)") adds tools through
MCP, mainly Zapier, and one-click OAuth for some apps.

## HOLO (the "holohand" program)

- Repo: [zubair-trabzada/holo-gestures](https://github.com/zubair-trabzada/holo-gestures) (MIT, ~100 stars). Also
  mirrored as [jarvis-ai-1-8/JARVIS-](https://github.com/jarvis-ai-1-8/JARVIS-).
- `python server.py` (standard library only) on port 4890 (`HOLO_PORT`), one `holo.html` page in Chrome, MediaPipe
  Tasks Vision and three.js vendored locally. `holo.json` → `{"folder": "…"}` picks the notes folder; subfolders
  become orbs, notes become cards.
- It POSTs gesture events to `/api/state`, saved to `state/holo-state.json` as `{event, card, ts}` with events such
  as `grab`, `open`, `dock`, `sum` (two-hand squeeze), `jarvis` (J mode). That file is the integration hook:
  `holo_bridge.py` watches it, lights the same note in the Brain and has JARVIS summarize squeezed cards.
- Gestures: pinch to grab/throw, quick pinch to open, flick to dismiss, two pinches to zoom/rotate, two-hand
  stretch to read, squeeze to summarize, peace sign to reset; F = effects, J = narration; `?sim=1` demo,
  `?probe=1` self-test (26/26).
- A separate H.O.L.O. design ([Samer-Smati/jarvis PR #30](https://github.com/Samer-Smati/jarvis/pull/30)) smooths
  landmarks with a One Euro filter (minCutoff 1.0, beta 1.0; beta 0.035 lagged ~33%). The built-in hand control
  in `hud/modes.js` uses the same filter and values.

## Comparable open-source assistants

- [isair/jarvis](https://github.com/isair/jarvis): local voice assistant with a floating face, diary + knowledge-graph
  memory, **redaction** of sensitive data before it reaches the model, **dictation hotkey** (hold to record, release
  to paste), room transcript ("third person in the room"), MCP tools, setup wizard, low-power mode.
  → Dictation adopted (Ctrl+Alt+D). Redaction and room mode are on the backlog.
- [sosoj92/jarvis-assistant-vocal](https://github.com/sosoj92/jarvis-assistant-vocal): wake word → local STT →
  Claude/Ollama, Home Assistant/Hue, OBS, Twilio calls, exposes an MCP server.
- [ishaan1013/jarvis](https://github.com/ishaan1013/jarvis): gesture-controlled 3D hologram with OpenCV +
  MediaPipe + Flask, Web Speech API.
- [Pythonpreran/Aircursor](https://github.com/Pythonpreran/Aircursor) and similar "virtual mouse" projects:
  MediaPipe + PyAutoGUI cursor control with pinch-to-click (pinch distance thresholds, smoothing).
- [dmrr35/Open.Jarvis](https://github.com/dmrr35/Open.Jarvis): Windows-first, local command routing before the LLM
  (this repo does the same for app launches and window commands).

## Free tools commonly used in JARVIS builds

| Tool | Status here | Notes |
| --- | --- | --- |
| MediaPipe (Google) | **Used** (HOLO hand control) | Loaded from jsDelivr `@mediapipe/tasks-vision@1.1.1`; needs internet on first use. |
| faster-whisper | Used | GPU speech recognition. |
| openWakeWord | Used ("hey Jarvis" model) | A custom "Jarvis" model can be trained free in their Colab notebook if false wakes bother you. |
| Kokoro / Piper | Kokoro installed as fallback | Qwen clone is primary. |
| Obsidian | Used | The vault is the second brain. |
| Telegram Bot API | **Built**, needs your bot token | `scripts/setup_telegram.py`. |
| Zapier MCP | **Ready**, needs your token | Gmail/Google/Notion. Free plan has a small monthly task allowance (each tool call uses tasks); check Zapier's pricing. |
| Home Assistant | Not yet | Its official MCP server ([docs](https://www.home-assistant.io/integrations/mcp_server/)) uses OAuth 2.0 + PKCE, which JARVIS's MCP client doesn't implement. Options: add OAuth to `mcp_connections.py`, or use Zapier's Home Assistant actions. |
| Ollama | Not wired | Free offline LLM; would give a backup brain when ChatGPT limits are hit. Needs a provider adapter with tool calling. |
| ntfy / Pushover | Not needed | Telegram already covers phone notifications. |

## Backlog, in priority order

1. **Live test** the new pieces with you (Telegram voice notes, HOLO squeeze-to-summarize, Focus callout tone).
2. **Ollama fallback brain** (`model_provider` adapter) so JARVIS still answers when Codex is rate-limited or offline.
3. **OAuth for MCP** (unlocks Home Assistant, Notion, Canva one-click logins as in the video).
4. **Semantic vault search** (local embeddings) once the vault grows past a few hundred notes; today it's lexical.
5. **Redaction** of secrets/IDs before text reaches the model (isair/jarvis pattern).
6. More proactive behaviour on top of the calendar heads-ups (built): e.g. "you've been in Discord for an hour"
   using the same foreground-app evidence as Focus.
