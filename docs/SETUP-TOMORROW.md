# Setup and acceptance checklist

Updated 2026-10-21. The workday build is installed and was quietly activated after automated
checks. Refresh the Brain page when you return. Start with the acceptance walkthrough when
you are back at the PC; account sign-ins and real hardware behavior remain to be checked.

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

Installed at `C:\Users\Lemab\holo` and configured for the existing vault. The inert browser
probe passes 26/26 gesture checks using synthetic notes. The real camera/hand-tracking test is pending.
The setup command below is now only needed for reinstalling or updating.

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

## 5. OAuth connections (browser sign-in)

In the armory, choose **Add your own tool**, enter the actual MCP endpoint, and choose
**Sign in with OAuth**. Click **Prepare sign-in**, then **Continue to service sign-in**.
Approve access on the service's own website and return to Jarvis. Successful authorization
discovers tools and saves encrypted tokens; it does not execute a tool. Calls retain spoken approvals.

- Supports public clients with PKCE S256, protected-resource metadata, OAuth/OIDC issuer discovery,
  dynamic registration or a pre-registered public client ID, token refresh/rotation, and revocation.
- If the service needs pre-registration, register `http://127.0.0.1:PORT/callback` and enter the same
  port and client ID under OAuth options. Otherwise leave them blank for automatic registration.
- Closing the connection dialog cancels pending sign-in. Requests expire after five minutes.
- Remove an OAuth connection to erase it locally and attempt revocation. The result tells you if
  you must also revoke access on the service's account page.
- This is a bounded implementation, not a promise that every MCP server works. Confidential clients,
  hosted client-ID metadata documents, legacy SSE/stdio transports, cross-origin metadata/endpoints,
  and automatic permission expansion are not supported. Expired/denied authorization may require
  removing and reconnecting. A saved catalog is labelled **configured**, not live-verified.

Reference: [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).
Only fake services have been used for OAuth acceptance; real account authorization remains your step.

## 6. Optional offline conversation model

The local provider uses Ollama. Codex remains selected; Jarvis never silently retries a failed
conversation or action with another provider. Paid API providers remain blocked in subscription-only mode.

The isolated setup script installs a checksum-pinned Windows runtime and local `qwen3:4b` weights
under `data/local-brain`, with no Python package changes, PATH changes, or startup tasks:

This installation is already complete. Local inference and a synthetic tool round trip passed.
Discovery is enabled in `.env`, and the local server is running idle. Codex remains selected.
After a Windows restart, run `start-local-model.bat` when you want the local provider available.
The setup command below is only needed to recreate or verify the installation.

```powershell
.venv\Scripts\python.exe scripts\setup_local_brain.py
```

Start it with `start-local-model.bat` (or `scripts/setup_local_brain.py --serve`). It listens only on
`127.0.0.1:11435`, disables Ollama cloud features, and does not load model weights until requested.
Enable discovery in `.env` with `JARVIS_OLLAMA_ENABLED=1` and
`JARVIS_OLLAMA_URL=http://127.0.0.1:11435`, then restart Jarvis. In the model pill choose
**Ollama / local models**, select `qwen3:4b`, and **Validate and apply**.

The adapter checks for local weights and tool support before sending conversation history.
Cloud models and non-loopback endpoints are rejected. Local tool calls use Jarvis's existing
approval and work-safe dispatcher. A text-only model cannot interpret camera/screen images;
it reports that limitation. Conversation inference is local, but tools you explicitly request
may still use the internet. There is no built-in live web search in the local model provider.
GPU contention with speech and games still needs live acceptance.

Sources: [Ollama chat API](https://docs.ollama.com/api/chat),
[tool calling](https://docs.ollama.com/capabilities/tool-calling),
[local-only configuration](https://docs.ollama.com/faq),
[Qwen3 4B model](https://ollama.com/library/qwen3:4b).

## 7. Repeatable checks without hardware or accounts

```powershell
.venv\Scripts\python.exe scripts\verify_project.py
```

Runs unit tests, the Brain browser fixture, and the optional installed-HOLO gesture probe.
The report is saved to `data/reports/project-verification.json`. Camera, microphone,
external-account calls, and writes to the real HOLO event file are not part of these checks.

## Restarting

- Python changes: say **"Jarvis, power down"**, then open the **JARVIS Brain** shortcut.
- Brain page changes: refresh the page. Brain server changes (`brain.py`): end the `pythonw … brain.py` process in
  Task Manager (Details → Command line), then open the shortcut.
