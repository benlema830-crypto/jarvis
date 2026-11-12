# What Zubair's older Jarvis videos have that ours doesn't

Checked 2026-11-11 by Claude Opus 5.5. Codex wrote up each of his Claude Code-era Jarvis videos (vault:
`Research/Zubair watch/`); then I checked every suggestion against our code, because the write-ups often said
"if not already supported". The owner's rule: **"we only want to implement things we dont have already,
otherwise its going backwards."** So this list keeps only real gaps. The Fable 5.2 workshop items are in
`ZUBAIR-FABLE-5.2-WORKSHOP.md` and aren't repeated here.

Older no-code (n8n) Jarvis videos from 2024-2025 were skipped: that's an older approach he moved past.
His Shorts were skipped: they're clips of the long videos.

## Real gaps (checked in our code)

| # | Gap | Seen in | What we have now | Effort | Cost |
|---|---|---|---|---|---|
| G1 | **Point at things on screen**: Jarvis draws a marker over the button or field he means ("click here") | "Full Control of My Computer" | `look_at_screen` sees the screen and `do_on_computer` clicks, but nothing draws on screen for you to follow | medium | none (plan usage only) |
| G2 | **Send files over Telegram** (an invoice, a report, a picture) | "Upgraded JARVIS With Jev", "Build Your Own JARVIS" | `send_telegram` sends text only. Voice notes already work both ways (`telegram_bridge.py`) | small | none |
| G3 | **Meeting prep**: before an event, a short brief from the calendar plus vault notes and recent work on that topic | "Build Your Own JARVIS", "Built JARVIS with Claude Code" | `nudges.py` only says "X starts in 8 minutes" | medium | Codex/Claude plan usage only |
| G4 | **Reply in another language**: "Jarvis, answer me in Spanish" sticks until changed. You still speak English, and he speaks and answers (tool results included) in that language | "Now it Can Speak ANY Language" | The brain can write other languages, but the voice is fixed to English: `qwen_fast_worker.py` and `models/qwen-voice/tts_worker.py` pass `language='English'`. Speech-to-text is fixed to English too (`ears.py` `language="en"`), which is fine, because he listens in English as well | medium | none (local voice). Check which languages the Qwen voice model supports, and listen to how the cloned voice sounds in each |
| G5 | **Reverse-engineer a website or app** with REA, an open-source MCP server (https://github.com/morluto/rea, MIT, `npx rea-agents setup`). It inspects a live site or a Windows app and writes an evidence-backed teardown that an agent can build from | "Reverse Engineer ANYTHING", "Stopped Paying for AI APIs" | Not connected. Our MCP armory (`mcp_connections.py`) has Zapier, GitHub, Spotify and Fusion. Node v24.22.1 on this PC meets REA's requirement (24.x >= 24.22.1) | small to connect, medium to add a "teardown" card and save reports to the vault | none (plan usage) |
| G6 | *(optional, lower priority)* **Offline talking brain**: switch Jarvis's conversation to the local Qwen model by voice, for when the internet is down | "Completely Offline", "Stopped Paying for AI APIs" | Local Qwen 3.5 9B is already set up for agents (`agent_models.py` `local`, Ollama on 11435), but the talking brain can only be Claude Code or Codex (`model_provider.PROVIDERS`). Measured 2026-11-04: the 9B model is slower than the cloud brain and claims it did things it didn't (5/5), so it would need the claim gate and a clear "offline" label | large | none (local GPU; it competes with the voice for GPU memory) |

Each of these builds on something we have. None replaces anything. G6 is an extra mode, not a replacement for the cloud brain.

## Not gaps: we already have these (don't rebuild)

- Interrupting him by voice (`ears.py`/`jarvis.py` barge-in), wake word, personality/response style (`response_style`)
- Graph that lights the notes used in an answer (`knowledge_events.py` → `hud/brain.js`), graph filters, depth, focus
- Ring / cube / face looks for the reactor (`hud/brain.js` "Reactor: sphere / ring / cube / face")
- HOLO hand gestures: ours runs his own repo, and our clone is up to date with his latest commit
- Telegram voice notes in and out; Gmail read, draft and send (`gmail.py`)
- Tool armory and custom connections: MCP with Zapier, GitHub, Spotify, Fusion already connected
- Model switching; screen agent with stop controls; research; away jobs; parallel agents (ours goes further than his)
- Translating what's on screen: `look_at_screen` plus the brain already does it on request
- Local cloned voice and switching voices by voice (`switch_voice`, VoiceStudio/Qwen). His "offline" videos add this; ours had it first

## Left out on purpose

- **Camera "Eyes", screen "Watch" mode and "Focus lock" with a distraction count.** These were in our Jarvis and the
  owner had them **deleted** in the 2026-11-10 makeover. Bringing them back would undo that decision. Only if the owner asks.
- **Real phone calls** (he calls the owner or businesses). Needs a paid phone service. The owner chose "skip calls
  for now" on 2026-10-29. Only if the owner asks.
- **Jev router** (a model that sorts requests before the main brain). His own write-up shows no gain, and we already
  measured that routing to smaller models doesn't speed ours up.
- **Invoice workflow, Canva, Google Docs**: possible through the Zapier MCP that's already connected, if the owner
  ever wants them. Not code to write.
- **OpenAI Realtime voice mode**: a paid API, and the owner likes the current voice.

## How the last four were written up

YouTube refused transcript downloads after 12 in a row (`IpBlocked`), so on 2026-11-11 the audio of "Completely
Offline", "Stopped Paying for AI APIs", "Speak ANY Language" and "Reverse Engineer ANYTHING" was downloaded and
transcribed on this PC with Jarvis's own Whisper (large-v3-turbo on the GPU, about 15 s per video), then written up
by Codex the same way as the others.
