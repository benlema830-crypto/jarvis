# Setup checklist (one-time, about 30 minutes)

Everything below is optional and independent: do them in any order. JARVIS already runs the new
version (restarted quietly at 03:40 on 2026-10-21), so start with the 5-minute test.

## 0. Five-minute test of what's new

Open the **JARVIS Brain** shortcut, then:

1. **Layout** — graph in the middle, Inspector/Top hubs/Forces on the left, Filter + reactor + EYES/WATCH/HOLO/FOCUS on
   the right, chat dock at the bottom. Click a note: it lights up with its neighbours and the camera centres on it.
   Shift-click another node to see the gold path between them. Right-click a node to read it.
2. **"Jarvis, good morning."** — the full briefing on demand.
3. **"Jarvis, what's the latest news about …?"** — he searches the web live; links appear under *Assistant sources*
   (he never reads URLs aloud).
4. **"Jarvis, add a task: try HOLO."** then **"What's on my list?"** — a `Tasks.md` note appears in your vault and graph.
5. **EYES** → *Turn on* (allow the camera) → **"Jarvis, what do you see?"** → *Turn off*.
6. **FOCUS** → pick an app, 2 minutes, *Start focus*. Switch to another app for ~10 s: JARVIS calls you out.
   Say **"Jarvis, end my focus session"** (or click Stop) when done. (Anything starting with "stop" is treated as an
   instant interrupt, so use "end".)
7. **HOLO** → *Turn on hand control*. Pinch and drag to orbit, quick pinch on a node to select, open palm to fit.
8. **"Jarvis, write a one-page document about …"** — a Word file opens from `Documents\JARVIS Documents`.

If anything misbehaves, *More → Voice health* and `data/brain-assistant.log` say why.

## 1. HOLO (the hand-gesture notes app from the video's creator)

Free, MIT-licensed: [zubair-trabzada/holo-gestures](https://github.com/zubair-trabzada/holo-gestures). It needs Git, Chrome and a webcam.

```powershell
winget install --id Git.Git -e                                   # only if `git --version` fails
cd C:\Users\Lemab\Jarvis
powershell -ExecutionPolicy Bypass -File scripts\setup_holo.ps1   # clones to ~\holo and points it at your vault
```

Then say **"Jarvis, open HOLO"** (or HOLO → *Open HOLO* in the Brain). Allow the camera and raise a hand.

- Pinch a card to grab/throw it, quick pinch to open it, two-hand stretch to read, **squeeze to have JARVIS summarize it**
  in his own voice. Cards you grab also light up in the Brain graph.
- In HOLO, **J** toggles its own narration (browser voice) and **F** extra effects; `?sim=1` plays a demo without a camera.
- "Jarvis, what am I holding?" tells you the last card you picked up. "Jarvis, close HOLO" stops its server.

## 2. Telegram (text or voice-note JARVIS from your phone)

1. In Telegram, message **@BotFather** → `/newbot` → choose a name and a username ending in `bot` → copy the token.
2. Run `.venv\Scripts\python.exe scripts\setup_telegram.py`, paste the token into the masked box.
3. It shows a code: send `/pair 123456` to your new bot within 5 minutes. It replies "Paired".
4. Restart JARVIS ("Jarvis, power down", then open the Brain shortcut).

Now message the bot: text gets a text reply; a voice note gets a text **and** a voice-note reply in your Qwen voice.
"Jarvis, send me that link on Telegram" works from the PC. Only your paired chat is answered; risky actions
still need your spoken "yes" at the PC.

## 3. Gmail, Google Calendar/Drive/Docs/Sheets, Notion… via Zapier MCP

This is how the video's JARVIS reached Gmail and Google Docs. JARVIS's MCP client supports Zapier's token method.

1. Go to [mcp.zapier.com](https://mcp.zapier.com) → **Add MCP server** → choose **Other**.
2. Add the actions you want (e.g. *Gmail: Find Email, Send Email, Create Draft*; *Google Docs: Create Document from Text*;
   *Google Calendar: Find Events*). Connect each app when Zapier asks.
3. Server **Settings → Generate token**, copy it (it's shown once).
4. Brain → tool armory (🔧) → **Zapier MCP +** → the URL is prefilled (`https://mcp.zapier.com/api/v1/connect`);
   paste the token → **Test & connect**.
5. Try "Jarvis, do I have any unread emails from …?" — he asks before every call.

Zapier's free plan has a small monthly task allowance (each MCP tool call uses tasks), so check
[Zapier's pricing](https://zapier.com/pricing) if you'll use it heavily.

## 4. GitHub (optional)

Create a fine-grained personal access token (GitHub → Settings → Developer settings) with read access to the repos
you want, then armory → **GitHub +** → URL is prefilled (`https://api.githubcopilot.com/mcp/`) → paste the token.

## 5. Things that are free and worth considering later

See [RESEARCH.md](RESEARCH.md) for details and links: a custom "Jarvis" wake word (openWakeWord), Ollama as an
offline backup brain, Home Assistant (needs an OAuth-capable connector), and ntfy-style phone notifications.

## Restarting

- Python changes: say **"Jarvis, power down"**, then open the **JARVIS Brain** shortcut.
- Brain page changes: refresh the page. Brain server changes (`brain.py`): end the `pythonw … brain.py` process in
  Task Manager (Details → Command line), then open the shortcut.
