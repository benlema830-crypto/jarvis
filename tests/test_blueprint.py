import copy
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import blueprint as bp
import tools
import workshop

RAW = {
    "title": "Test Gantry", "summary": "A frame with a motor.", "units_shown": "inch",
    "scale_basis": "2020 extrusion is 20 mm.",
    "parts": [
        {"id": "base", "name": "Base plate", "group": "Frame", "shape": "box", "size": [400, 300, 12], "at": [0, 0, 6],
         "material": "plywood", "colour": "#c8a26b", "sizes_from": "photo-estimate", "confidence": 0.4,
         "holes": [{"diameter": 6, "at": [150, 100, 0], "axis": "z"}]},
        {"id": "post", "name": "Upright", "group": "Frame", "shape": "box", "size": [20, 20, 300], "at": [-180, 0, 162],
         "material": "2020 aluminium extrusion", "sizes_from": "standard", "confidence": 0.8},
        {"id": "post", "name": "Upright", "group": "Frame", "shape": "box", "size": [20, 20, 300], "at": [180, 0, 162],
         "material": "2020 aluminium extrusion", "sizes_from": "standard", "confidence": 0.8},
        {"id": "roller", "name": "Roller", "group": "Drive", "shape": "tube", "diameter": 30, "inner_diameter": 22,
         "length": 60, "axis": "x", "at": [0, 0, 27], "rotate": [0, 0, 30], "material": "PLA"},
        {"id": "screws", "name": "M5 screw", "group": "Hardware", "shape": "none", "qty": 12, "mass_g": 3},
        {"id": "pi", "name": "Raspberry Pi 5", "group": "Electronics", "status": "new", "shape": "box",
         "size": [85, 56, 20], "at": [100, 50, 22], "cost": 80, "mass_g": 46, "volts": 5, "watts": 12},
        {"id": "psu", "name": "Supply", "group": "Electronics", "status": "new", "shape": "box", "size": [129, 98, 38],
         "at": [-100, 60, 31], "cost": 22, "supply_watts": 100},
        {"name": "Junk", "shape": "pyramid", "size": ["a", None, 5], "at": [float("nan"), 0, 0], "status": "weird",
         "confidence": 7},
    ],
    "measurements": [
        {"letter": "A", "what": "base width", "estimate_mm": 400, "part": "base", "axis": "x", "photo": 1,
         "line": [0.1, 0.8, 0.9, 0.8]},
        {"letter": "a", "what": "duplicate letter"},
        {"letter": "B", "what": "roller length", "estimate_mm": 60, "part": "roller", "axis": "length"},
        {"letter": "C", "what": "points at a part that isn't there", "part": "ghost", "axis": "x"},
    ],
    "unknowns": ["underneath"],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [mock.patch.object(bp, "STORE", root / "bp"), mock.patch.object(bp, "OUTBOX", root / "out")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def project(self, raw=RAW, photo=True):
        spec = bp.tidy(copy.deepcopy(raw), keep={"id": "test-gantry"})
        folder = bp.STORE / "test-gantry" / "photos"
        folder.mkdir(parents=True, exist_ok=True)
        if photo:
            from PIL import Image
            Image.new("RGB", (400, 300), (90, 90, 90)).save(folder / "01.jpg")
        return bp.save(spec)


class TidyTests(Base):
    def test_makes_a_safe_spec_from_untidy_output(self):
        spec = bp.tidy(copy.deepcopy(RAW), keep={"id": "x"})
        ids = [p["id"] for p in spec["parts"]]
        self.assertEqual(len(ids), len(set(ids)))                         # duplicate ids made unique
        junk = spec["parts"][-1]
        self.assertEqual((junk["shape"], junk["status"], junk["size"], junk["at"], junk["confidence"]),
                         ("box", "existing", [10, 10, 10], [0, 0, 0], 0.5))
        self.assertEqual([m["letter"] for m in spec["measurements"]], ["A", "B", "C"])
        self.assertNotIn("part", spec["measurements"][2])                  # a part that isn't there is dropped
        self.assertEqual(spec["parts"][3]["inner_diameter"], 22)
        self.assertEqual(spec["parts"][5]["make"], "buy")

    def test_extract_json_survives_prose_and_trailing_commas(self):
        self.assertEqual(bp.extract_json('Here:\n```json\n{"a": [1, 2,],}\n```'), {"a": [1, 2]})
        with self.assertRaises(ValueError):
            bp.extract_json("no spec here")

    def test_keeps_measured_values_through_a_revision(self):
        spec = bp.tidy(copy.deepcopy(RAW), keep={"id": "x"})
        spec["measurements"][0]["value_mm"] = 410
        again = bp.tidy({"parts": RAW["parts"], "measurements": [{"letter": "A", "what": "base width"}]}, keep=spec)
        self.assertEqual(again["measurements"][0]["value_mm"], 410)


class MeasureTests(Base):
    def test_parses_the_ways_people_say_sizes(self):
        found = bp.parse_measurements("A is 24 1/2 in, B: 61 cm, C 2 ft 3 in, D=31, E 1.2 m, F 3/4\"", "inch")
        self.assertAlmostEqual(found["A"], 622.3)
        self.assertEqual(found["B"], 610)
        self.assertAlmostEqual(found["C"], 685.8)
        self.assertAlmostEqual(found["D"], 787.4)
        self.assertEqual(found["E"], 1200)
        self.assertAlmostEqual(found["F"], 19.05)
        self.assertEqual(bp.parse_measurements("a is 610mm and b is 2.5 inches"), {"A": 610, "B": 63.5})
        self.assertEqual(bp.parse_measurements("A 300", "mm"), {"A": 300})

    def test_a_measurement_sets_its_part_and_unknown_letters_are_refused(self):
        spec = bp.tidy(copy.deepcopy(RAW), keep={"id": "x"})
        bp.apply_measurements(spec, {"A": 410, "B": 75})
        parts = {p["id"]: p for p in spec["parts"]}
        self.assertEqual(parts["base"]["size"][0], 410)
        self.assertEqual(parts["roller"]["length"], 75)
        self.assertEqual((parts["base"]["sizes_from"], parts["base"]["confidence"]), ("measured", 0.95))
        with self.assertRaises(ValueError):
            bp.apply_measurements(spec, {"Z": 3})


class CheckTests(Base):
    def test_clashes_floating_power_cost_and_guesses(self):
        raw = copy.deepcopy(RAW)
        raw["parts"].append({"id": "hover", "name": "Hovering box", "shape": "box", "size": [10, 10, 10], "at": [0, -140, 200]})
        raw["parts"].append({"id": "inside", "name": "Clashing box", "shape": "box", "size": [50, 50, 50], "at": [-180, 0, 100]})
        c = bp.checks(bp.tidy(raw, keep={"id": "x"}))
        self.assertIn("Hovering box", [f["name"] for f in c["floating"]])
        self.assertIn(("Upright", "Clashing box"), [(x["a"], x["b"]) for x in c["clashes"]])
        self.assertEqual(c["power"], {"draw_w": 12, "supply_w": 100, "ok": True})
        self.assertEqual(c["cost_usd"], 102)
        self.assertIn("Base plate", [g["name"] for g in c["guesses"]])
        self.assertEqual(c["open_measurements"], ["A", "B", "C"])
        self.assertEqual(c["overall_mm"][0], 405)   # the clashing box sticks out 5 mm

    def test_a_part_meant_to_pass_through_is_not_a_clash(self):
        raw = copy.deepcopy(RAW)
        raw["parts"].append({"id": "shaft", "name": "Shaft", "shape": "cylinder", "diameter": 8, "length": 100,
                             "axis": "x", "at": [-180, 0, 100], "passes_through": ["post", "ghost"]})
        spec = bp.tidy(raw, keep={"id": "x"})
        self.assertEqual(spec["parts"][-1]["passes_through"], ["post"])
        self.assertNotIn("Shaft", [x["b"] for x in bp.checks(spec)["clashes"]])
        del spec["parts"][-1]["passes_through"]
        self.assertIn("Shaft", [x["b"] for x in bp.checks(spec)["clashes"]])

    def test_rotation_moves_the_bounds(self):
        part = {"shape": "box", "size": [100, 10, 10], "at": [0, 0, 0], "rotate": [0, 0, 90]}
        lo, hi = bp.box(part)
        self.assertAlmostEqual(hi[0] - lo[0], 10)
        self.assertAlmostEqual(hi[1] - lo[1], 100)

    def test_parts_list_counts_identical_pieces(self):
        rows = bp.bill(bp.tidy(copy.deepcopy(RAW), keep={"id": "x"}))
        upright = next(r for r in rows if r["name"] == "Upright")
        self.assertEqual(upright["qty"], 2)
        self.assertEqual(next(r for r in rows if r["name"] == "M5 screw")["qty"], 12)
        self.assertEqual(rows[-1]["status"], "new")


class OutputTests(Base):
    def test_fusion_script_is_valid_python_and_carries_the_spec(self):
        spec = bp.tidy(copy.deepcopy(RAW), keep={"id": "test-gantry"})
        script = bp.fusion_script(spec, "C:/out")
        compile(script, "fusion", "exec")
        encoded = script.split('b64decode("')[1].split('"')[0]
        import base64
        data = json.loads(base64.b64decode(encoded))
        self.assertEqual(data["project"], "test-gantry")
        self.assertTrue(data["inches"])
        self.assertEqual(next(p for p in data["parts"] if p["id"] == "pi")["colour"], bp.STATUS_COLOUR["new"])

    def test_preview_is_a_workshop_scene_with_every_shaped_part(self):
        spec = bp.tidy(copy.deepcopy(RAW), keep={"id": "x"})
        scene = bp.preview_scene(spec)
        names = [n for n, _ in workshop.parts({"steps": scene["steps"]})]
        self.assertIn("Raspberry Pi 5", names)
        self.assertNotIn("M5 screw", names)
        self.assertIn("const shape", scene["setup"])

    def test_packet_writes_everything_the_owner_builds_from(self):
        spec = self.project()
        spec["plan"] = {"goal": "AI sorter", "summary": "Adds a Pi.", "wiring": [{"from": "PSU", "to": "Pi", "what": "5 V"}],
                        "steps": ["Mount it"], "risks": ["<pinch>"]}
        out = bp.packet(spec)
        files = sorted(p.name for p in out.iterdir())
        for name in ("build-packet.html", "parts-list.csv", "parts-list.xlsx", "spec.json", "measure-photo-1.jpg"):
            self.assertIn(name, files)
        page = (out / "build-packet.html").read_text(encoding="utf-8")
        self.assertIn("Raspberry Pi 5", page)
        self.assertIn("&lt;pinch&gt;", page)                 # text from the model is escaped
        self.assertIn("Mount it", page)


class FlowTests(Base):
    def setUp(self):
        super().setUp()
        self.said = []
        self.done = threading.Event()
        extra = [mock.patch.object(bp, "_announce", side_effect=lambda s, n: (self.said.append((s, n)), self.done.set())),
                 mock.patch.object(bp, "show_on_bench", return_value=""),
                 mock.patch("fusion_link.available", return_value=False)]
        for p in extra:
            p.start()
        self.patches += extra

    def wait(self):
        self.assertTrue(self.done.wait(10), "the background job didn't finish")
        self.done.clear()

    def test_new_project_from_a_folder_of_photos(self):
        folder = Path(self.tmp.name) / "photos"
        folder.mkdir()
        from PIL import Image
        Image.new("RGB", (900, 600), (10, 120, 10)).save(folder / "a.png")
        with mock.patch.object(bp, "ask", return_value=copy.deepcopy(RAW)) as ask:
            reply = bp.start(str(folder), "my college machine")
            self.wait()
        self.assertIn("Reading 1 photo", reply)
        self.assertEqual(len(ask.call_args[0][2]), 1)
        spec = bp.load()
        self.assertEqual(spec["title"], "Test Gantry")
        self.assertIn("3 measurements to take", self.said[0][0])
        self.assertIn("Fusion isn't running", self.said[0][1])
        self.assertTrue((bp.outbox(spec) / "build-packet.html").is_file())

    def test_measurements_are_recorded_then_the_spec_is_reworked(self):
        self.project()
        revised = copy.deepcopy(RAW)
        revised["parts"][1]["size"][2] = 320
        with mock.patch.object(bp, "ask", return_value=revised) as ask:
            reply = tools.TOOLS_BY_NAME["blueprint"].call({"action": "measure", "request": "A is 16 1/8 in"})
            self.wait()
        self.assertIn("A 16 1/8 in", reply)
        self.assertIn("A (base width) = 409.57 mm", ask.call_args[0][1])
        spec = bp.load()
        self.assertEqual(spec["parts"][0]["size"][0], 409.57)     # the real number survives the rework
        self.assertEqual(spec["parts"][1]["size"][2], 320)
        self.assertIn("Still to measure: B, C", self.said[0][0])

    def test_upgrade_adds_a_plan_and_a_failure_is_spoken(self):
        self.project()
        upgraded = copy.deepcopy(RAW)
        upgraded["plan"] = {"summary": "Camera and Pi."}
        with mock.patch.object(bp, "ask", return_value=upgraded):
            bp.upgrade("an AI robot")
            self.wait()
        self.assertEqual(bp.load()["plan"]["goal"], "an AI robot")
        self.assertIn("new parts", self.said[-1][0])
        with mock.patch.object(bp, "ask", side_effect=ValueError("The model didn't return a spec.")):
            bp.revise("the arm is on the left")
            self.wait()
        self.assertIn("didn't finish", self.said[-1][0])

    def test_undo_and_status(self):
        spec = self.project()
        spec["title"] = "Renamed"
        bp.save(spec, "rename")
        self.assertIn("Took back", bp.undo())
        self.assertEqual(bp.load()["title"], "Test Gantry")
        self.assertIn("To measure: A", bp.status())

    def test_needs_photos(self):
        with self.assertRaises(ValueError):
            tools.TOOLS_BY_NAME["blueprint"].call({"action": "new", "request": "my machine"})


if __name__ == "__main__":
    unittest.main()
