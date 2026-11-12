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


class WorkshopFlowTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Path(temp.name) / "workshop"
        self.events, self.said, self.replies = [], [], [SCRIPT]
        self.opened, self.browser = [], False
        self.calls = []
        fresh = {"open": False, "busy": "", "scene": None, "exploded": False, "view": "model", "thinking": "",
                 "started": 0.0, "seconds": 0, "tokens": 0, "done": [], "notes": [], "error": "", "errors": [],
                 "render": "", "model": ""}

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
                (workshop.preferences, "read", lambda: {})]:
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def wait(self):
        for _ in range(200):
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

    def test_a_second_job_while_one_runs_is_not_started(self):
        workshop._work.acquire()
        self.addCleanup(lambda: workshop._work.locked() and workshop._work.release())
        self.assertIn("still busy", workshop.build("a chair"))
        self.assertEqual(self.calls, [])

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


if __name__ == "__main__":
    unittest.main()
