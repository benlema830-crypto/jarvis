# Zubair's "Fable 5.2 Just Took My JARVIS to a Whole New Level": research for the build

Researched 2026-11-11 by Claude Opus 5.5. **Nothing here is built yet.** The owner said: "research and figure out
what he added and how he did it ... Dont make changes yet, fable 5.2 will handle that after you research."
So this is the brief for the Fable 5.2 session that builds it. Ask the owner which parts they want before starting.

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

## Build options for Fable (biggest payoff first; the owner picks)

1. **Workshop overlay in the Jarvis page** (large). A new view next to the 3D model/Console switch: three.js from
   `~/holo/vendor`, OrbitControls, grid floor, build panel. Generation runs through Claude Code with `fable`, which
   returns a JSON-wrapped module `{title, parts:[{name, description, explode:[x,y,z]}], steps:[...], code}`
   that runs in a sandboxed `new Function(THREE, scene, api)` so a bad output can't touch the rest of the page.
   Tools: `workshop_build(request, picture?)`, `workshop_edit(request)`, `workshop_explode(on)`, plus part
   questions answered from the stored part list. Save each scene in `data/workshop/` so it reopens.
2. **Picture in** (medium, after 1): choose/drop/paste, and `look_at_screen` as "build what's on my screen".
3. **Fable as a main-brain choice by voice** (small): add it to `claude_code_brain.MODELS` and the model words.
4. **Narrated computer use** (small to medium): let `agent.py` say a short line per step when the owner is in
   the room, and stop when the owner moves the mouse (his demo), not only on a corner fling.
5. **Photoreal render** (medium; **costs money**): his uses the OpenAI image API. Our saved OpenAI key returned
   `credit_balance_exhausted` on 2026-11-11, and the owner's rule is the API only when the job is impossible
   without it, so ask before building this. Check first whether the Codex/ChatGPT subscription can make images.

Not worth copying: the paid v8.2 skill, and Meta Ads specifically (the takeaway is narration and stopping, not the ads).

## Open questions for the owner

- Which of 1-5 do they want, and is the photoreal render worth paying for?
- Should workshop builds run on Fable every time (slower, about 30-60 s per build in his video) or Opus for edits?
- Do they want to join the free AI Workshop Lite to get the prompt pack? (Optional.)
