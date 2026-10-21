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

## 8. Project memory, semantic search, and named routines

Brain **More > Project tools** contains all three. Voice examples:

- "Where did we leave Rocket Frontier?"
- "Save a Jarvis handoff: completed …, unresolved …, next action …"
- "Search my notes for keeping player progress between visits."
- "Review Development mode" or "Run Wrap up."

Project recall reads the selected project's Git state, maintained handoff/validation files,
and saved agent reports. Git evidence verifies repository state only; reports and notes are
attributed claims, not new test runs. Rocket Frontier's `fresh/` handoff and validation take
precedence over its archived game. Saved handoffs live in `data/handoffs/`, with dates,
sources, previous-entry IDs and separate progress/problems/next-action/file fields.
Project folders are never modified by saving a handoff. Old agent reports without timestamps
remain undated; newly completed reports include `reported_at`.

Semantic search uses local `embeddinggemma:300m` on the isolated Ollama server at
`127.0.0.1:11435`. The model is installed on this PC. To restore it after reinstalling Ollama:

```powershell
$env:OLLAMA_HOST='127.0.0.1:11435'
.\data\local-brain\runtime\ollama.exe pull embeddinggemma:300m
```

Start the local server with `start-local-model.bat` first. Search uses only validated Markdown
notes in the configured Obsidian vault; it does not index arbitrary project files or accounts.
An incremental SQLite index lives in `data/vault-vectors.sqlite3`. Edits, deletions, vault-root
changes and model-digest changes invalidate cached chunks. Embeddings unload after each batch
to reduce idle GPU use. Cold requests can take tens of seconds. Scores below 0.30 are excluded;
scores indicate similarity, not truth. Search falls back to labeled keyword results if the
local model is unavailable or disabled (`JARVIS_OLLAMA_ENABLED=0`). No remote embedding fallback.

The supplied **Development mode** opens Rocket Frontier's folder, reads its status and the
vault task list, then starts 30 minutes of Focus on `RobloxStudioBeta.exe`. It does not launch
Studio. **Wrap up** reads status/tasks and saves an evidence snapshot and checklist. Vault tasks
are labeled as all-project tasks. Edit the project, steps, app and duration before saving.
Change the name to create another routine. Saving and reviewing never execute steps.

Every run requires a fresh review and explicit approval. Review tokens expire after five minutes,
are consumed once, and are revoked when routines change. Voice runs use the existing spoken
approval channel. Execution stops on the first failed step; completed effects are shown and not
automatically undone. Stop routine prevents subsequent steps; the main Stop control also ends
Focus. Only the listed local actions are supported, with no arbitrary commands, publication,
messages or automatic agent work. Nothing runs on a schedule or at startup.

Embedding API references: [Ollama embeddings](https://github.com/ollama/ollama/blob/main/docs/capabilities/embeddings.mdx)
and [EmbeddingGemma](https://ollama.com/library/embeddinggemma).

## 9. Scheduled research and progress digests

Use **More > Scheduled digests**. Create a named daily schedule, choose its time and timezone,
and explicitly enable it. No schedules are enabled by this build. Default settings are
America/Chicago, quiet hours 22:00–08:00, and at most two runs per local day (configurable 1–4).

- **Progress** reads saved Jarvis agent reports plus current Git evidence; it uses no AI call.
  Reports retain dates when available and distinguish agent claims from repository evidence.
- **Research** uses the selected, signed-in Codex subscription with live web search. It has no
  dynamic action tools, shell, edits or subagents. Each attempt is limited to one model turn,
  four search operations and 180 seconds. There is no paid-provider fallback. Subscription
  limits still apply. Reports include source links corroborated by search events; generated
  prose and additional inline links still need normal source review. Blocked sites or missing
  dates can limit freshness; the report must say so rather than present older results as new.

Brain and the PC must be running. A 30-second poll checks schedules. Quiet hours defer automatic
work; missed previous days are skipped, and today's due job may run on startup. A run is reserved
on disk before work starts, so failures/crashes count toward the cap and do not automatically retry
that day. Restarted in-flight attempts become interrupted. Run now is explicit, bypasses quiet hours,
and still counts toward the daily cap. Only one digest runs at a time. Reports are silent: no speech,
email, Telegram messages or external publication. Schedules and the last 200 attempt records live
in `data/digests.json`; report files remain in `data/digests/` after a schedule is deleted.

Voice: "List my digest schedules", "Schedule a Jarvis progress digest at 6 PM daily", or
"Run my Roblox development digest now". Choose your own timing before enabling research.

## 10. Memory viewer and text redaction

Use **More > Memory & privacy** to inspect/correct/delete facts, inspect or clear recent dialogue,
and select private phrases, email addresses or phone numbers for filtering. Recognizable API keys,
bearer/JWT/service tokens, credential assignments, private keys and SSNs are filtered by default.
Exact private phrases are stored locally in `data/privacy.json` so they can be matched.

Redaction covers Jarvis-owned conversational text requests for Codex, OpenAI, Claude and Ollama,
tool-result text sent through those adapters, local embedding inputs, and new facts/dialogue/handoffs.
Initial prompts passed to coding workers are filtered too. Authentication headers and binary images
are not rewritten. A memory correction/deletion or privacy change resets model context on the next
turn and excludes pre-change dialogue from future prompts; older excerpts remain inspectable until
cleared. Existing provider-side history is not erased. Memory edits have stale-version checks and a
cross-process file lock. Saving privacy filters scrubs stored facts and recent dialogue.

This is best-effort text filtering, not a complete data-loss-prevention system. It does not inspect
screenshots, speech/audio, arbitrary files read directly by external coding workers, all existing logs,
past handoffs, exports, backups or provider-retained data. Existing work-app screen masking remains
in place. Clear unwanted excerpts separately and review source material before requesting access.

## 11. Spreadsheet, PDF and presentation tools

Use **More > File tools**, or ask Jarvis to create a budget/tracker (`.xlsx`), report (`.pdf`), or
slide deck (`.pptx`) from your data. Outputs go to `Documents/JARVIS Documents` and do not open or
send automatically. The panel's starter budget is explicitly fictional sample data. Generated files
get unique names and existing files are not overwritten. The Open control opens only generated files.

- Spreadsheets: up to 20 columns and 2,000 rows, styled headers, filters, frozen header, numeric totals,
  and editable bar/line charts. Input strings stay literal; only generated SUM totals become formulas.
  Excel/LibreOffice calculates those formulas when opened; returned totals are also computed locally.
- PDF: flowing text/headings, wrapping tables (up to 8 columns/500 rows), page numbers and vector charts.
  Arial is embedded on Windows for normal Unicode text. Full emoji/CJK font coverage is not guaranteed.
- PowerPoint: editable text and charts, up to 40 supplied slides; long body text is split into continuation
  slides. Charts use the first column as categories and the second as numeric values, up to 40 categories.
  These are creation tools, not full Office editing/round-trip or PDF-import tools. Existing Word creation remains.

Installed local libraries: openpyxl, python-pptx and ReportLab; pypdf verifies PDF text in tests. No Office
account is required. Reopening verifies file structure, values/formulas, charts and extracted PDF text;
visual PDF inspection is separate from owner acceptance in Excel/PowerPoint. Sample outputs are in the
generated-file list; verification paths are recorded in `data/reports/artifact-smoke.json`.

Library references: [openpyxl charts](https://openpyxl.readthedocs.io/en/stable/charts/bar.html),
[python-pptx](https://python-pptx.readthedocs.io/en/latest/user/quickstart.html),
[ReportLab Platypus](https://docs.reportlab.com/reportlab/userguide/ch5_platypus/).

## 12. Response settings

**More > Response settings** saves humor (0–100), honesty/directness (tactful to blunt),
explanation detail, classic/friendly/professional tone, disagreement firmness and frequency of "sir".
Honesty itself cannot be reduced: uncertainty, evidence and truthful action reports remain required.
Serious situations override humor, and simple action confirmations stay short. These are model
instructions, not guarantees of an exact joke frequency. Settings apply on the next turn and survive
restarts; changing style refreshes provider context while retaining recent in-session dialogue.

Voice examples: "Set humor to 80 percent", "Be more direct", "Give detailed explanations",
or "Stop calling me sir". Defaults are humor 25, directness 75, brief, classic, balanced pushback,
and occasional sir. Preferences live in `data/response-settings.json`, separate from personal memory.
All previously reviewed features are retained. The Classic HUD menu option has been removed.

## Restarting

- Python changes: say **"Jarvis, power down"**, then open the **JARVIS Brain** shortcut.
- Brain page changes: refresh the page. Brain server changes (`brain.py`): end the `pythonw … brain.py` process in
  Task Manager (Details → Command line), then open the shortcut.
