# Jarvis makeover plan

Written 2026-11-10. Phases 1 to 3 of `MAKEOVER-PROMPT.md`. Nothing has been built or changed. This waits for your approval.

## The short version

1. **Jarvis is slow where you feel it, and the cause is not the model.** A spoken request takes about 4.6 seconds to the first word when no tool is needed and about 8 seconds when one is. Roughly 2.5 seconds of that is fixed waiting that has nothing to do with thinking: he waits 1.2 seconds of silence before deciding you've finished, and he builds each whole sentence of audio (about 1.3 seconds) before playing any of it.
2. **His honesty check has a hole.** It only catches sentences shaped like "I've turned it on", and it lets them through whenever any tool at all succeeded that turn. It has never recorded a single catch. "The TV is on" would still pass today.
3. **You don't use the Brain page.** In the last 7 days it was never the window in front. The terminal was in front 69% of the time. The graph it's built around is 88% Jarvis's own reports.
4. **Two code paths can spend API money.** The screen agent (`do_on_computer`, used 43 times) runs on your Anthropic API key, and "subscription only" is off, so a Claude plan limit falls back to API credits.
5. **A lot is unused.** 29 of 85 tools have never been called. 129 memory proposals are waiting and 1 was ever approved. Several voice engines, brain providers and whole modes have no real use.

**Recommendation:** one talking brain (Claude on your plan), a streaming local voice loop, proof attached to every action he reports, a keyboard-and-voice Console in place of the graph, one memory in place of five, and about 40% less code. No new monthly cost.

---

## 1. Audit

### How I measured

- Read `data/turn_metrics.jsonl` (504 timed turns, Oct 28 to Nov 10), 21 days of `data/transcripts/`, `data/brain-assistant.log` (7,822 lines), `data/ears.log`, `data/activity.jsonl`, `data/task_effort.jsonl` and `data/project_log.jsonl`.
- Queried the running Jarvis (`/status`, `/voice-health`), Home Assistant and Tailscale.
- Ran the full test suite: **799 tests pass in 83 seconds.**
- Timed a bare terminal answer (`claude -p`, one-word reply) six times as the baseline to beat.

I did not make Jarvis speak or run live voice tests, since that would have talked through your Bose speaker. Two numbers below are therefore assembled from separately logged stages, and I say so where it applies.

### What you feel

| Measure | Today | Evidence |
| --- | --- | --- |
| Spoken request to first spoken word, no tool | **about 4.6 s** (estimate) | 1.2 s end-of-speech wait (`ears.py` `END_SILENCE`) + 0.14 s transcription + 2.0 s brain + 1.3 s audio build. Stages logged separately; no single end-to-end timer is saved. |
| Spoken request to first spoken word, with a tool | **about 8.3 s** (estimate) | Same, with 5.7 s brain. He says nothing until the tools finish. |
| Typed message to first sentence, no tool | **median 2.0 s**, slowest tenth 4.4 s+ | 426 turns in transcripts |
| Typed message to first sentence, with a tool | **median 5.7 s**, slowest tenth 13.0 s+ | 344 turns (45% of all turns use a tool) |
| Turns answered in under 1 second | **0 of 42** in the last 3 days | `turn_metrics.jsonl` |
| Bare terminal baseline | **3.1 to 3.5 s** total | `claude -p` on Haiku, Sonnet and Opus. Model choice changed it by under 0.4 s. |
| Interruptions | **19% of voice turns** are cut off (94 of 502) | assistant log. Stopping works. I did not measure how fast he stops; that needs a live test with you. |
| Background agent success | Codex 61 of 68 (90%), median 5 min, slowest tenth 25 min+. Screen agent 31 of 32, median 99 s | `task_effort.jsonl` |
| Direct tool failures | **Not measurable.** Tool results and errors are not logged anywhere. | `tools.run_tool` |
| Unverified claims | **Not measurable.** The only detector is the gate's own pattern, which found 2 suspect turns in 502. That number says more about the detector than about Jarvis. | `truth_guard.py`; `data/claim_checks.jsonl` does not exist |
| Approval prompts | **about 600 in 21 days**, 304 of them "Delete it?" | transcripts. You set auto-approve to "routine" partway through. |

Against the terminal, Jarvis is already about level on simple typed questions (2.0 s against 3.1 s). He loses on voice, on anything that needs a tool, and on the slow tail.

### Subsystem table

| Subsystem | Status | Quality against best practice | Verdict |
| --- | --- | --- | --- |
| **Main loop** (`jarvis.py`, 1,434 lines) | Works. Up since Nov 9, 82 turns in 7 days. | One file holds five different brain paths, the prompt, startup and every channel. | **Replace** with a small core. One brain path. |
| **Brain: Claude via Claude Code** | Works. 438 of 504 turns. | Right choice, wrongly loaded: all 85 tools (about 13,000 tokens) and a 3,400-token prompt go in every session. | **Keep, slim down.** Core tools up front, the rest found on demand. |
| **Brain: Codex conversation** | Works, 25 turns, not used since you switched. | Second personality. | **Delete** as a talking brain. Keep Codex as a worker. |
| **Brain: Anthropic API, OpenAI API** | API path last used Oct 26. OpenAI never appears in the metrics. | Paid. Against your money rule. | **Delete.** |
| **Brain: local Ollama + quick router** | Turned off Nov 4. 41 turns: slower (median 4.0 s) and it claimed actions it hadn't checked. | Worse than the cloud brain on your own numbers. | **Delete.** Keep Ollama only for vault search. |
| **Hearing** (`ears.py`) | Works. Transcription median 0.14 s. | Transcription is excellent. End-of-speech uses a fixed 1.2 s silence; current practice is a small model that knows when a sentence is finished. | **Improve.** Keep Whisper, replace the silence timer. |
| **Voice lock** | Works. 43 rejections scored 0.65 to 0.74, just under the 0.74 cut-off, which were probably you. | Fine. | **Keep,** tune the threshold. |
| **Voice: VoiceStudio clone** | Works. 1,767 sentences, median 1.2 s each. Needed 12 restarts; goes "half dead". | Good sound. Not streamed, and depends on a separate desktop app staying alive. | **Replace** with a streaming voice engine run by Jarvis himself, same cloned voice. |
| **Voice: Qwen clone** | Works. 598 sentences, slower tail (up to 49 s). | Older non-streaming build. | **Replace** (same change as above). |
| **Voice: ElevenLabs** | **Broken.** Authentication error in the log. Paid. | n/a | **Delete.** |
| **Voice: Piper** | Unused. | n/a | **Delete.** |
| **Voice: Kokoro** | Works as the fallback. | Still the standard fast fallback. | **Keep.** |
| **Honesty** (`truth_guard.py`) | Partly works. Agent outcome lines and the Home Assistant read-back work. The claim gate has never logged a catch. | Pattern matching on wording. Current practice is proof from the tool, checked by something other than the model that did the work. | **Replace** the gate. Keep read-backs and outcome lines. |
| **Direct terminal tools** | Works, lightly used (run_command 11, read_file 4, edit_file 0). | Right idea. Guarded by keywords, not a sandbox. | **Keep and make it the main way of working.** |
| **Agent sessions** (Codex) | Works. 65 dispatches, 90% success. | Solid. Slow by nature. | **Keep** for long jobs. |
| **Screen agent** (`agent.py`) | Works, 43 uses, median 99 s. **Runs on the paid API.** | Slow and paid. Browser control through your Claude plan now does the same job. | **Replace.** |
| **Away jobs** | Works. 2 jobs, both finished. Re-runs tests itself. | Matches best practice (separate check, sandbox, branch not merge). | **Keep.** Build on it. |
| **Memory: saved facts** | Works. 26 facts. | Thin for something that should know you for years. | **Merge** into one memory. |
| **Memory: proposals you approve** | **Not working as a system.** 129 waiting, 1 approved, 2 rejected. | A queue nobody clears. | **Delete.** Replace with automatic saving plus a short weekly review. |
| **Memory: working memory, project memory, handoffs, journal, briefs, recent conversation, chat history** | Each works. Seven stores for one job. | Overlapping. | **Merge.** |
| **Vault search** | Works (index ready in 6 s; 9 searches in 3 weeks). | Fine. | **Keep.** |
| **Vault contents** | 153 notes, 135 written by Jarvis (103 reports, 18 journal, 14 briefs). | Your second brain is mostly his logs. | **Move** reports out of the vault into a searchable history. |
| **Brain page + graph** (`brain.py`, `hud/`, 4,629 lines) | Works. In front 3% of the last 30 days and 0% of the last 7. | A graph of 153 notes is not a control surface. | **Replace** with the Console. |
| **Classic HUD page** | Removed from the menu, still served. | n/a | **Delete** the page, keep the event stream. |
| **Desktop orb** | Works. No use recorded. | n/a | **Fold** into the Console as a small status pill. |
| **Holo, Eyes, Watch, Focus** | Built. 1 holo call, 1 camera call, 0 focus, 0 mode switches in 3 weeks. | n/a | **Delete.** Screen look-ups (`look_at_screen`, 33 uses) stay. |
| **Digests, routines, documents, artifacts, YouTube, Amazon cart** | Built, 0 or 1 uses each. No routines file was ever created. | n/a | **Delete.** Each can come back as a skill if you ask for it. |
| **Home Assistant** | Works. Live check returned all devices. 35 controls, 16 status reads. Reads back after acting. | Good. | **Keep.** |
| **Morning alarm, presence greeting** | Work. Alarm ran today at 6:40. 83 "welcome back" greetings in 21 days. | Works, but nothing limits how often he speaks up. | **Keep,** put under one "should I interrupt?" rule. |
| **Telegram** | Works. 17 messages. | Good phone channel. | **Keep.** |
| **Phone bridge** (Tailscale, 7782) | Works. 43 messages, 12 refused for bad key or address. | Good. | **Keep,** point it at the new Console. |
| **Gmail** | Set up. Never called. | n/a | **Keep** (small, and needed for away work later). |
| **Calendar, reminders, tasks** | Work. 1 to 2 uses each. | Fine. | **Keep.** |
| **Spotify** | Works. Morning music started 6 times. | Fine. | **Keep.** |
| **MCP connections** | Work. 4 saved (Zapier, GitHub, Spotify, Fusion), 7 calls. | Own client code duplicates what the Claude runtime already does. | **Replace** own client with the built-in one. |
| **Performance records** | Partly. Brain time is saved. Voice stage times live only in memory and vanish on restart. | Can't see what you feel. | **Improve** first, before anything else. |
| **Tests** | 799 pass. One data file (`spotify-mcp.enc`) changed during the run; I could not tell whether a test or the live Spotify bridge did it. | Good coverage, slight risk to real data. | **Keep,** isolate from `data/`. |

---

## 2. Gap list

Ranked by how much each would change your day.

| # | Gap | What the best are doing | Why it matters to you |
| --- | --- | --- | --- |
| 1 | **Voice feels slow** | Streaming at every stage, with a small end-of-turn model (Pipecat Smart Turn v3: 8 MB, about 12 ms on CPU) in place of a silence timer. Published budgets are under 1 second end to end. Streaming local voices (Qwen3-TTS, CosyVoice, Chatterbox Turbo) start audio in 100 to 200 ms. | Removes about 2.5 s from every spoken turn. |
| 2 | **Silence while tools run** | Speak or show progress the moment work starts. | 45% of your turns wait a median 5.7 s in silence. |
| 3 | **Claims without proof** | A separate, read-only check that looks at the real state and gates the word "done", with three answers: confirmed, failed, unknown. Google and HKU's VeriCUA (Nov 2026) rejected about 80% of false "done" claims this way. | Your number-one complaint. |
| 4 | **Not a terminal replacement** | Coding agents show the command, the diff, and an undo. | You spend 69% of your screen time in a terminal next to Jarvis instead of in him. |
| 5 | **Every tool loaded all the time** | Tool search: only names load, full definitions on demand. Now the default in Claude Code. | Faster, cheaper turns and better tool choice. |
| 6 | **Memory that doesn't grow** | OpenClaw and Hermes Agent keep plain Markdown memory the agent edits itself, tidied in a scheduled pass. Letta's research finds plain files competitive with specialised memory products. Vendor benchmark scores contradict each other (Mem0 reports 92 to 94 for itself; an outside test gave it 49). | 26 facts after a month, and a queue of 129 you'll never clear. |
| 7 | **No learning from finished work** | Hermes Agent writes a reusable skill after solving something, behind an approval gate. | Repeated jobs stay as slow as the first time. |
| 8 | **Unlimited interruptions** | A daily interruption budget and three choices per event: say it now, hold it for the summary, or stay silent. | 83 greetings and about 600 approval prompts in 3 weeks. |
| 9 | **No regular self-wake** | OpenClaw's heartbeat: wake every 30 minutes, read a short checklist, act only if something is due. | The base for useful away work. |
| 10 | **Phone is text-only** | Same feed on every surface; cards for decisions. Agent-drawn interface standards exist now (MCP Apps, Jan 2026; Google A2UI 0.9, Apr 2026). | Approvals wait at the PC today. |

Things others have that I'm **not** recommending:

- **Speech-to-speech models** (OpenAI Realtime, Gemini Live). They're the fastest, under 500 ms. They're also paid by the minute (about $0.05 to $0.11 a minute on OpenAI), would be a second personality, and would take your tools away from Claude. A streaming version of what you have gets under 1.5 seconds for free.
- **A hosted memory service** (Mem0, Zep). No trustworthy evidence they beat good files for one person.
- **A local talking model.** Your own numbers say it was slower and less honest.
- **Moving to OpenClaw or Hermes.** Jarvis already has the hard parts they lack on your setup (your voice, Home Assistant, Windows control). Take their ideas, not their code.

---

## 3. Target architecture

### What the new Jarvis is

One always-on program with four parts, and workers it hands long jobs to.

```
   You                                                            
    │  voice · Console · `j` in a terminal · phone · Telegram      
    ▼                                                             
┌─────────────────────────────────────────────────────────────┐   
│  FRONT DOOR   one feed of events, same on every surface      │   
└───────┬─────────────────────────────────────────────────────┘   
        ▼                                                         
┌───────────────┐   ┌──────────────────────────────────────────┐  
│  VOICE LOOP   │   │  BRAIN  (Claude, your plan, one persona)  │  
│  local, GPU   │◄─►│  ~20 core tools, others found on demand   │  
│  wake word    │   │  talks first, works second                │  
│  turn model   │   └───────┬───────────────────┬──────────────┘  
│  Whisper      │           ▼                   ▼                 
│  streaming    │   ┌──────────────┐    ┌────────────────────┐    
│  cloned voice │   │  HANDS        │    │  WORKERS            │   
└───────────────┘   │  shell, files │    │  Claude: live jobs  │   
                    │  home, apps   │    │  Codex sandbox:     │   
                    │  browser, MCP │    │  away jobs          │   
                    └──────┬───────┘    └─────────┬──────────┘    
                           ▼                      ▼               
                    ┌─────────────────────────────────────────┐   
                    │  PROOF   every action returns a receipt: │   
                    │  asked · seen · confirmed/failed/unknown │   
                    │  a separate checker gates "done"         │   
                    └──────────────────┬──────────────────────┘   
                                       ▼                          
                    ┌─────────────────────────────────────────┐   
                    │  MEMORY  one store: Markdown you can     │   
                    │  read in the vault + searchable history  │   
                    └─────────────────────────────────────────┘   
        ▲                                                         
┌───────┴───────┐                                                 
│  HEARTBEAT    │  every 30 min: anything due? say, hold, or skip 
└───────────────┘                                                 
```

**The five rules it's built on**

1. **One voice.** Claude does all the talking, on every surface. Workers report to him and he restates it. That fixes the changing personality.
2. **Talk first.** If a turn needs a tool and the tool hasn't returned within a second, he says a few words ("Checking the build.") and then gives the result.
3. **No receipt, no claim.** He can only say a thing happened if a receipt this turn says "confirmed". "Sent but not confirmed" and "unknown" are said as exactly that. The reply is checked against receipts before it's spoken, and the check doesn't depend on how he worded it.
4. **Small jobs by hand, big jobs by worker.** Anything a few commands can settle, he does himself in the conversation and shows the output. Workers are for jobs over a couple of minutes.
5. **No paid path.** No API key is loaded at all. If your plan limit is hit, he says so and stops.

### What gets cut

| Cut | Lines (approx.) | Evidence |
| --- | --- | --- |
| Brain page, graph, classic HUD, orb, holo, modes (`brain.py`, `hud.py` pages, `hud/`, `desktop_orb.py`, `graph_organization.py`, `holo_*`, `eyes.py`, `visual_modes.py`, `orbit.py`, `workspace.py`) | 6,300 | 0 foreground use in 7 days; 1 to 2 calls |
| Extra brains (`ollama_brain.py`, `router.py`, OpenAI and Anthropic API paths in `jarvis.py` and `model_provider.py`, `model_credentials.py`, key setup scripts) | 1,100 | Off, unused, or paid |
| Extra voices (`elevenlabs_voice.py`, `piper_voice.py`, both Qwen files, `voicestudio_voice.py` once the new engine is in) | 650 | Broken, unused, or replaced |
| Screen agent (`agent.py`) | 450 | Paid API; replaced by browser control on your plan |
| Unused features (`digests.py`, `artifacts.py`, `documents.py`, `routines.py`, `youtube_history.py`, `memory_proposals.py`, Amazon cart and YouTube tools) | 1,250 | 0 or 1 uses |
| Own MCP client and OAuth (`mcp_connections.py`, `mcp_oauth.py`) | 660 | The Claude runtime does this |
| Loose files: three `.wav` samples in the repo root, old preview images and scripts in `data/`, `clip-farm/` (moves to its own folder; it isn't Jarvis) | n/a | Not code |

About 10,400 of 24,500 lines go, before the rewrite of what stays. Target: **under 13,000 lines** including the new Console.

### What gets merged

- **Three programs become one.** `jarvis.py` and `brain.py` merge; ports 7778 and 7782 stay, 7781 goes. VoiceStudio stops being needed for speech (you can keep the app for making voices).
- **Seven memory stores become one.** See Phase 5.
- **Three ways to start an agent become one** (`terminal_task`, `send_agent_task`, `queue_away_job` become "hand this off", with "while I'm away" as an option).
- **85 tools become about 20 core tools plus a searchable shelf.**

### Local or cloud

| Job | Where | Why |
| --- | --- | --- |
| Wake word, end-of-turn, transcription, voice lock | Local GPU | Already 0.14 s. Private. |
| Speech | Local GPU | Your cloned voice, streaming. Free. About 4 to 6 GB of your 16 GB. |
| Vault and history search | Local | Works today. |
| All thinking and talking | Claude on your plan | Your numbers: the local model was slower and overclaimed. |
| Long builds | Codex in its sandbox, on your ChatGPT sign-in | Proven for unattended work on this PC. |

---

## 4. UI direction

Open both files in a browser:

- **A. Console:** `docs/plans/makeover-mockups/console.html`
- **B. Ambient:** `docs/plans/makeover-mockups/ambient.html`

| | A. Console | B. Ambient |
| --- | --- | --- |
| Idea | A terminal that talks. One stream of what you asked and what he did, with proof chips, diffs you can undo, and a side rail of running work, things waiting on you, and the house. | A nearly empty screen. Cards appear only when something happens or needs you. Everything else is voice. |
| Best at | Doing work. Replacing the terminal. | Glancing. Coming back after being away. The phone. |
| Weak at | Not pretty from across the room. | Real work: no place for output, diffs or history. |
| Fits your use | Yes. 69% of your time is in a terminal. | Partly. Fits the phone and the "welcome back" moment. |

**Recommendation: build A, the Console.** It's the only one of the two that can meet "I'd choose it over opening a terminal". Take two things from B: its card feed becomes the phone page, and its "while you were out" summary becomes what the Console shows when you return.

The Console also comes with `j`, a one-letter command for the terminal you already have open. `j is the fan on` prints the answer right there, from the same running Jarvis.

The graph is dropped. Obsidian already draws one for your vault.

---

## 5. Build order

Everything happens on a `makeover` branch. After every phase, voice, wake word, Telegram, phone and Home Assistant are checked live before moving on, and the old path stays until the new one has passed. I re-run the measurements and show before and after.

### Phase 0: See clearly and stop the leaks

- Save every stage of every turn to disk: end of speech, transcript ready, first text, first audio, done, tools used, tool results and errors.
- Build a 50-case honesty test from your real transcripts (including the TV case) that can be replayed without touching devices.
- Turn on "subscription only" and take the API keys out of what Jarvis loads. Screen agent replies "not available" until Phase 3.
- Make tests unable to write to the real `data/` folder.

**Done when:** one command prints all the numbers in the "What you feel" table from saved data. A test proves no code path can reach a paid API. `data/` is byte-identical before and after a test run.

### Phase 1: Fast voice

- Replace the 1.2 s silence wait with an end-of-turn model (Smart Turn v3, local).
- Replace sentence-at-a-time audio with a streaming voice engine using your existing voice sample. I'll test Qwen3-TTS streaming and Chatterbox Turbo on your GPU and keep the faster one that sounds right to you. Kokoro stays as fallback.
- "Talk first" for tool turns.
- Load about 20 core tools; the rest found on demand.
- Compare Haiku, Sonnet and Opus as the talking brain on 30 of your real requests, scored on speed and on the honesty test. Use the fastest one that passes.
- Duck his voice the instant your voice is detected, not after the transcript.

**Done when:** spoken request to first audio is **median 1.5 s or less, slowest tenth 3 s or less** with no tool (today about 4.6 s). With a tool, first words within 1.5 s and the result at a median of 4 s or less (today about 8.3 s). Typed first text on screen at a median of 1.0 s or less. If the plan-based connection can't reach these, I report the real numbers rather than add a paid path.

### Phase 2: Honest by construction

- Every tool that changes something returns a receipt: what was asked, what was seen afterwards, and confirmed, failed or unknown.
- Replies are checked against the turn's receipts before speaking. The wording-based gate is deleted.
- A separate read-only checker confirms worker results (tests re-run, file exists, device state) before "done" is said.
- A nightly self-audit of the day's turns writes the count of unbacked claims to the scorecard.

**Done when:** 0 unbacked action claims on the 50-case test, and 0 in the nightly audit for 7 days running. The TV case says "I can't confirm the TV" every time.

### Phase 3: One brain, smaller core

- Delete the extra brains, extra voices, and the unused features listed above.
- Browser control on your Claude plan replaces the paid screen agent.
- Built-in MCP replaces the home-made client. Your four connections are carried over and each one tested.
- Same persona prompt on PC, phone and Telegram. (FRIDAY on the phone stays, since you set that up.)

**Done when:** under 13,000 lines. All remaining tests pass. A 20-question style check gives the same character on all three surfaces. Each of the four MCP connections completes one real read-only call.

### Phase 4: Console

- Build the Console and the `j` command. Hotkey opens it.
- Phone page becomes the card feed, with approve and decline buttons that work from the phone.
- Run it beside the Brain page for a week, then delete the Brain page.

**Done when:** hotkey to a usable Console in under 0.3 s. Run, read, edit with diff and undo, and stop all work from it. You approve one real request from your phone. After the week, you tell me which one you used.

### Phase 5: One memory

- One store: readable Markdown in the vault (`Memory/You.md`, one file per project, a dated log) plus a searchable history of every conversation and job.
- Jarvis saves what you tell him as he goes, with the date and your words as the source. Changed facts keep the old version marked as replaced.
- A nightly tidy merges duplicates. Once a week he reads you a one-minute "here's what I learned; anything wrong?".
- The 129 waiting proposals are sorted once: obvious ones saved, the rest shown to you in one list.
- Reports stop being written into the vault as notes; the 103 existing ones move to the history.

**Done when:** 30 questions drawn from things you've told him over the past month score 27 or more correct (I'll run the same 30 today first for the before number). The proposals queue is gone. One place to look.

### Phase 6: Away work

- Heartbeat every 30 minutes with a short checklist you can edit.
- One rule for speaking up: now, hold for the summary, or skip. A daily cap you set (I'd start at 5).
- A job board in the Console: queued, running, checked, needs you.
- A morning report listing what finished overnight, each with the checker's verdict.
- Anything that sends, publishes, pays or deletes still asks you, now with a button on your phone.

**Done when:** three overnight jobs in a row finish with a checker verdict and one morning summary. Interruptions stay at or under the cap for a week. No paid API calls in the log.

The income goal comes after this. Phase 6 is the base it needs: work that runs unattended, is checked, and asks before anything leaves the house. Picking the business is a conversation for us to have once that base is proven.

---

## 6. Costs

| Item | Monthly | Notes |
| --- | --- | --- |
| **Recommended plan, all phases** | **$0 new** | Runs on the Claude plan and ChatGPT sign-in you already have, plus your GPU. |
| Risk: heavier use of your Claude plan | $0, but you may hit limits | He'll say so and stop. Moving up a plan tier would be your call; I haven't priced it. |
| Anthropic API key (today) | **Unknown, and should go to $0** | The screen agent has been billing it (43 uses) and limit fallback is on. Jarvis only logs conversation spend and that log stops Oct 26, so I can't see the amount. Worth a look at your Anthropic billing page. Phase 0 closes it. |
| ElevenLabs (today) | Whatever you're paying, if anything | The key is failing. If there's a subscription, it's doing nothing. |
| Not recommended: OpenAI Realtime voice | about $30 to $65 | At 20 minutes of talk a day and $0.05 to $0.11 a minute. Third-party price figures; not checked against OpenAI's own page. |
| Hardware | $0 | The 5070 Ti is enough. |
| Optional later: move Telegram and the heartbeat to the Pi | $0 | So your phone still reaches Jarvis when the PC sleeps. |

---

## Approved 2026-11-10, with changes

- Plan approved. Paid API paths off from Phase 0.
- **Console goes inside the existing Jarvis page,** not in place of it. One switch moves between the Console and the 3D model view.
- **Keep Holo, the graph and the 3D model.** Eyes, Watch, Focus, digests, routines and documents are still deleted.
- The existing page gets a tidy-up at my discretion: remove buttons that do nothing useful, group related ones.

Where the sections above say the Brain page, graph, holo or orb are deleted, this overrides them.

## Decisions I needed from you (answered above)

1. **Approve the plan,** or tell me what to change.
2. **Console or Ambient?** I recommend Console.
3. **OK to delete Holo, Eyes, Watch, Focus, digests, routines, documents and the graph?** The usage says yes. You may know something the logs don't.
4. **OK to turn off the paid API paths at the start of Phase 0?** This disables `do_on_computer` until Phase 3 replaces it.

## Build log (branch `makeover`)

### Done and running, 2026-11-10

| Step | What changed | Checked how |
| --- | --- | --- |
| Phase 0 | Every turn's stage times, tools and tool results are saved (`data/turn_stages.jsonl`). `scripts/measure.py` prints the scorecard. Paid API keys are no longer loaded and "subscription only" is on. `scripts/run_tests.py` fails a run that changes `data/`. | Live turn recorded with its tool. Test proves the keys are blank. |
| Phase 1, part | End-of-turn model (Smart Turn v3.2) ends a finished sentence after 0.32 s of silence; the old 1.2 s timer is the fallback. A tool running over 1.2 s gets a few spoken words. A newly saved fact no longer restarts the brain session. | Model told finished from unfinished phrases on 8 of 10 synthesised samples, 23 ms each. **Not yet heard by you in real use.** |
| Phase 2 | Every action leaves a receipt (confirmed, sent, waiting, unknown, failed). The claim gate checks receipts, not just "some tool ran". Jarvis adds the sentence himself when a failure goes unmentioned. | 65 of 65 honesty cases pass, including the TV case. Replayed over 915 past turns, it would have stopped 13 replies. |
| Phase 3, part | Removed Eyes, Watch, Focus, digests, routines, documents, artifacts, YouTube and Amazon tools. | 802 tests pass. Removed routes return 404 on the live server. |
| Phase 3, part | One talking brain: the Anthropic API, OpenAI API, local chat model and router code is deleted. Claude or Codex on your own plans are the only choices; a plan limit is said aloud and the turn stops. | 766 tests pass. Live `/models` offers only those two. |
| Phase 4 | Console view inside the Jarvis page (switch in the top bar, or Ctrl+.). Page tidy-up. `j` command for any terminal. | Browser check passes, including 30 Console assertions. Live page shows 10 real device tiles. `j` answered in 1.1 s (plain) and 1.9 s (with a lookup). |

### Added later on 2026-11-10

| Step | What changed | Checked how |
| --- | --- | --- |
| Voice | End of turn waits a full second of silence (owner pauses mid-thought). Piper voice deleted at the owner's request. | Tests; live picker no longer lists Piper. |
| Phase 5 | The memory approval queue is gone. Its 129 items were sorted once: 41 saved with their source, 36 decisions logged, 15 left for the owner, 37 dropped (all listed in `data/reports/memory-proposals-sorted-2026-11-10.md`). Journal decisions now go straight to the vault's Decision log. `search_history` searches past conversations. `Memory/What Jarvis knows about you.md` in the vault is a readable copy of memory. On Sundays he says what he saved that week. | 30 recall questions: 18 found before, 29 after (I wrote the questions knowing the facts, so treat it as a rough check). Live: answered "where do I work" and found a past conversation. |
| Phase 6 | `attention.py`: unprompted updates are said or held (budget of five a day; held ones come out together at the next welcome back). `heartbeat.py`: half-hourly plain checks, plus an optional checklist note in the vault. Console job board for away jobs. Yes/No buttons on the phone page for open approvals. | 810 tests. Live routes answer; the phone refuses `/pending` without the key. **No real away job or phone approval has been run yet.** |
| Fixes found on the way | The phone bridge dropped the connection instead of giving its reason (test failed 2 runs in 9; now 0 in 12). `j` hung when started with a silent input pipe. Two tests read the real vault or Spotify sign-in. | Tests added for each. |

| Cards | A waiting question, held updates, finished away jobs and finished agents show as cards with their buttons, beside the 3D model and in the Console. | Browser check covers every card and button. |
| `do_on_computer` | Back, on the Claude plan instead of the paid API: the same mouse, keyboard and safety code, with Claude Code as the brain. | Two real trials: opened Notepad and typed a line (13 s, 3 calls); clicked Notepad's File menu first try and read it back (8 s). |

Changed from the plan: finished-job reports **stay in the vault**. The graph you chose to keep is built from them, so moving them out would have emptied it.

### What the measurements corrected

- **Trimming the tool list does not make him faster.** Opus answered in the same time with 85 tools and with 28. Dropped from the plan as a speed measure.
- **A smaller model is not the fix either.** First text, no tool: Haiku 0.5 s, Sonnet 0.5 s, Opus 0.6 s. With a tool: 1.1, 1.7 and 2.0 s. Haiku also misread a calendar time in a ten-question test. Opus stays.
- **The brain itself is fast.** On his real prompt with instant tools, Opus gives the first sentence in 1.2 s (no tool) and 2.2 s (tool). The old 5.7 s on tool turns was mostly the tools themselves and session restarts, not thinking.
- **VoiceStudio cannot stream.** First audio arrives when the whole sentence is built (about 0.8 s for a 4.5 s sentence). Halving its quality steps saves 0.27 s. Getting first audio under 0.3 s needs a different engine, which needs your ear.
- **Audit error:** I said the voice lock cut-off was 0.74. That was an old log line; it is 0.62 today, so the "43 near-miss rejections" figure does not describe the current setting.

### Still to do

- Phase 1: streaming voice engine (needs you to listen), instant ducking when you speak (needs a live test), and your verdict on the turn detector.
- Phase 3: remove ElevenLabs from `voice.py` (unreachable now that its key isn't loaded; best done with the voice engine swap). Piper stays until you say otherwise: there is a custom voice in `models/piper`. Move to the built-in MCP client.
- Phase 4: diff cards have no Undo button yet. The phone page has approve buttons but is still a chat, not a card feed.
- Phase 6: prove it with three real overnight jobs and one real phone approval.

## Things I could not verify

- How fast he stops when interrupted, and true end-to-end voice timing. Both need a live test with you speaking.
- How often he states something unverified. Phase 0 builds the way to measure it.
- How much the API key has been charged.
- Whether a test or the live Spotify bridge changed `data/spotify-mcp.enc` during my test run. Spotify should be checked next time you use it.
- Speed targets in Phase 1 are goals from published figures, not yet measured on your PC.
- Most web sources on assistants and voice are vendor blogs. Where numbers disagreed I've said so.

## Sources

Assistants: [OpenClaw vs Hermes (TrueFoundry)](https://www.truefoundry.com/blog/openclaw-vs-hermes) · [Hermes Agent compare page](https://hermes-agent.nousresearch.com/compare/openclaw) · [Neutral comparison (vdf.ai)](https://vdf.ai/blog/hermes-agent-vs-openclaw/) · [OpenClaw alternatives (openalternative.co)](https://openalternative.co/blog/best-openclaw-alternatives) · [OpenClaw heartbeat docs](https://docs.openclaw.ai/heartbeat) · [Scheduled tasks across ChatGPT, Claude, Gemini](https://www.aiagentslibrary.com/blog/chatgpt-vs-claude-vs-gemini-scheduled-tasks/) · [ChatGPT Pulse retired](https://prowlo.com/blog/chatgpt-pulse-shut-down)

Voice: [LiveKit: voice agent architecture](https://livekit.com/blog/voice-agent-architecture-stt-llm-tts-pipelines-explained) · [Sub-500 ms pipeline budget (Bearworks)](https://www.bearworks.com/post/sub-500ms-voice-agents-stt-llm-tts-latency) · [Cascaded vs speech-to-speech (Gradium)](https://gradium.ai/content/cascaded-voice-agent-vs-speech-to-speech-2026) · [Smart Turn v3 model card](https://huggingface.co/yapwithai/pipecat-smart-turn-v3/blob/main/README.md) · [Turn detection comparison (Evalgent)](https://www.evalgent.com/blog/end-of-turn-detection-flux-silero-turn-detector) · [Kyutai Unmute](https://github.com/kyutai-labs/unmute) · [Open-source TTS 2026 (BentoML)](https://www.bentoml.com/blog/exploring-the-world-of-open-source-text-to-speech-models) · [Kokoro vs Chatterbox vs Qwen3-TTS](https://www.tryspeakeasy.io/blog/open-source-text-to-speech-2026) · [OpenAI Realtime pricing (Forasoft)](https://www.forasoft.com/blog/article/openai-realtime-api-pricing) · [OpenAI Realtime vs Gemini Live cost](https://cozzo.io/compare/openai-realtime-vs-gemini-live)

Agents and honesty: [MCP client best practices](https://modelcontextprotocol.io/docs/2026-07-28/develop/clients/client-best-practices) · [Tool search and code mode](https://redreamality.com/blog/mcp-server-sprawl-tool-selection-at-scale/) · [VeriCUA coverage, Nov 2026](https://cryptobriefing.com/google-hku-vericua-ai-agent-verification/) · [Verifier that goes and looks (Ken Ashe, Oct 2026)](https://kenashe.ai/blog/2026-10-30-verifying-computer-use-agents-by-letting-the-verifier-go-look) · [Verify-gated completion](https://learn.agentpatterns.ai/multi-agent/verify-gated-completion/) · [Agent harness study (arXiv 2609.20474)](https://arxiv.org/pdf/2609.20474)

Memory: [Five memory systems compared](https://medium.com/@wasowski.jarek/i-compared-5-ai-agent-memory-systems-across-6-dimensions-none-wins-6a658335ed0a) · [Mem0: state of agent memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026) · [Mem0 vs Letta vs Zep](https://www.digitalapplied.com/blog/open-source-agent-memory-mem0-letta-zep-compared) · [MemDelta: hidden confounds in memory benchmarks](https://arxiv.org/pdf/2606.29914)

Proactivity and UI: [Notification budgets (tianpan.co, May 2026)](https://tianpan.co/blog/2026-05-13-background-agents-notification-budget-attention-economy) · [Building proactive agents (Navan)](https://navan.com/blog/build-proactive-ai-agents) · [A2UI 0.9 (Google, Apr 2026)](https://developers.googleblog.com/a2ui-v0-9-generative-ui/) · [Generative UI guide (CopilotKit)](https://www.copilotkit.ai/blog/the-developer-s-guide-to-generative-ui-in-2026)

Local models: [Best LLM for 16 GB VRAM](https://localaimaster.com/vram/best-llm-16gb-vram) · [Small local models for tool calling](https://www.promptquorum.com/power-local-llm/best-local-models-tool-calling-2026)
