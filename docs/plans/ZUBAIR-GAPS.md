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
| G1 | **Point at things on screen**: Jarvis draws a marker over the button or field he means ("click here") | "Full Control of My Computer" | `look_at_screen` sees the screen and `do_on_computer` clicks, but nothing draws on screen for you to follow | medium | none (the plan he's already on) |
| G2 | **Send files over Telegram** (an invoice, a report, a picture) | "Upgraded JARVIS With Jev", "Build Your Own JARVIS" | `send_telegram` sends text only. Voice notes already work both ways (`telegram_bridge.py`) | small | none |
| G3 | **Meeting prep**: before an event, a short brief from the calendar plus vault notes and recent work on that topic | "Build Your Own JARVIS", "Built JARVIS with Claude Code" | `nudges.py` only says "X starts in 8 minutes" | medium | Codex/Claude plan usage only |

Each of these builds on something we have. None replaces anything.

## Not gaps: we already have these (don't rebuild)

- Interrupting him by voice (`ears.py`/`jarvis.py` barge-in), wake word, personality/response style (`response_style`)
- Graph that lights the notes used in an answer (`knowledge_events.py` → `hud/brain.js`), graph filters, depth, focus
- Ring / cube / face looks for the reactor (`hud/brain.js` "Reactor: sphere / ring / cube / face")
- HOLO hand gestures: ours runs his own repo, and our clone is up to date with his latest commit
- Telegram voice notes in and out; Gmail read, draft and send (`gmail.py`)
- Tool armory and custom connections: MCP with Zapier, GitHub, Spotify, Fusion already connected
- Model switching; screen agent with stop controls; research; away jobs; parallel agents (ours goes further than his)

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

## Still being written up

YouTube refused transcript downloads after 12 in a row (`IpBlocked`), so four write-ups are retrying every 15 minutes:
"I Built JARVIS to Work Completely Offline", "I Stopped Paying for AI APIs… and Built This Jarvis Instead",
"Now it Can Speak ANY Language" and "I Gave My AI Assistant the Power to Reverse Engineer ANYTHING". Add any real
gap they show to the table above. A likely one, from the title: **speaking languages other than English**. Ours is
fixed to English (`ears.py` passes `language="en"` to Whisper).
