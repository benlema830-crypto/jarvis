# Zubair's "Fable 5.2 Just Took My JARVIS to a Whole New Level": research for the build

**Built 2026-11-11 by Claude Fable 5.2: all five items, each tried live. How it works now is in
`docs/PROJECT-MAP.md`, "The workshop, and what else came from Zubair's videos". What follows is the research it
was built from.**

Researched 2026-11-11 by Claude Opus 5.5. At that point nothing was built. The owner said: "research and figure out
what he added and how he did it ... Dont make changes yet, fable 5.2 will handle that after you research."
So this is the brief for the Fable 5.2 session that builds it. The owner chose all five options below.

- Video: https://www.youtube.com/watch?v=34J8xhaAn4U (posted 2026-11-10, 17:19, channel "Zubair Trabzada | AI Workshop")
- Full transcript and Jarvis's own write-up: vault note `Research/Zubair watch/2026-11-11 Fable 5.2 Just Took My JARVIS to a Whole New Level.md`
- Frames from the video: `docs/plans/zubair-fable-5.2-frames/` (file names are the timestamps)

## Where his code is (and isn't)

- **Not public.** The workshop isn't on his GitHub. His GitHub (`zubair-trabzada`) has HOLO, brain-map and
  Claude Code skill packs, none touched for this video. The newest push (2026-11-11) is `geo-seo-claude`, an SEO skill.
- **Free prompt pack:** the "FREE JARVIS PROMPT PACK" is in the free Skool community AI Workshop Lite
  (https://www.skool.com/aiworkshop-lite) → Classroom → YouTube Resources → "Claude code and Codex GPT" folder,
  at the bottom. You have to join to see it (free, but it's a sign-up, so the owner does that, not an agent). It's a set of
  prompts you paste into Claude Code, not source code. Getting it is optional; the notes below are enough to build from.
- **Paid:** "the finished JARVIS" (v8.2, a skill file) is in the paid community. The owner doesn't want it. Skip it.
- **His own repo already has the explode idea:** `~/holo` (zubair-trabzada/holo-gestures, MIT, our clone is current)
  explodes multi-part GLB models: each mesh moves along its direction from the model's centre
  (`holo.html` ~line 954: `p.m.position.copy(p.base).addScaledVector(p.dir, c.explode * .55)`). It also vendors
  `three.module.js` and `GLTFLoader.js`, which the workshop can reuse. Our Jarvis has no three.js of its own
  (the graph in `hud/brain.js` is a 2D canvas).

## What he showed (timestamps)

| Time | Feature |
|---|---|
| 02:02 | Switches the main brain to Fable 5.2 **by voice** ("Claude Fable 5.2 online, sir. A step above Opus"). He says it runs through the API and costs a lot. |
| 02:28 | "Build yourself a body": the workshop opens, Fable designs a 3D object and it **appears piece by piece** |
| 03:47 | Voice edits ("make the reactor ring red", then "I meant the housing"); each edit takes a few seconds |
| 05:10 | "Pull it apart": an **exploded view** with a **label and leader line on every part**; "put it back together" reverses it |
| 05:50 | Questions about parts ("what is the main logic board?") answered from what was built |
| 07:02 | "Open the workshop": an empty bench to "drop a picture on, paste, or share your screen and say 'Jarvis, build this'" |
| 07:50 | Floor-plan screenshot → a 3D house with rooms, furniture, pool and palm trees; the roof is see-through; the picture is pinned top right |
| 09:00 | Voice edits to the house: remove stairs, centre the door, make the living room 1.2 m deeper, add plants |
| 10:47 | "Render it": a **photoreal miniature** made with **GPT Image 2.6 through the OpenAI API**, shown with 3D model / Miniature / Save picture buttons; he says it renders again after each change |
| 11:49 | Computer use: shares a Chrome tab, "take over the screen and create a new Meta campaign"; Jarvis **narrates every step aloud**; "OK Jarvis, that's enough" or touching the mouse stops it; he says it never publishes unless told to |

## How it works (from the frames; nothing below was said in the video unless marked)

The frames are clear enough to see how it was built:

1. **A full-screen overlay in his web UI** (localhost:4719) with its own title ("Jarvis Reactor Companion",
   "Pool Home Plan", "The workshop") and a Close button. Dark three.js scene, a glowing grid floor in a circle, his
   Jarvis orb stays on the right, captions bottom centre. "Drag to turn it" (OrbitControls) and zoom.
2. **Fable writes three.js scene code**; it isn't making mesh files. The "thinking" text in the build panel says it:
   *"assigning each part an exploded offset so the shells and internals don't overlap"*, *"wiring the tick handler so
   the ring and tick group pulse with the voice level"*, *"Still writing the scene code, now setting up the lamps and
   the roof over the house footprint. Still writing the helper that places furniture at offset coordinates."*
   So the model returns JavaScript that builds named parts from three.js primitives, each with its exploded
   offset, label and description, and an animation hook tied to the voice level.
3. **Build panel, bottom left:** "BUILDING" / "BUILT", the model's thinking streamed live ("FABLE IS THINKING" →
   "THOUGHT IT THROUGH IN 41 S"), then a checklist of steps written in Jarvis's voice ("Turning the aluminium
   foot", "Seating the speaker driver", ... "Waking the reactor"). Edits get their own list ("Clearing the foyer
   stairs", "Centring the entry porch"). Top left: model name, timer, token count (e.g. 1:04, 22.9K tokens).
   Parts appear as the steps finish, so the code is streamed or split by step (inferred).
4. **Edits are changes to that code**: the current scene code plus the request go back to Fable, and the scene
   is rebuilt. An edit took about 30 s and 12K tokens in the video (frame at 09:20).
5. **Explode and reassemble** animate each part to its stored offset; labels with leader lines (CSS2D-style, inferred).
   Questions about parts are answered from the part list (names and descriptions) kept with the scene (inferred).
6. **Picture in:** a "Choose a picture" button, drag-and-drop, paste, or a shared screen (browser
   `getDisplayMedia`; the Chrome "Choose what to share with localhost:4719" dialog is visible at 12:25). The picture
   goes to Fable's vision along with the request.
7. **Render:** a screenshot of the 3D canvas goes to GPT Image 2.6 (he said this) to make the "miniature".
8. **Spoken lines are short, in character, and end with an offer** ("Say pull it apart, or I can warm the light").

## What we already have

- **Fable on the subscription, not the API:** `agent_models.py` already maps `fable` → `claude-fable-5-2` for agents
  through Claude Code on the owner's Max plan. That's the cheap way for the workshop's code generation. His runs
  on API credits; ours shouldn't need to.
- **Main brain by voice:** `switch_model` exists, but `claude_code_brain.MODELS` has only Opus/Sonnet/Haiku. Adding
  `claude-fable-5-2` there is the small change that matches 02:02. The saved brain today is Codex `gpt-6.1-terra`
  with `subscription_only: true`.
- **Explode logic and vendored three.js:** in `~/holo` (above).
- **Computer use:** `agent.py` (`do_on_computer`) drives a Claude Code session with screenshots. It already
  stops on "Jarvis, stop", Ctrl+Alt+J, the STOP button, or the mouse flung into a corner, and asks before money or
  messages. It works on the whole desktop, not a shared tab, and it doesn't narrate each step aloud the way his does.
- **Real CAD:** the Fusion MCP (`mcp__fusion__*`) and the bedroom model (memory: bedroom-fusion-model) are a
  different strength his Jarvis doesn't show: Fusion makes real, measurable models; his workshop makes concept scenes.

## What to build: all five (owner, 2026-11-11: "can we do all 5 of those?")

The owner's rule for everything from Zubair: "we only want to implement things we dont have already, otherwise its
going backwards." So build each piece onto what Jarvis already has. Don't replace a part of ours that works.

1. **Workshop overlay in the Jarvis page** (large). A new view beside the existing 3D model/Console switch (keep
   both). three.js from `~/holo/vendor` (MIT), OrbitControls, a grid floor, the build panel (live thinking, step
   checklist, timer, tokens), a title and Close. Generation runs through Claude Code with `fable` on the Max plan
   (`agent_models.py`), not API credits. Fable returns `{title, parts:[{name, description, explode:[x,y,z]}],
   steps:[...], code}`, and `code` runs in `new Function(THREE, scene, api)`, so a bad answer only breaks the scene, not the
   page. Tools for the brain: `workshop_build(request, picture?)`, `workshop_edit(request)`,
   `workshop_explode(on)`, `workshop_render()`. Questions about parts are answered from the stored part list. Each
   scene is saved under `data/workshop/` (code, parts, versions) so it reopens and an edit can be undone. Spoken lines
   stay short and end with an offer, like his.
2. **Picture in** (medium). "Choose a picture", drag-and-drop and paste on the bench; "build what's on my screen"
   uses the existing `look_at_screen` capture. The picture goes to Fable with the request and is pinned top right.
3. **Fable as a choice for Jarvis's talking brain** (small). See "What #3 means" below.
4. **Narrated computer use** (small to medium). In `agent.py` (`do_on_computer`): one short spoken line per step
   while the owner is in the room (`whereabouts.py`), and stop when the owner moves the mouse or presses a key,
   not only when it's flung into a corner. Keep the stops and approvals it already has.
5. **Realistic render** (medium). See "What #5 means" below. Use Codex image generation on the ChatGPT plan, not
   the OpenAI API.

### What #3 means

Jarvis has two kinds of model:
- **The talking brain**: the model that answers when you speak to him. It's saved in `data/preferences.json`
  (today Codex `gpt-6.1-terra`) and you change it by voice with `switch_model` or in the Brain's Model control.
  On the Claude side that list is `claude_code_brain.MODELS` = Opus 5.5, Sonnet 5.5, Haiku 5.5. **Fable isn't in it.**
- **The workers**: agents, away jobs and parallel jobs, which can already run on Fable (`model="fable"`).

At 02:02 Zubair says "switch your brain to Fable 5.2" and from then on his talking brain is Fable. #3 does the same:
add `claude-fable-5-2` to `claude_code_brain.MODELS` and the spoken names ("Fable", "Fable 5.2"), so "Jarvis, switch
your brain to Fable" works. It runs on the Max plan through Claude Code, like Opus does today, so no API bill.
It is a choice, not the new default. The workshop (#1) uses Fable for its builds whatever the talking brain is, so
#3 isn't needed for the workshop. It's for when the owner wants Fable's judgment in conversation. Trade-off:
Fable uses more of the Max plan's limits per reply than Opus, and its reply speed hasn't been measured on this PC.
Measure the first-sentence time with `scripts/measure.py` after adding it (Opus is about 1.2 s).

### What #5 means

In his video "Render it" takes the plain 3D model (flat colours, simple shapes, like a toy) and makes a
**realistic photo-style picture** of it as a tabletop miniature, with real-looking grass, water, wood and cars
(frame `11-02-miniature-render.jpg`). He says it re-renders after each change. It's done by an AI **image
generator**, not by the 3D scene.

- **Why his costs money:** he uses GPT Image 2.6 through the **OpenAI API**. That is billed per use to an API
  account, separately from a ChatGPT subscription: about $30 per million output image tokens, roughly
  $0.03-$0.21 per image depending on size and quality (secondary sources, November 2026; check OpenAI's page
  before relying on it). Rendering again after every voice edit adds up. Our saved OpenAI key had
  `credit_balance_exhausted` on 2026-11-11.
- **Ours doesn't have to cost anything extra:** Codex CLI 0.164 on this PC has `image_generation` (stable, on),
  and it runs on the owner's **ChatGPT plan** (`codex login status`: "Logged in using ChatGPT"). Tested 2026-11-11:
  - text to image, 37 s: `zubair-fable-5.2-frames/test-codex-image.jpg`
  - **his 3D house screenshot to a realistic miniature, 56 s, keeping the layout:**
    `zubair-fable-5.2-frames/test-codex-render-from-3d.jpg`. As good as his.
  - Command used: `codex exec --skip-git-repo-check -s workspace-write --image scene.jpg -- "<prompt>; save it in the
    current folder as miniature.png"`. Put `--` before the prompt, or `--image` swallows it.
  It counts against the ChatGPT plan's usage. So: render only when asked ("render it"), not after every edit
  like his. Offer to re-render after an edit instead. Run it in the background (about a minute), show it with
  3D model / Miniature / Save picture buttons, and save to `data/workshop/<scene>/renders/`.

## Order

#3 first (small, separate), then #1, #2, #5 and #4. Run the full tests (`scripts/run_tests.py`), restart quietly
(`scripts/restart_jarvis.py`), and try each by voice for real before saying it works.

## Also from his older videos

See `docs/plans/ZUBAIR-GAPS.md`: what his earlier Jarvis videos show that ours still lacks, checked against our code.
