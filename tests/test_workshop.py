import base64
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import brain
import hud
import workshop

SCRIPT = """TITLE: Desk Lamp
=== SETUP
const steel = new THREE.MeshStandardMaterial({ color: 0x888888 });
=== STEP: Turning the base
api.part("Base", "A weighted steel disc that keeps the lamp upright.", new THREE.Mesh(new THREE.CylinderGeometry(.1, .1, .02), steel), [0, -0.2, 0]);
=== STEP: Raising the arm
api.part('Arm', 'A tube that carries the wire to the head.', new THREE.Mesh(new THREE.CylinderGeometry(.01, .01, .4), steel), [0, 0.2, 0]);
=== SPOKEN
A desk lamp, sir. Say pull it apart,
or I can warm the light.
"""
PATCH = """=== STEP: Raising the arm
api.part('Arm', 'A red tube that carries the wire.', new THREE.Mesh(new THREE.CylinderGeometry(.01, .01, .4), red), [0, 0.2, 0]);
=== STEP: Fitting the shade
api.part("Shade", "A cone that aims the light.", new THREE.Mesh(new THREE.ConeGeometry(.08, .1), steel), [0, 0.4, 0]);
=== REMOVE: Turning the base
=== NOTE: Lacquering the arm red
=== SPOKEN
The arm is red, sir."""


def jpeg(size=(40, 30)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


class ScriptFormatTest(unittest.TestCase):
    def test_parse_reads_title_setup_steps_and_spoken(self):
        parsed = workshop.parse(SCRIPT)
        self.assertEqual(parsed["title"], "Desk Lamp")
        self.assertIn("steel", parsed["setup"])
        self.assertEqual([s["name"] for s in parsed["steps"]], ["Turning the base", "Raising the arm"])
        self.assertEqual(parsed["spoken"], "A desk lamp, sir. Say pull it apart, or I can warm the light.")

    def test_parse_ignores_code_fences_and_reads_a_patch(self):
        parsed = workshop.parse("```\n" + PATCH + "\n```")
        self.assertIsNone(parsed["setup"])
        self.assertEqual(parsed["remove"], ["Turning the base"])
        self.assertEqual(parsed["notes"], ["Lacquering the arm red"])
        self.assertEqual(len(parsed["steps"]), 2)

    def test_feed_reports_each_block_as_soon_as_the_next_one_starts(self):
        seen = []
        feed = workshop.Feed(lambda kind, value: seen.append((kind, value["name"] if kind == "step" else value)))
        cut = SCRIPT.index("\n", SCRIPT.index("=== STEP: Raising the arm")) + 1   # the next block's heading has arrived
        for i in range(0, cut, 7):   # arrives in arbitrary pieces
            feed.add(SCRIPT[i:min(i + 7, cut)])
        self.assertEqual([kind for kind, _ in seen], ["title", "setup", "step"])   # the first step is complete
        self.assertEqual(seen[-1][1], "Turning the base")
        feed.add(SCRIPT[cut:], final=True)
        self.assertEqual(seen[-1], ("step", "Raising the arm"))
        self.assertEqual(workshop.parse(feed.text)["spoken"][:11], "A desk lamp")

    def test_parts_come_from_the_part_calls_with_either_quote(self):
        scene = {"steps": workshop.parse(SCRIPT)["steps"]}
        self.assertEqual(workshop.parts(scene), [
            ("Base", "A weighted steel disc that keeps the lamp upright."),
            ("Arm", "A tube that carries the wire to the head.")])

    def test_patch_replaces_adds_and_removes_steps(self):
        scene = dict(workshop.parse(SCRIPT), id="x")
        changed = workshop.apply_patch(scene, workshop.parse(PATCH))
        self.assertEqual([s["name"] for s in changed["steps"]], ["Raising the arm", "Fitting the shade"])
        self.assertIn("red tube", changed["steps"][0]["code"])
        self.assertEqual(scene["steps"][1]["code"].count("red"), 0)   # the original is untouched, for undo

    def test_a_patch_that_changes_nothing_is_refused(self):
        scene = dict(workshop.parse(SCRIPT), id="x")
        with self.assertRaises(ValueError):
            workshop.apply_patch(scene, workshop.parse("=== SPOKEN\nDone, sir."))

    def test_script_round_trips(self):
        scene = dict(workshop.parse(SCRIPT), id="x")
        again = workshop.parse(workshop.script(scene))
        self.assertEqual(again["steps"], scene["steps"])
        self.assertEqual(again["setup"], scene["setup"])


class LocalGenerationTest(unittest.TestCase):
    def test_local_stream_preserves_pictures_progress_and_usage(self):
        import local_brain
        text, thinking = [], []
        events = [{"message": {"thinking": "shape", "content": "TITLE: Lamp\n"}},
                  {"message": {"content": "=== STEP: Base\napi.add(base);"}},
                  {"done": True, "eval_count": 42, "prompt_eval_count": 12}]
        with mock.patch.object(local_brain, "chat", return_value=iter(events)) as chat, \
                mock.patch.object(workshop, "_stream") as claude:
            usage = workshop.generate(workshop.QWEN_MODEL, "low", "system", "build", [b"one", b"two"],
                                      thinking.append, text.append)
        payload = chat.call_args.args[0]
        self.assertEqual(payload["messages"][1]["images"], ["b25l", "dHdv"])
        self.assertTrue(payload["think"])
        self.assertNotIn("tools", payload)
        self.assertEqual(usage["output_tokens"], 42)
        self.assertEqual(thinking, ["shape"])
        self.assertTrue("".join(text).startswith("TITLE: Lamp"))
        claude.assert_not_called()

    def test_local_cancellation_and_incomplete_output_are_not_success(self):
        import local_brain
        for events, error in [([], RuntimeError), ([{"done": True, "done_reason": "length"}], RuntimeError)]:
            with mock.patch.object(local_brain, "chat", return_value=iter(events)):
                with self.assertRaises(error):
                    workshop.generate(workshop.QWEN_MODEL, "low", "s", "p")
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(local_brain, "chat", return_value=iter([])):
            with self.assertRaises(InterruptedError):
                workshop.generate(workshop.QWEN_MODEL, "low", "s", "p", cancel=cancel)


class WorkshopFlowTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Path(temp.name) / "workshop"
        self.events, self.said, self.replies = [], [], [SCRIPT]
        self.opened, self.browser = [], False
        # The plain flow tests switch off the two things a build now does afterwards; their own tests switch them on.
        self.prefs = {"workshop": {"check": False, "references": False}}
        self.found = []
        self.calls = []
        fresh = {"open": False, "busy": "", "scene": None, "exploded": False, "view": "model", "thinking": "",
                 "started": 0.0, "seconds": 0, "tokens": 0, "done": [], "notes": [], "error": "", "errors": [],
                 "render": "", "model": "", "selected": [], "isolate": False, "measuring": False, "cut": None,
                 "moving": [], "variants": []}

        def generate(model, effort, system, prompt, image=None, on_thinking=None, on_text=None, cancel=None):
            self.calls.append({"model": model, "effort": effort, "prompt": prompt, "image": image})
            on_thinking("thinking it over")
            text = self.replies.pop(0)
            for i in range(0, len(text), 50):
                on_text(text[i:i + 50])
            return {"output_tokens": 321}

        for target, name, value in [
                (workshop, "STORE", self.store), (workshop, "STATE", fresh), (workshop, "generate", generate),
                (workshop, "_restored", True), (workshop, "_work", threading.Lock()),
                (workshop, "_emit", lambda phase, **data: self.events.append((phase, data))),
                (workshop, "_announce", lambda text, note: self.said.append((text, note))),
                (workshop, "_page", {"at": 0.0, "visible": False, "opened": 0.0}),
                (workshop, "PAGE_WAIT_SECONDS", 0.2), (workshop, "PAGE_LOAD_SECONDS", 0.4),
                (workshop, "open_page", lambda: self.opened.append(1) or self.browser),
                (workshop, "_sizes", {"at": 0.0, "whole": None, "parts": {}, "ruler": None}),
                (workshop, "OUTBOX", Path(temp.name) / "outbox"), (workshop, "EXPORT_WAIT", 0.6),
                (workshop, "VIDEO_SECONDS", 0), (workshop, "SNAPSHOT_WAIT", 0.6), (workshop, "SCOUT_WAIT", 2),
                (workshop, "find_references", lambda request, folder, cancel=None, shots=(): self.photos(folder, shots)),
                (workshop, "_screens", lambda: (jpeg((90, 30)), [jpeg((60, 40)), jpeg((50, 40))])),
                (workshop.preferences, "read", lambda: self.prefs)]:
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def photos(self, folder, shots=()):
        """What the photo scout "found": writes the files where the real one would."""
        self.shots = [Path(shot).name for shot in shots]
        Path(folder).mkdir(parents=True, exist_ok=True)
        for ref in self.found:
            (Path(folder) / ref["name"]).write_bytes(jpeg())
        return list(self.found)

    def wait(self):
        for _ in range(400):
            if not workshop.STATE["busy"] and not workshop._work.locked():
                return
            time.sleep(0.02)
        self.fail("the workshop never finished")

    def phases(self):
        return [phase for phase, _ in self.events]

    def test_build_streams_steps_saves_the_scene_and_announces_it(self):
        reply = workshop.build("a desk lamp")
        self.assertIn("build has started", reply)
        self.wait()
        self.assertEqual(self.calls[0]["model"], "claude-fable-5-2")
        self.assertEqual(self.calls[0]["effort"], "low")
        self.assertEqual([p for p in self.phases() if p in ("start", "title", "setup", "step", "done")],
                         ["start", "title", "setup", "step", "step", "done"])
        scene = workshop.STATE["scene"]
        self.assertEqual(scene["title"], "Desk Lamp")
        saved = json.loads((self.store / scene["id"] / "scene.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["steps"]), 2)
        text, note = self.said[0]
        self.assertTrue(text.startswith("A desk lamp, sir."))
        self.assertIn("Base: A weighted steel disc", note)   # so questions about parts can be answered
        self.assertEqual(workshop.snapshot()["tokens"], 321)

    def test_qwen_build_and_edit_use_the_installed_model(self):
        self.prefs["workshop"]["model"] = "qwen"
        workshop.build("a desk lamp")
        self.wait()
        self.replies.append(PATCH)
        workshop.edit("make the arm red")
        self.wait()
        self.assertEqual([c["model"] for c in self.calls], [workshop.QWEN_MODEL] * 2)
        self.assertEqual(workshop.snapshot()["selected_model"], "qwen")
        self.assertEqual(workshop.snapshot()["models"], workshop.MODELS)

    def test_model_selection_preserves_options_and_refuses_changes_during_a_job(self):
        with mock.patch.object(workshop.preferences, "update") as save:
            workshop.page_report({"action": "model", "model": "qwen"})
            save.assert_called_once_with(workshop={"model": "qwen", "check": False, "references": False})
            workshop._work.acquire()
            try:
                with self.assertRaisesRegex(ValueError, "finish"):
                    workshop.select_model("fable")
            finally:
                workshop._work.release()
            self.assertEqual(save.call_count, 1)
            with self.assertRaises(ValueError):
                workshop.select_model("unknown")

    def test_a_second_job_while_one_runs_is_not_started(self):
        workshop._work.acquire()
        self.addCleanup(lambda: workshop._work.locked() and workshop._work.release())
        self.assertIn("queued", workshop.build("a chair"))   # waits its turn; nothing starts alongside
        self.assertEqual(self.calls, [])
        workshop.STATE.pop("queued", None)

    def test_edit_sends_the_script_back_and_can_be_undone(self):
        workshop.build("a desk lamp")
        self.wait()
        self.replies.append(PATCH)
        workshop.edit("make the arm red and add a shade, no base")
        self.wait()
        self.assertIn("=== STEP: Turning the base", self.calls[1]["prompt"])
        self.assertIn("make the arm red", self.calls[1]["prompt"])
        scene = workshop.STATE["scene"]
        self.assertEqual([s["name"] for s in scene["steps"]], ["Raising the arm", "Fitting the shade"])
        self.assertEqual(self.events[-1][0], "patch")
        self.assertEqual(self.events[-1][1]["notes"], ["Lacquering the arm red"])
        self.assertEqual(self.said[-1][0], "The arm is red, sir.")
        self.assertIn("Undone", workshop.undo())
        self.assertEqual([s["name"] for s in workshop.STATE["scene"]["steps"]], ["Turning the base", "Raising the arm"])
        with self.assertRaises(ValueError):
            workshop.undo()

    def test_a_failed_build_says_so_and_frees_the_bench(self):
        self.replies[:] = ["I can't help with that."]
        workshop.build("a desk lamp")
        self.wait()
        self.assertIn("didn't finish", self.said[0][0])
        self.assertEqual(self.phases()[-1], "error")
        self.assertFalse(workshop._work.locked())

    def test_nothing_to_change_or_pull_apart_on_an_empty_bench(self):
        for call in (lambda: workshop.edit("make it red"), lambda: workshop.explode(True), workshop.render, workshop.undo):
            with self.assertRaises(ValueError):
                call()

    def test_explode_names_the_parts_and_tells_the_page(self):
        workshop.build("a desk lamp")
        self.wait()
        self.assertIn("Base, Arm", workshop.explode(True))
        self.assertEqual(self.events[-1], ("explode", {"on": True}))
        self.assertTrue(workshop.snapshot()["exploded"])

    def test_picture_from_the_bench_goes_to_the_model_and_back_to_the_brain(self):
        self.store.mkdir(parents=True)
        (self.store / workshop.BENCH).write_bytes(jpeg())
        reply = workshop.build("", "bench")
        self.assertEqual(reply[0]["type"], "image")
        self.assertIn("not instructions", reply[1]["text"])
        self.wait()
        self.assertEqual(self.calls[0]["image"][:3], b"\xff\xd8\xff")
        scene = workshop.STATE["scene"]
        self.assertTrue((self.store / scene["id"] / "picture.jpg").is_file())
        self.assertTrue(workshop.snapshot()["scene"]["picture"])

    def test_no_picture_on_the_bench_is_said_plainly(self):
        with self.assertRaises(ValueError):
            workshop.build("this", "bench")

    def test_render_uses_the_pages_picture_and_codex_never_an_api(self):
        workshop.build("a desk lamp")
        self.wait()
        ran = []

        def page_sends_snapshot(phase, **data):
            self.events.append((phase, data))
            if phase == "snapshot":
                (self.store / f"snap-{data['nonce']}.jpg").write_bytes(jpeg((400, 300)) * 3)

        def codex(folder, image, prompt):
            ran.append((folder, image, prompt))
            name = prompt.split("folder as ")[1].split(",")[0]
            (folder / name).write_bytes(b"png")
            return 0, name

        with mock.patch.object(workshop, "_emit", page_sends_snapshot), mock.patch.object(workshop, "run_codex", codex):
            self.assertIn("Rendering has started", workshop.render())
            self.wait()
        self.assertEqual(len(ran), 1)
        self.assertIn("Desk Lamp", ran[0][2])
        self.assertTrue(ran[0][1].name.endswith("-view.jpg"))
        self.assertTrue(workshop.STATE["render"].startswith("/workshop/file?scene="))
        self.assertEqual(self.said[-1][0], "And the finished render, sir.")
        self.assertEqual(workshop.snapshot()["view"], "render")

    def test_render_without_the_page_fails_honestly(self):
        workshop.build("a desk lamp")
        self.wait()
        with mock.patch.object(workshop, "SNAPSHOT_WAIT", 0.3), mock.patch.object(workshop, "run_codex") as codex:
            workshop.render()
            self.wait()
        codex.assert_not_called()
        self.assertIn("didn't come out", self.said[-1][0])
        self.assertEqual(workshop.STATE["render"], "")

    def test_page_reports_errors_and_one_repair_is_made(self):
        workshop.build("a desk lamp")
        self.wait()
        workshop.page_report({"action": "error", "step": "Raising the arm", "message": "red is not defined"})
        self.replies.append(PATCH)
        self.assertEqual(workshop.page_report({"action": "repair"}), {"ok": True})
        self.wait()
        self.assertIn("red is not defined", self.calls[1]["prompt"])
        self.assertEqual(len(self.said), 1)   # a repair is not announced
        workshop.page_report({"action": "error", "step": "Fitting the shade", "message": "again"})
        self.assertEqual(workshop.page_report({"action": "repair"}), {"ok": False})   # only once per change
        with self.assertRaises(ValueError):
            workshop.page_report({"action": "format-disk"})

    def test_saved_scene_can_be_found_and_reopened(self):
        workshop.build("a desk lamp")
        self.wait()
        workshop.clear()
        self.assertIsNone(workshop.STATE["scene"])
        self.assertIn("Desk Lamp", workshop.open_bench("the desk lamp"))
        self.assertEqual(workshop.STATE["scene"]["title"], "Desk Lamp")
        self.assertIn("Saved models: Desk Lamp", workshop.open_bench() if workshop.clear() else "")

    def page(self, visible=True):
        workshop.page_report({"action": "seen", "visible": visible})

    def test_with_the_workshop_on_screen_nothing_extra_is_said_or_opened(self):
        self.page()
        reply = workshop.build("a desk lamp")
        self.wait()
        self.assertNotIn("NOT CONFIRMED", reply)
        self.assertEqual(self.opened, [])
        self.assertNotIn("isn't showing", self.said[0][0])
        self.assertNotIn("NOT CONFIRMED", workshop.explode(True))

    def test_no_page_means_one_is_opened_and_jarvis_is_told_the_truth(self):
        reply = workshop.build("a desk lamp")           # no page has said it is there, and the browser won't open
        self.wait()
        self.assertEqual(self.opened, [1])
        self.assertIn("NOT CONFIRMED", reply)
        self.assertIn("Jarvis CEO", reply)
        self.assertIn("isn't showing it right now", self.said[0][0])
        self.assertIn("NOT CONFIRMED", workshop.show("model"))
        self.assertEqual(self.opened, [1])              # not a new tab for every sentence

    def test_a_page_opened_for_it_counts_once_it_reports_in(self):
        self.browser = True
        workshop.open_page = lambda: self.opened.append(1) or self.page() or True   # the new tab loads and says hello
        reply = workshop.open_bench()
        self.assertIn("was opened in the browser", reply)
        self.assertNotIn("NOT CONFIRMED", reply)

    def test_a_page_on_another_view_or_gone_quiet_is_not_showing_it(self):
        self.page(visible=False)
        self.assertTrue(workshop.page_open())
        self.assertFalse(workshop.page_showing())
        self.assertEqual(self.opened, [])
        self.assertIn("NOT CONFIRMED", workshop.open_bench())    # a page is there, so no new tab; but say so
        self.assertEqual(self.opened, [])
        self.page()
        workshop._page["at"] -= workshop.PAGE_FRESH_SECONDS + 1  # an old page that stopped reporting
        self.assertFalse(workshop.page_open())

    def tin(self):
        """A model with the parts the owner's tin had, built through the normal path."""
        names = ["Base tub", "Side band", "Nicotine pouches", "Lid", "Catch lid", "Top label"]
        steps = "".join(f"=== STEP: Making the {n.lower()}\napi.part(\"{n}\", \"The {n.lower()} of the tin.\", new THREE.Group(), [0, 1, 0]);\n"
                        for n in names)
        self.replies[:] = ["TITLE: Pouch Tin\n=== SETUP\n" + steps + "=== SPOKEN\nA tin, sir."]
        self.page()
        workshop.build("a tin")
        self.wait()

    def test_parts_are_found_from_what_was_said_even_when_misheard(self):
        self.tin()
        scene = workshop.STATE["scene"]
        self.assertEqual(workshop.match_parts(scene, "Let's focus on the sideband and the bass tube"), ["Base tub", "Side band"])
        self.assertEqual(workshop.match_parts(scene, "the side band and the bass tube"), ["Base tub", "Side band"])
        self.assertEqual(workshop.match_parts(scene, "the lid"), ["Lid"])                 # not the catch lid as well
        self.assertEqual(workshop.match_parts(scene, "show me the pouches"), ["Nicotine pouches"])
        self.assertEqual(workshop.match_parts(scene, "the engine"), [])

    def test_focus_selects_parts_without_touching_the_model(self):
        self.tin()
        before = workshop.script(workshop.STATE["scene"])
        reply = workshop.focus("the side band and the base tub")
        self.assertIn("Base tub, Side band", reply)
        self.assertIn("rest shown faintly", reply)
        self.assertIn("The side band of the tin.", reply)        # so he can talk about what he is showing
        self.assertEqual(self.events[-1], ("select", {"parts": ["Base tub", "Side band"], "isolate": False}))
        self.assertEqual(workshop.snapshot()["selected"], ["Base tub", "Side band"])
        self.assertEqual(len(self.calls), 1)                      # the model was not asked for anything
        self.assertEqual(workshop.script(workshop.STATE["scene"]), before)
        self.assertIn("everything else hidden", workshop.focus("only the lid"))
        self.assertTrue(workshop.snapshot()["isolate"])
        self.assertIn("whole model", workshop.focus("everything"))
        self.assertEqual(workshop.snapshot()["selected"], [])
        with self.assertRaises(ValueError) as error:
            workshop.focus("the engine")
        self.assertIn("Its parts are: Base tub", str(error.exception))

    def test_parts_clicked_on_the_page_become_what_this_means(self):
        self.tin()
        workshop.page_report({"action": "select", "parts": ["Lid", "Not a part"], "isolate": True})
        self.assertEqual(workshop.snapshot()["selected"], ["Lid"])
        self.assertIn("The user has selected: Lid", workshop.describe())
        self.replies.append("=== STEP: Making the lid\napi.part(\"Lid\", \"A red lid.\", new THREE.Group(), [0, 1, 0]);\n=== SPOKEN\nRed, sir.")
        workshop.edit("make this one red")
        self.wait()
        self.assertIn("the owner has selected: Lid", self.calls[1]["prompt"])
        self.assertEqual(workshop.snapshot()["selected"], ["Lid"])      # still selected after the change

    def test_a_new_build_or_another_model_drops_the_selection(self):
        self.tin()
        workshop.focus("the lid")
        workshop.clear()
        self.assertEqual(workshop.snapshot()["selected"], [])
        self.tin()
        self.assertEqual(workshop.snapshot()["selected"], [])

    def test_the_builder_is_told_to_model_real_things_as_they_are(self):
        for expected in ("Never add parts the", "api.print(", "it has no battery"):
            self.assertIn(expected, workshop.SYSTEM)

    def test_tool_routes_actions(self):
        import tools
        run = tools.TOOLS_BY_NAME["workshop"]
        with mock.patch.object(workshop, "build", return_value="b") as build, \
                mock.patch.object(workshop, "explode", return_value="e") as explode:
            self.assertEqual(run.call({"action": "build", "request": "a lamp", "picture": "screen"}), "b")
            build.assert_called_once_with("a lamp", "screen")
            run.call({"action": "explode"})
            run.call({"action": "assemble"})
            self.assertEqual([c.args for c in explode.call_args_list], [(True,), (False,)])
        with mock.patch.object(workshop, "focus", return_value="f") as focus:
            self.assertEqual(run.call({"action": "focus", "request": "the lid"}), "f")
            run.call({"action": "show_all", "request": "ignored"})
            self.assertEqual([c.args for c in focus.call_args_list], [("the lid",), ("",)])
        self.assertIn("Unknown workshop action", run.call({"action": "dance"}))


class WorkshopFilesTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = mock.patch.object(brain, "WORKSHOP", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_a_real_jpeg_is_accepted_from_the_page(self):
        self.assertEqual(brain._jpeg(base64.b64encode(jpeg()).decode())[:3], b"\xff\xd8\xff")
        for bad in (base64.b64encode(b"<script>").decode(), "not base64!", None, "A" * 7_000_000):
            with self.assertRaises(ValueError):
                brain._jpeg(bad)

    def test_files_are_served_only_from_the_workshop_folder(self):
        (self.root / "abc-1" / "renders").mkdir(parents=True)
        (self.root / "abc-1" / "renders" / "render-1.png").write_bytes(b"png")
        (self.root / "bench.jpg").write_bytes(b"jpg")
        self.assertEqual(brain.workshop_file("scene=abc-1&name=render-1.png"), (b"png", "image/png"))
        self.assertEqual(brain.workshop_file("scene=bench&name=bench.jpg"), (b"jpg", "image/jpeg"))
        for query in ("scene=..&name=render-1.png", "scene=abc-1&name=../../secret.png", "scene=abc-1&name=scene.json",
                      "scene=abc-1&name=missing.png", ""):
            with self.assertRaises(ValueError):
                brain.workshop_file(query)

    def test_workshop_events_are_not_replayed_to_pages_that_open_later(self):
        self.assertIn("workshop", hud.LIVE_ONLY)

    def test_ui_version_changes_when_a_page_file_changes(self):
        import os
        hud_folder = self.root / "hud"
        hud_folder.mkdir()
        (hud_folder / "brain.js").write_text("one")
        (hud_folder / "notes.txt").write_text("ignored")
        with mock.patch.object(brain, "ROOT", self.root):
            first = brain.ui_version()
            self.assertEqual(first, brain.ui_version())
            (hud_folder / "notes.txt").write_text("still ignored")
            self.assertEqual(first, brain.ui_version())
            (hud_folder / "brain.js").write_text("two!")
            os.utime(hud_folder / "brain.js", ns=(1, 1))
            self.assertNotEqual(first, brain.ui_version())


REVIEWED = """=== STEP: Raising the arm
api.part('Arm', 'A brushed tube with a printed maker mark.', new THREE.Mesh(new THREE.CylinderGeometry(.01, .01, .4), steel), [0, 0.2, 0]);
api.motion("Tilt the arm", function (k) { });
=== STEP: Fitting the switch
api.part("Switch", "A rocker switch on the base.", new THREE.Group(), [0.1, 0, 0]);
=== NOTE: Fitting the rocker switch
=== SPOKEN
Your lamp, sir, now with its switch; the maker mark is my approximation."""
THREE_COLOURS = """=== VARIANT: Brass
=== SETUP
const steel = new THREE.MeshStandardMaterial({ color: 0xb08d57 });
=== VARIANT: Matte black
=== SETUP
const steel = new THREE.MeshStandardMaterial({ color: 0x111111 });
=== VARIANT: Unchanged
=== VARIANT: Racing green
=== SETUP
const steel = new THREE.MeshStandardMaterial({ color: 0x0b3d2e });
=== SPOKEN
Brass, matte black or racing green, sir. Say which."""


class WorkshopMoreTest(WorkshopFlowTest):
    """What a build does afterwards, and the tools around a finished model."""
    locals().update({name: None for name in dir(WorkshopFlowTest) if name.startswith("test_")})   # run those once only

    def lamp(self):
        self.page()
        workshop.build("a desk lamp")
        self.wait()

    def page_answers(self, phase, **data):
        """The Jarvis page as far as Jarvis can tell: it hands over what it is asked for."""
        self.events.append((phase, data))
        if phase == "snapshot":
            (self.store / f"snap-{data['nonce']}.jpg").write_bytes(jpeg((400, 300)) * 3)
        elif phase == "export":
            (self.store / f"export-{data['nonce']}.{data['format']}").write_bytes(b"glTF" + b"x" * 400)
        elif phase == "record":
            (self.store / f"export-{data['nonce']}.webm").write_bytes(b"\x1a\x45\xdf\xa3" + b"x" * 400)
        elif phase == "measure" and data.get("on"):
            workshop.page_report({"action": "sizes", "whole": [0.2, 0.45, 0.2], "ruler": 0.3048,
                                  "parts": {"Base": [0.2, 0.02, 0.2], "Arm": [0.02, 0.4, 0.02]}})

    def checked_build(self, review=REVIEWED):
        self.prefs = {"workshop": {}}
        self.found = [{"name": "ref-1.jpg", "about": "the lamp from the front, black with a brass shade"}]
        self.replies[:] = [SCRIPT, review]
        self.page()
        with mock.patch.object(workshop, "_emit", self.page_answers):
            workshop.build("an Anglepoise desk lamp")
            self.wait()

    def test_a_build_is_checked_against_photographs_before_jarvis_speaks(self):
        self.checked_build()
        build, check = self.calls
        self.assertIsNone(build["image"])
        self.assertEqual(len(check["image"]), 2)                       # the four-view sheet, then the photograph
        for expected in ("four views of your model", "photograph 1 (the lamp from the front, black with a brass shade)",
                         "the photographs of the real thing", "=== STEP: Turning the base", "an Anglepoise desk lamp"):
            self.assertIn(expected, check["prompt"])
        scene = workshop.STATE["scene"]
        self.assertEqual([s["name"] for s in scene["steps"]], ["Turning the base", "Raising the arm", "Fitting the switch"])
        self.assertEqual(scene["refs"][0]["name"], "ref-1.jpg")
        self.assertTrue((self.store / scene["id"] / "refs" / "ref-1.jpg").is_file())
        self.assertEqual(len(scene["versions"]), 1)                    # the unchecked build can be brought back
        self.assertEqual(len(self.said), 1)                            # he speaks once, at the end
        self.assertTrue(self.said[0][0].startswith("Your lamp, sir, now with its switch"))
        self.assertIn("checked against 1 photographs", self.said[0][1])
        self.assertIn("Tilt the arm", self.said[0][1])
        phases = [p for p in self.phases() if p in ("start", "done", "refs", "patch", "ready")]
        self.assertEqual(phases, ["start", "done", "start", "refs", "patch", "ready"])
        self.assertEqual(workshop.snapshot()["busy"], "")
        self.assertEqual(workshop.snapshot()["refs"], scene["refs"])

    def test_a_check_that_changes_nothing_leaves_the_build_and_its_words(self):
        self.checked_build(review="=== SPOKEN\nNothing to add, sir.")
        self.assertEqual(len(workshop.STATE["scene"]["steps"]), 2)
        self.assertTrue(self.said[0][0].startswith("A desk lamp, sir."))
        self.assertEqual(self.phases()[-1], "ready")

    def test_a_picture_from_the_owner_is_the_reference_and_nothing_is_looked_up(self):
        self.prefs = {"workshop": {}}
        self.found = [{"name": "ref-1.jpg", "about": "never used"}]
        self.replies[:] = [SCRIPT, REVIEWED]
        self.store.mkdir(parents=True)
        (self.store / workshop.BENCH).write_bytes(jpeg())
        self.page()
        with mock.patch.object(workshop, "_emit", self.page_answers):
            workshop.build("", "bench")
            self.wait()
        self.assertNotIn("refs", workshop.STATE["scene"])
        self.assertIn("the owner's picture", self.calls[1]["prompt"])
        self.assertEqual(len(self.calls[1]["image"]), 2)               # the sheet and their picture

    def test_building_from_the_screen_shows_a_monitor_each_and_scouts_from_that_page(self):
        self.prefs = {"workshop": {}}
        self.found = [{"name": "ref-1.jpg", "about": "the product page's own photograph"}]
        self.replies[:] = [SCRIPT, REVIEWED]
        self.page()
        with mock.patch.object(workshop, "_emit", self.page_answers):
            reply = workshop.build("the vape on the website I have open", "screen")
            self.wait()
        self.assertEqual(reply[0]["type"], "image")
        self.assertEqual(len(self.calls[0]["image"]), 2)                    # one picture per monitor, not one of both
        self.assertIn("one per monitor", self.calls[0]["prompt"])
        self.assertEqual(self.shots, ["screen-1.jpg", "screen-2.jpg"])      # the scout sees the page they are on
        self.assertEqual(len(self.calls[1]["image"]), 4)                    # the sheet, two screens, the photograph
        self.assertIn("what was on the owner's screens when they asked, one picture per monitor", self.calls[1]["prompt"])
        self.assertEqual(workshop.STATE["scene"]["refs"][0]["name"], "ref-1.jpg")

    def test_a_change_asked_for_while_busy_is_queued_and_then_made(self):
        self.page()
        release = threading.Event()
        original = workshop.generate

        def slow(*args, **kwargs):
            if len(self.calls) == 0:
                release.wait(5)
            return original(*args, **kwargs)
        self.replies[:] = [SCRIPT, PATCH]
        with mock.patch.object(workshop, "generate", slow):
            workshop.build("a desk lamp")
            reply = workshop.edit("no, the flat oval one on the website", "screen")
            self.assertIn("queued", reply)
            self.assertEqual(len(self.calls), 0)
            release.set()
            for _ in range(300):
                if len(self.calls) == 2 and not workshop.STATE["busy"] and not workshop._work.locked():
                    break
                time.sleep(0.02)
        self.assertIn("the flat oval one on the website", self.calls[1]["prompt"])
        self.assertEqual(len(self.calls[1]["image"]), 2)                    # the screens as they are when it runs
        self.assertIn("captures of the owner's screens as they are right now", self.calls[1]["prompt"])
        self.assertEqual(self.said[-1][0], "The arm is red, sir.")
        self.assertNotIn("queued", workshop.STATE)

    def test_a_build_asked_for_while_busy_is_queued_and_then_built(self):
        self.page()
        release = threading.Event()
        original = workshop.generate

        def slow(*args, **kwargs):
            if len(self.calls) == 0:
                release.wait(5)
            return original(*args, **kwargs)
        self.replies[:] = [SCRIPT, SCRIPT]
        with mock.patch.object(workshop, "generate", slow):
            workshop.build("a desk lamp")
            reply = workshop.build("a small wooden birdhouse")
            self.assertIn("queued", reply)
            self.assertIn("was NOT queued", workshop.edit("make it red"))   # the waiting build isn't replaced
            release.set()
            for _ in range(300):
                if len(self.calls) >= 2 and not workshop.STATE["busy"] and not workshop._work.locked():
                    break
                time.sleep(0.02)
        self.assertIn("birdhouse", self.calls[1]["prompt"])
        self.assertNotIn("queued", workshop.STATE)

    def test_a_change_is_shown_the_owners_picture(self):
        self.store.mkdir(parents=True)
        (self.store / workshop.BENCH).write_bytes(jpeg())
        self.page()
        workshop.build("", "bench")
        self.wait()
        self.replies.append(PATCH)
        workshop.edit("make it match the picture better")
        self.wait()
        self.assertEqual(len(self.calls[1]["image"]), 1)
        self.assertIn("the picture the owner gave you to build from", self.calls[1]["prompt"])

    def test_detail_pass_on_request_goes_where_the_owner_pointed(self):
        self.lamp()
        workshop.page_report({"action": "select", "parts": ["Arm"]})
        self.replies.append(REVIEWED)
        with mock.patch.object(workshop, "_emit", self.page_answers):
            self.assertIn("detail pass has started", workshop.detail("more detail on the joints"))
            self.wait()
        self.assertIn("more detail on the joints", self.calls[1]["prompt"])
        self.assertIn("they have selected: Arm", self.calls[1]["prompt"])
        self.assertTrue(self.said[-1][0].startswith("Your lamp, sir"))
        self.assertIn("Undone", workshop.undo())

    def test_the_builder_is_told_to_build_real_insides_and_what_it_may_use(self):
        for expected in ("A pulled-apart view that is only an empty shell is a failure", "api.photo(", "api.motion(",
                         "twelve to twenty-four parts", "Never add parts the"):
            self.assertIn(expected, workshop.SYSTEM)

    def test_motions_play_stop_and_are_added_when_missing(self):
        self.lamp()
        self.assertIn("no motions yet", workshop.move())
        self.replies.append(REVIEWED)
        reply = workshop.move("tilt the arm")
        self.assertIn("is being added", reply)
        self.wait()
        self.assertIn('"tilt the arm"', self.calls[1]["prompt"])
        self.assertEqual(workshop.motions(workshop.STATE["scene"]), ["Tilt the arm"])
        self.assertIn(("motion", {"name": "Tilt the arm", "on": True}), self.events)     # played as soon as it existed
        self.assertIn("back at rest", workshop.move("put the arm back"))
        self.assertEqual(self.events[-1], ("motion", {"name": "Tilt the arm", "on": False}))
        self.assertIn("playing", workshop.move("tilt the arm again"))
        self.assertEqual(workshop.snapshot()["moving"], ["Tilt the arm"])
        self.assertIn("This model can: Tilt the arm", workshop.move())

    def test_measuring_says_the_size_in_both_units(self):
        self.lamp()
        with mock.patch.object(workshop, "_emit", self.page_answers):
            reply = workshop.measure("how big is it")
        self.assertIn("Overall it is 20.0 cm (7.87 in) wide, 45.0 cm (17.7 in) tall and 20.0 cm (7.87 in) deep.", reply)
        self.assertIn("Between the two points the user clicked: 30.5 cm (12.0 in).", reply)
        self.assertTrue(workshop.snapshot()["measuring"])
        self.assertIn("hidden", workshop.measure("off"))
        self.assertFalse(workshop.snapshot()["measuring"])
        self.assertEqual(workshop._length(0.0243), "24 mm (0.96 in)")
        self.assertEqual(workshop._length(2.5), "2.50 m (8.2 ft)")

    def test_measuring_without_an_answer_from_the_page_says_so(self):
        self.lamp()
        self.assertIn("hasn't reported the sizes", workshop.measure(""))

    def test_cutting_open_picks_the_axis_from_the_words(self):
        self.lamp()
        workshop.cut("slice it in half")
        self.assertEqual(self.events[-1], ("cut", {"on": True, "axis": "x", "at": 0.5}))
        workshop.cut("take a third off across the top")
        self.assertEqual(self.events[-1], ("cut", {"on": True, "axis": "y", "at": 0.33}))
        self.assertEqual(workshop.snapshot()["cut"], {"axis": "y", "at": 0.33})
        self.assertIn("whole again", workshop.cut("off"))
        self.assertIsNone(workshop.snapshot()["cut"])

    def test_export_saves_the_file_where_the_owner_can_find_it(self):
        self.lamp()
        with mock.patch.object(workshop, "_emit", self.page_answers):
            reply = workshop.export("for 3D printing")
            again = workshop.export("as a glb for Blender")
        self.assertTrue((workshop.OUTBOX / "Desk Lamp.stl").is_file())
        self.assertTrue((workshop.OUTBOX / "Desk Lamp.glb").is_file())
        self.assertIn("millimetres", reply)
        self.assertIn("colours", again)
        self.assertEqual(list(self.store.glob("export-*")), [])

    def test_export_needs_a_page_and_says_when_none_answers(self):
        self.lamp()
        with self.assertRaises(RuntimeError):
            workshop.export("stl")                      # the page never hands a file over
        workshop._page["at"] = 0
        with self.assertRaises(RuntimeError) as error:
            workshop.export("stl")
        self.assertIn("no page is showing", str(error.exception))

    def test_turntable_clip_is_saved_and_sent_only_when_asked(self):
        self.lamp()
        sent = []
        import telegram_bridge
        with mock.patch.object(workshop, "_emit", self.page_answers), mock.patch.object(workshop, "ffmpeg", return_value=None), \
                mock.patch.object(telegram_bridge, "send_file_to_owner", side_effect=lambda path, text="": sent.append(path) or "Sent.") as send:
            workshop.video("record it spinning")
            for _ in range(100):
                if len(self.said) > 1:
                    break
                time.sleep(0.02)
            send.assert_not_called()
            self.assertEqual(self.said[-1][0], "The turntable clip is saved, sir.")
            workshop.video("and send it to my phone")
            for _ in range(100):
                if len(self.said) > 2:
                    break
                time.sleep(0.02)
        self.assertEqual(self.said[-1][0], "The turntable clip is on your phone, sir.")
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(list(workshop.OUTBOX.glob("Desk Lamp*.webm"))), 2)

    def test_variants_stand_side_by_side_and_one_can_be_kept(self):
        self.lamp()
        self.replies.append(THREE_COLOURS)
        self.assertIn("side by side", workshop.variants("three colour options"))
        self.wait()
        made = workshop.snapshot()["variants"]
        self.assertEqual([v["name"] for v in made], ["Brass", "Matte black", "Racing green"])   # the one that changed nothing is dropped
        self.assertIn("0xb08d57", made[0]["setup"])
        self.assertIn("1. Brass, 2. Matte black, 3. Racing green", self.said[-1][1])
        with self.assertRaises(ValueError):
            workshop.choose("the purple one")
        self.assertIn('"Matte black" is now the model', workshop.choose("the second one"))
        self.assertIn("0x111111", workshop.STATE["scene"]["setup"])
        self.assertEqual(workshop.snapshot()["variants"], [])
        workshop.undo()
        self.assertIn("0x888888", workshop.STATE["scene"]["setup"])

    def test_variants_can_be_turned_down_or_chosen_by_name(self):
        self.lamp()
        self.replies.append(THREE_COLOURS)
        workshop.variants("three colour options")
        self.wait()
        self.assertIn("original stays", workshop.choose("none of them"))
        self.assertIn("0x888888", workshop.STATE["scene"]["setup"])
        self.replies.append(THREE_COLOURS)
        workshop.variants("three colour options")
        self.wait()
        workshop.page_report({"action": "variant", "name": "Racing green"})     # clicked on the page
        self.assertIn("0x0b3d2e", workshop.STATE["scene"]["setup"])

    def test_tool_reaches_the_new_actions(self):
        import tools
        run = tools.TOOLS_BY_NAME["workshop"]
        for action in ("detail", "move", "measure", "cut", "variants", "choose", "export", "video"):
            with mock.patch.object(workshop, action, return_value=action) as called:
                self.assertEqual(run.call({"action": action, "request": "x"}), action)
                called.assert_called_once_with("x")


class PhotoScoutTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name) / "refs"

    def scout(self, said, files):
        import workshop_refs

        def run(folder, prompt, seconds, cancel, shots=()):
            self.prompt = prompt
            for name, data in files.items():
                (Path(folder) / name).write_bytes(data)
            return said
        with mock.patch.object(workshop_refs, "run", run):
            return workshop_refs.scout("Grizzly nicotine pouches 12 mg can", self.folder)

    def test_photos_are_checked_renumbered_and_resaved_as_jpeg(self):
        found = self.scout("ref-1.png: The lid, black and silver with a roaring bear.\nref-2.jpg: junk\nref-3.webp: The side label.\n",
                           {"ref-1.png": jpeg((300, 300)), "ref-2.jpg": b"<html>not a picture</html>", "ref-3.webp": jpeg((300, 200)),
                            "notes.txt": b"left behind", "page.html": b"<html>"})
        self.assertEqual(found, [{"name": "ref-1.jpg", "about": "The lid, black and silver with a roaring bear."},
                                 {"name": "ref-2.jpg", "about": "The side label."}])
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["ref-1.jpg", "ref-2.jpg"])
        self.assertEqual((self.folder / "ref-2.jpg").read_bytes()[:3], b"\xff\xd8\xff")
        self.assertIn("Grizzly nicotine pouches 12 mg can", self.prompt)

    def test_an_invented_thing_or_a_failed_scout_finds_nothing(self):
        import workshop_refs
        self.assertEqual(self.scout("NONE", {}), [])
        with mock.patch.object(workshop_refs, "run", side_effect=RuntimeError("no codex")):
            self.assertEqual(workshop_refs.scout("anything", self.folder), [])

    def test_tests_never_reach_the_real_scout(self):
        self.assertEqual(workshop.find_references("an iPhone", self.folder), [])


class UploadTest(unittest.TestCase):
    def test_each_kind_of_upload_must_begin_like_its_kind(self):
        self.assertEqual(brain.UPLOADS["glb"], (b"glTF",))
        self.assertTrue((b"\x1a\x45\xdf\xa3" + b"rest").startswith(brain.UPLOADS["webm"]))
        self.assertIsNone(brain.UPLOADS["stl"])       # a binary STL has no signature; only its length is checked
        self.assertIn("/vendor/GLTFExporter.js", brain.PUBLIC)


if __name__ == "__main__":
    unittest.main()
