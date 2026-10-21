# J.A.R.V.I.S.

A personal AI assistant for Windows, modelled on the reference video
([I Built JARVIS with GPT-6 Astra](https://www.youtube.com/watch?v=mitzci4FsOg); target and acceptance
checklist in [docs/plans/JARVIS-TARGET.txt](docs/plans/JARVIS-TARGET.txt)). He listens for his name,
answers in your own cloned voice, looks things up, works your PC, keeps your to-dos and documents,
and lives inside a 3D map of your Obsidian second brain.

**Daily setup:** Codex with your ChatGPT sign-in is the brain (no API key, plan limits apply),
your local Qwen voice clone speaks, Whisper on the GPU listens. Nothing paid is used as a fallback.

> Setting up the optional extras (HOLO hand gestures, Telegram, Gmail/Google via Zapier, Home Assistant):
> follow **[docs/SETUP-TOMORROW.md](docs/SETUP-TOMORROW.md)** — each one is a single script or a pasted URL.

## Start

- Double-click the **JARVIS Brain** desktop shortcut (or `.venv\Scripts\python.exe open_brain.py`).
  It starts the assistant if needed and opens the Brain at http://127.0.0.1:7781.
- Or run `run.bat` (voice) / `run.bat --text` (keyboard). Add `--quiet-start` to skip the spoken briefing.
- Say **"Jarvis…"** (or press **Ctrl+Alt+J**) any time, even mid-sentence, to get his attention.
  "Jarvis, stop" / the ■ button / Ctrl+Alt+J stop speech and cancel background work.
  (Anything that *starts* with "stop" is an instant interrupt; say "end my focus session", not "stop …".)

## The Brain

The Brain is the main interface, laid out like the video: the graph fills the screen, with compact
panels around it.

| Area | What it does |
| --- | --- |
| **Graph** | Your vault notes (coloured by top-level folder), real `[[wikilinks]]` as bright edges, plus memories, recent conversations and (off by default) tools. Drag = orbit, right-drag = pan, scroll = zoom, click = focus a node and its neighbours, **shift-click** a second node = trace the path, right-click = read, `/` = search, `F` = fit, Esc = clear. |
| **Left panel** | Vault name and counts, search, **Inspector** (excerpt, read full note, open in Obsidian, ask JARVIS, depth 1–3, neighbours), **Assistant sources** (notes JARVIS just read, web pages he cited), **Top hubs**, **Forces** (repel, link length), **Display** toggles. « collapses it. |
| **Toolbar** | ◎ Fit · 2D/3D · ⟳ auto-orbit · ↻ reload the vault. |
| **Right column** | **Filter** by group, the **reactor** (RING / CUBE / FACE; it pulses with real audio level only), ONLINE pill, model pill (click to switch brains), and the four modes below. |
| **Dock** | Latest reply (click *history* for the conversation), the command bar, and buttons: listening mode (wake word ↔ continuous), stop, ask about screen, activity, tasks & agents, tool armory, more (voice health, model, workspace, next steps, classic HUD). |

### Modes (all off until you switch them on)

| Mode | What happens | Privacy |
| --- | --- | --- |
| **EYES** | Your webcam feeds JARVIS. Ask "what do you see?", "how do I look?". Optional *Coach me*: every 5 minutes he glances over and speaks up only about posture, your phone or tiredness. | Newest frame only, in memory on this PC, expires 12 s after Eyes turn off. Frames go to the AI only when he looks. |
| **WATCH** | Masked desktop preview every 5 s. | Memory only; work apps blacked out; hiding the Brain stops it. JARVIS can also look at your screen any time you ask. |
| **HOLO** | Steer the graph with your hands: pinch-drag orbits, quick pinch selects, two-hand pinch zooms/twists, open palm fits, peace sign clears. Also launches the separate **HOLO** app (grab/throw/read note cards). | Hand tracking runs in the browser (Google MediaPipe); landmarks never leave the page. |
| **FOCUS** | Lock onto one app for 1–120 minutes. Leaving it for 5+ s counts a drift, and JARVIS calls you out with a dry one-liner; he wraps up when time's up. Also by voice: "Start a 30 minute focus session on VS Code." | Foreground app names only, no screenshots. Browser tabs can't be told apart. Keeps running while you work elsewhere. |

You can switch modes by voice too: "Jarvis, turn on your eyes", "turn on hand control".

## What he can do

- **Talk:** wake word "Jarvis", continuous mode, interruptible speech, your cloned Qwen voice, owner voice-lock.
- **Research:** live web search through Codex; sources appear as links in the Brain (never read aloud).
- **Second brain:** search, read and create notes in `Documents\JARVIS Knowledge`; retrieved notes light up in the graph.
- **To-dos:** "add a task…", "what's on my list?", "tick off the invoice" — kept in `Tasks.md` in your vault.
- **Documents:** "write an invoice / proposal / letter…" → a Word file in `Documents\JARVIS Documents`, using details from your notes.
- **Briefing:** spoken at startup, and on demand with "good morning" / "brief me" (calendar, reminders, weather, recent work).
- **Reminders & timers** that survive restarts; **calendar** reads (published Outlook ICS) and Outlook event creation,
  plus a spoken **heads-up 5–10 minutes before each calendar event**.
- **Dictation:** press **Ctrl+Alt+D**, speak, and your words are typed into whatever app has focus (local Whisper, never sent to the AI).
- **PC control without the mouse:** open apps/files/sites, move/snap/minimize/close windows across monitors, per-app volume and mute, media keys, speaker choice, clipboard, personal file list/copy/rename, screenshots.
- **Agents:** named Codex project sessions ("Have Frontier find the next task"), terminal jobs routed to Codex.
- **Tools you connect:** any Streamable HTTP MCP server (Zapier for Gmail/Google Docs/Sheets/Calendar/Notion, GitHub, Home Assistant…). Every external call asks for your spoken OK.
- **OAuth sign-in:** compatible public-client MCP servers can use browser approval, encrypted tokens, automatic refresh, and revocation on removal. Pre-registered client IDs and dynamic registration are supported; service-specific acceptance is still required.
- **Optional local brain:** Ollama models with local weights and tool support can be selected explicitly. Codex remains the daily default; there is no automatic fallback or paid-provider activation. See the [setup guide](docs/SETUP-TOMORROW.md#6-optional-offline-conversation-model).
- **Phone:** Telegram text or voice notes; he replies by text, and with a voice note when you sent one. "Send me that on Telegram" works too.
- **Switch brains** by voice ("switch your brain to …") or the model pill; changes are validated first.
- **Memory:** facts you tell him (`remember`/`forget`) plus the last 20 exchanges, carried across restarts.

## Safety and privacy

- Approvals for risky actions (deleting, installing, settings, external tools, publishing) are checked in code
  and need **your spoken yes** at the PC; Telegram messages can't approve anything.
- Work-safe mode: Teams (and Outlook unless `JARVIS_ALLOW_OUTLOOK=1`) is never opened, read, captured or logged.
- Text from web pages, files, notes, MCP tools and the clipboard is treated as data, never as instructions.
- Credentials (OpenAI key, MCP tokens, Telegram bot token) are encrypted with Windows DPAPI under `data/`,
  which is git-ignored along with `.env`, memories, transcripts and voice data.
- Telegram answers exactly one paired chat; everything else is ignored.

## Configuration

- `.env` (copy `.env.example`): devices, wake/voice-lock thresholds, optional API keys, ports.
- `voice-profile.json`: which voice engine/profile this install uses and its HUD port (7778).
- `data/preferences.json`: listening mode, model, calendar link, Telegram chat (written by the UI/scripts).

## Develop and test

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests     # 200+ inert unit tests
.venv\Scripts\python.exe tests\check_brain_browser.py      # drives the Brain in headless Chrome against a fake backend
.venv\Scripts\python.exe scripts\verify_project.py         # all inert checks, with a local report
```

Source layout and runtime files: [docs/PROJECT-MAP.md](docs/PROJECT-MAP.md). Feature status against the
video: [docs/STATUS.md](docs/STATUS.md). Research notes and ideas: [docs/RESEARCH.md](docs/RESEARCH.md).

After changing Python code, restart JARVIS (say "Jarvis, power down", then open the Brain shortcut).
After changing `hud/` files, just refresh the Brain page; after changing `brain.py`, restart the Brain
companion (end the `pythonw … brain.py` process, then open the shortcut).

## Troubleshooting

- **Brain says OFFLINE:** the assistant isn't running — open the JARVIS Brain shortcut. `data/brain-assistant.log` has its output.
- **He doesn't react to his name:** More → Voice health shows the mic, voice-lock and last recognition result. "Voice not matched" means the voice lock rejected it; re-run `enroll.bat` if your setup changed.
- **"Codex conversation failed":** check the Codex app is signed in with ChatGPT and you're within plan limits.
- **Camera modes say permission denied:** click the camera icon in the address bar and allow it for 127.0.0.1.
- **HOLO hand control says it can't download MediaPipe:** it needs internet the first time (jsDelivr + Google storage).
