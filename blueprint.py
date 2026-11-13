"""Blueprints: a real thing, from photographs to a CAD model the owner can build from and change.

The workshop (workshop.py) sketches anything in three.js for looking at. A blueprint is for building: every size
is in millimetres, every part is one physical piece with its material and how it is made or bought, and one file
(spec.json) is the single source of truth that everything else is produced from.

    photos ─▶ read (Fable looks at them: parts, sizes scaled from things of known size, how sure it is,
              and the few measurements that would pin down the rest, drawn on the photos as A, B, C...)
          ─▶ measure ("A is 610 mm") ─▶ revise (Fable reworks the whole spec around the real numbers)
          ─▶ cad (a new Fusion design built from the spec: a component per part, grouped; STEP and pictures)
          ─▶ check (the Fusion pictures go back to Fable beside the photos; what disagrees is fixed)
          ─▶ upgrade ("turn it into an AI robot": real parts with datasheet sizes, brackets to make, what has
              to change, wiring, power, software, build steps, risks; NEW and CHANGE parts in their own colour)
          ─▶ packet (Documents\\Jarvis Blueprints\\<name>\\: build packet HTML + PDF, parts list CSV + XLSX,
              measuring sheet, Fusion pictures, STEP)

The bench preview (the same parts on the Workshop tab of the Jarvis page) is made from the spec directly, with no
model call, so "pull it apart" and "measure it" work on it straight away.

Projects live in data/blueprints/<id>/: photos/, spec.json, versions/ (for undo), fusion/ (pictures, STEP).
Fable runs through Claude Code on the owner's plan (workshop.generate); Fusion through its MCP (fusion_link).
"""
import base64
import csv
import datetime
import io
import json
import math
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import preferences

HERE = Path(__file__).resolve().parent
STORE = HERE / "data" / "blueprints"
OUTBOX = Path.home() / "Documents" / "Jarvis Blueprints"
MAX_PHOTOS = 20
MAX_VERSIONS = 20
PHOTO_SIDE = 1600
SHAPES = ("box", "cylinder", "tube", "sphere", "cone", "none")
STATUSES = ("existing", "new", "change", "remove")
MAKES = ("existing", "buy", "3d print", "laser", "cnc", "saw", "drill", "weld", "bend", "sew", "other")
SOURCES = ("measured", "datasheet", "standard", "photo-estimate", "guess")
STATUS_COLOUR = {"new": "#22c3d6", "change": "#f2a33a"}
DENSITY = {  # kg per cubic metre, for a weight estimate when a part has no mass of its own
    "steel": 7850, "stainless": 8000, "iron": 7200, "aluminium": 2700, "aluminum": 2700, "brass": 8500,
    "copper": 8960, "titanium": 4500, "plywood": 600, "mdf": 750, "hardwood": 700, "oak": 750, "pine": 500,
    "wood": 600, "lumber": 500, "pla": 1240 * 0.45, "petg": 1270 * 0.45, "abs": 1050 * 0.45, "nylon": 1150,
    "acrylic": 1180, "polycarbonate": 1200, "hdpe": 960, "delrin": 1410, "acetal": 1410, "rubber": 1100,
    "foam": 50, "glass": 2500, "carbon fibre": 1600, "carbon fiber": 1600, "concrete": 2400, "fabric": 300,
}
FORMAT = """{
 "title": "two to five words",
 "summary": "two or three sentences: what the machine is, what it does, how it is built",
 "units_shown": "inch" or "mm" (how the owner talks about sizes),
 "scale_basis": "which things of known size set the scale, and how",
 "parts": [
  {"id": "short-kebab-id, unique",
   "name": "what the owner would call it; identical parts share a name (Leg, Leg, Leg, Leg)",
   "group": "the assembly it belongs to (Frame, Drive, Electronics, Gripper...)",
   "status": "existing" | "new" | "change" | "remove",
   "shape": "box" | "cylinder" | "tube" | "sphere" | "cone" | "none",
   "size": [x, y, z] for a box (mm, before rotation),
   "diameter": mm, "inner_diameter": mm (tube), "top_diameter": mm (cone), "length": mm, "axis": "x" | "y" | "z"
     for cylinder, tube and cone,
   "at": [x, y, z] the centre of the part in mm,
   "rotate": [rx, ry, rz] degrees about the world X, then Y, then Z axes, through the part's centre (omit if 0),
   "holes": [{"diameter": mm, "at": [x, y, z] from the part's centre before rotation, "axis": "x"|"y"|"z"}],
   "passes_through": ["ids of parts this one is meant to go into or through: a shaft through a hub, bearing or
     collar, a part sitting in a pocket"] (omit when none),
   "material": "6061 aluminium, 3/4 in plywood, PLA, mild steel...",
   "colour": "#rrggbb as it looks",
   "qty": 1 (only for shape "none": screws, wire, glue; a part with a shape is always one piece),
   "make": "existing" | "buy" | "3d print" | "laser" | "cnc" | "saw" | "drill" | "weld" | "bend" | "sew" | "other",
   "spec": "the exact standard or product when there is one: NEMA 17 42x42x40, 2020 V-slot, M5x12 SHCS,
            Raspberry Pi 5 8GB, 608-2RS",
   "buy": "where it is bought and roughly what to search for (new parts only)",
   "cost": US dollars each (new parts only),
   "mass_g": grams when known from a datasheet (otherwise it is worked out from the material),
   "volts": supply voltage (electrical parts), "watts": typical draw, "supply_watts": what a supply or battery
     can give,
   "sizes_from": "measured" | "datasheet" | "standard" | "photo-estimate" | "guess",
   "confidence": 0 to 1 that the sizes are within 5 percent,
   "notes": "anything the builder needs: what changes on a CHANGE part, where it is fixed, what it connects to"}
 ],
 "joints": [
  {"id": "short-kebab-id", "name": "what it is: Left drive wheel, Arm pivot, Gripper jaw",
   "type": "revolute" (turns about an axis) | "slider" (slides along it),
   "parts": ["ids of the parts that move together on this joint, and only those (not what rides on a joint
     further along: that has its own joint)"],
   "on": "id of the part it turns or slides on or is carried by (a frame part, or a part of another joint)",
   "origin": [x, y, z] a point on the axis in mm (the centre of the axle, pin or bearing),
   "axis": [dx, dy, dz] the direction of the axis (or slide),
   "min": degrees (mm for a slider) from the pose modelled, "max": the same; omit both for a wheel or anything
     that turns all the way round,
   "drive": "id of the motor or actuator that moves it" (omit when it is moved by hand or is free),
   "notes": "how it moves: what drives it and through what (gearbox, worm, belt, linkage), what stops it"}
 ],
 "measurements": [
  {"letter": "A", "what": "plain words: from where to where",
   "estimate_mm": number, "part": "a part id when the measurement is one size of one part",
   "axis": "x" | "y" | "z" | "diameter" | "length" (which size of that part),
   "photo": 1-based photo number where it is clearest,
   "line": [x1, y1, x2, y2] the two ends in that photo, as fractions of its width and height,
   "why": "what it fixes"}
 ],
 "unknowns": ["what can't be seen or worked out from the photos, and how the owner could find it out"],
 "plan": null or {
   "goal": "...", "summary": "...",
   "changes": [{"what": "...", "why": "...", "how": "..."}],
   "wiring": [{"from": "...", "to": "...", "what": "cable, gauge, connector, signal"}],
   "software": ["..."], "steps": ["ordered build steps"], "risks": ["safety and what could go wrong"]}
}"""

RULES = """Coordinates: millimetres, Z up, the floor (or the surface it stands on) at z = 0, the origin at the centre
of the footprint. +X runs to the right as seen in photo 1, +Y runs away from the camera, so the front of the
machine faces -Y. Positions are part centres. Every part sits where it really is: touching what it is fixed to,
never floating, never passing through another part (a bolt through a plate is shape "none" hardware).

One entry is one physical piece. Four legs are four entries with the same name and their own positions. Model
every piece that has a size worth knowing, as the simplest shape that has its true outer size (a motor is a box
and a cylinder for its shaft; an L-bracket is two boxes; extrusion is a box of its profile size). Small hardware
(screws, nuts, washers, cable ties, wire) is shape "none" with a qty. Never add parts the photos don't show,
except hardware that must be there for it to hold together.

Scale comes from things of known size, never from a guess at the whole: standard parts (NEMA 17 face 42.3 mm,
NEMA 23 56.4 mm, 2020 extrusion 20 mm, 2040, 3030, 4040, 80/20 1010 is 1 in, 2x4 lumber 38 x 89 mm, plywood
18/12/6 mm, 608 bearing 22 mm across, Arduino Uno 68.6 x 53.4 mm, Raspberry Pi 85 x 56 mm, breadboard 165 x 55 mm,
M3/M5 screw heads 5.5/8.5 mm, a 12 V 30 A PSU 215 x 115 x 50 mm, a cordless drill battery), then the room (a
door 2032 mm tall, outlet cover 70 x 115 mm, floor tiles, ceiling height, a workbench about 900 mm high), then
people (a hand is about 85 mm across). Say in scale_basis which you used. Where two photos disagree, trust the
one taken more square-on.

Anything that moves gets a joint, so the model moves the way the machine does: every wheel, arm, pivot, lid,
jaw, carriage and lead screw. Model the parts in the pose they are in (the photos' pose, or the pose it rests in),
put the axis exactly through the axle, pin, shaft or bearing they turn on, and give min and max from that pose
as far as it can really go before something stops it. A part that moves with something further along (a gripper
on an arm) belongs to its own joint whose "on" is a part of the arm, so it rides along. Parts that don't move
have no joint.

Be honest about what you know. sizes_from and confidence say how each size was got. The measurements list is
the four to ten that would fix the most uncertain sizes for the least work with a tape measure, most important
first; each drawn as a line between two points the owner can find on the real thing in the photo named."""

SYSTEM_READ = """You are the measuring engineer inside JARVIS, a personal assistant. The owner built a real machine
and has lost its CAD file. From their photographs you reconstruct it as a CAD spec that a model is built from
exactly, so that it can be measured, changed and built on. Reply with JSON only (no prose, no code fences) in
this form:

""" + FORMAT + """

""" + RULES

SYSTEM_REVISE = """You are the engineer inside JARVIS who keeps a machine's CAD spec right. You get the current
spec (JSON), the owner's photographs, and something new: real measurements taken with a tape measure, pictures
of the CAD model built from the spec, or a correction in the owner's words. Return the complete corrected spec
as JSON only, in the same form:

""" + FORMAT + """

""" + RULES + """

Keep every part id that still exists. A real measurement is the truth: set that size, mark it "measured" with
confidence 0.95, and move and resize everything that depends on it so the machine still fits together (if a
rail is longer, what sits on its ends moves; parts of the same standard stock stay that stock). Rescale guesses
in proportion when a measurement shows the overall scale was off. Keep "plan" unchanged unless the change touches
it. Keep the measurements list, with the measured ones still in it, and add new ones only where a big
uncertainty remains."""

SYSTEM_UPGRADE = """You are the design engineer inside JARVIS. The owner has a real machine (its CAD spec and
photographs are below) and wants to change it into something new. Design the change so that it can really be
built in a home workshop, and return the complete spec with your design in it, as JSON only, in this form:

""" + FORMAT + """

""" + RULES + """

How to design it:
- Keep every existing part. Mark a part "change" when it has to be modified and say exactly how in notes (drill
  two 5 mm holes 40 mm apart, cut 120 mm off, move it 30 mm up); "remove" when it comes off. Add what is needed
  as "new" parts.
- New bought parts are real products you can name, with sizes, mass, volts and watts from their datasheets
  (sizes_from "datasheet"), a cost in US dollars and where to buy them. Prefer common, well-supported parts
  (Raspberry Pi 5, NVIDIA Jetson Orin Nano, ESP32, Arduino, TMC2209 or DM542 drivers, NEMA steppers, MG996R or
  Dynamixel servos, Pololu motor drivers, Intel RealSense or OAK-D or USB cameras, RPLIDAR, VL53L1X, BNO085,
  LiPo or LiFePO4 packs, Mean Well supplies, buck converters, an emergency stop) unless the machine calls for
  something else.
- Everything new needs a way to be mounted: design the brackets, plates and spacers as "new" parts to 3D print,
  laser cut or cut from stock, with their mounting holes, sized to the parts they hold and the frame they bolt to.
- It must fit: new parts must not pass through existing ones, cables need a route, moving parts need clearance.
  Keep the existing joints, and give every new moving part its joint.
- Power: every electrical part has volts and watts; supplies and batteries have supply_watts with at least 30
  percent spare. Motors need drivers rated for their current.
- Safety: an emergency stop that cuts motor power, fuses, guards over pinch points, and a note on anything that
  can move on its own.
- Fill "plan": the goal, a summary, each change and why, the wiring list, the software it needs (operating
  system, frameworks, models, how the AI part sees, decides and moves), the build in order, and the risks."""

SYSTEM_CHECK = """You compare a CAD model with photographs of the real machine it was made from. First come the
owner's photographs, then pictures of the CAD model from the front, the right side, the top and an angle. The
spec the model was built from follows. Where the model differs from the photographs (a part missing, the wrong
size or proportion, in the wrong place, the wrong way round, floating, passing through another part, something
that moves on the real machine with no joint, a joint's axis not through its axle or pin), correct the spec. Return the complete corrected spec as JSON only, in the same form:

""" + FORMAT + """

""" + RULES + """

If nothing needs correcting, return the spec unchanged."""

_lock = threading.RLock()
_work = threading.Lock()
STATE = {"busy": "", "started": 0.0, "error": "", "project": None}


# ---------- Projects ----------

def _slug(text):
    words = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40].strip("-")
    return f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{words or 'machine'}"


def _folder(project_id):
    if not re.fullmatch(r"[a-z0-9-]{1,80}", project_id or ""):
        raise ValueError("Unknown blueprint project.")
    return STORE / project_id


def _current_id():
    try:
        return json.loads((STORE / "current.json").read_text(encoding="utf-8"))["project"]
    except (OSError, ValueError, KeyError):
        return None


def _set_current(project_id):
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / "current.json").write_text(json.dumps({"project": project_id, "at": time.time()}), encoding="utf-8")


def load(project_id=None):
    project_id = project_id or _current_id()
    if not project_id:
        raise ValueError("There's no blueprint project yet. Start one from photos with action new.")
    spec = json.loads((_folder(project_id) / "spec.json").read_text(encoding="utf-8"))
    spec["id"] = project_id
    return spec


def save(spec, label=""):
    """Write the spec, keeping the one before it for undo."""
    folder = _folder(spec["id"])
    (folder / "versions").mkdir(parents=True, exist_ok=True)
    path = folder / "spec.json"
    if path.is_file():
        stamp = f"{datetime.datetime.now():%Y%m%d-%H%M%S-%f}"
        shutil.copyfile(path, folder / "versions" / f"{stamp}.json")
        for old in sorted((folder / "versions").glob("*.json"))[:-MAX_VERSIONS]:
            old.unlink(missing_ok=True)
    spec["updated"] = time.time()
    if label:
        spec.setdefault("history", []).append({"at": time.time(), "what": label})
        spec["history"] = spec["history"][-40:]
    tmp = folder / "spec.tmp"
    tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    _set_current(spec["id"])
    return spec


def projects():
    found = []
    for path in STORE.glob("*/spec.json") if STORE.is_dir() else []:
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
            found.append({"id": path.parent.name, "title": spec.get("title", ""), "updated": spec.get("updated", 0)})
        except (OSError, ValueError):
            continue
    return sorted(found, key=lambda p: -p["updated"])


def photos(spec):
    folder = _folder(spec["id"]) / "photos"
    return sorted(folder.glob("*.jpg")) if folder.is_dir() else []


# ---------- Photos in ----------

def _jpeg(data, side=PHOTO_SIDE):
    from PIL import Image, ImageOps
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    image.thumbnail((side, side))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _gather(source):
    """Photo bytes from a folder, image files, image URLs, "bench" (the workshop bench) or "screen"."""
    found = []
    for item in [s.strip().strip('"') for s in re.split(r"[;\n]|,(?=\s*(?:https?:|[a-zA-Z]:\\|~))", source or "")]:
        if not item:
            continue
        if item.lower() == "bench":
            import workshop
            path = workshop.STORE / workshop.BENCH
            if not path.is_file():
                raise ValueError("There's no picture on the workshop bench.")
            found.append(path.read_bytes())
        elif item.lower() == "screen":
            import workshop
            found.extend(workshop._screens()[1])
        elif re.match(r"https?://", item, re.I):
            import requests
            response = requests.get(item, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("image/"):
                raise ValueError(f"That link isn't a picture: {item[:80]}")
            found.append(response.content)
        else:
            path = Path(item).expanduser()
            if path.is_dir():
                files = sorted(p for p in path.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp"))
                if not files:
                    raise ValueError(f"There are no JPEG or PNG photos in {path}.")
                found.extend(p.read_bytes() for p in files)
            elif path.is_file():
                found.append(path.read_bytes())
            else:
                raise ValueError(f"I can't find {item}.")
    if not found:
        raise ValueError('Say where the photos are: a folder, picture files, image links, "bench" or "screen".')
    return [_jpeg(data) for data in found[:MAX_PHOTOS]]


def _photo_bytes(spec, side=1400):
    return [_jpeg(path.read_bytes(), side) for path in photos(spec)]


# ---------- The spec: tidy what the model returned, and work things out from it ----------

def _num(value, low=0.0, high=1e6):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and low <= number <= high else None


def _vec(value, default=(0.0, 0.0, 0.0), low=-1e6, high=1e6):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        numbers = [_num(v, low, high) for v in value]
        if None not in numbers:
            return numbers
    return list(default)


def _colour(value, default="#9aa3ab"):
    value = str(value or "").strip()
    return value.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else default


def extract_json(text):
    """The JSON object in a model's reply, even with prose or fences around it."""
    text = str(text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The model didn't return a spec.")
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", text[start:end + 1])     # trailing commas
        return json.loads(cleaned)


def tidy(raw, keep=None):
    """A spec that every later step can rely on: known shapes, sizes in range, unique ids, no NaN."""
    keep = keep or {}
    spec = {k: keep[k] for k in ("id", "created", "history", "source", "photo_count") if k in keep}
    spec["title"] = " ".join(str(raw.get("title") or keep.get("title") or "Machine").split())[:60]
    spec["summary"] = str(raw.get("summary") or keep.get("summary") or "")[:1200]
    spec["units_shown"] = "mm" if str(raw.get("units_shown", keep.get("units_shown", "inch"))).lower().startswith("m") else "inch"
    spec["scale_basis"] = str(raw.get("scale_basis") or keep.get("scale_basis") or "")[:800]
    parts, seen = [], set()
    for n, item in enumerate(raw.get("parts") or []):
        if not isinstance(item, dict):
            continue
        shape = str(item.get("shape", "box")).lower()
        shape = shape if shape in SHAPES else "box"
        base = re.sub(r"[^a-z0-9-]+", "-", str(item.get("id") or item.get("name") or f"part-{n + 1}").lower()).strip("-") or f"part-{n + 1}"
        pid, k = base[:60], 2
        while pid in seen:
            pid, k = f"{base[:56]}-{k}", k + 1
        seen.add(pid)
        part = {"id": pid, "name": " ".join(str(item.get("name") or pid).split())[:80],
                "group": " ".join(str(item.get("group") or "Main").split())[:40],
                "status": str(item.get("status", "existing")).lower() if str(item.get("status", "existing")).lower() in STATUSES else "existing",
                "shape": shape}
        if shape == "box":
            part["size"] = _vec(item.get("size"), (10, 10, 10), 0.01, 1e5)
        elif shape in ("cylinder", "tube", "cone"):
            part["diameter"] = _num(item.get("diameter"), 0.01, 1e5) or 10.0
            part["length"] = _num(item.get("length"), 0.01, 1e5) or 10.0
            part["axis"] = str(item.get("axis", "z")).lower() if str(item.get("axis", "z")).lower() in ("x", "y", "z") else "z"
            if shape == "tube":
                inner = _num(item.get("inner_diameter"), 0.0, part["diameter"] * 0.999)
                part["inner_diameter"] = inner if inner else round(part["diameter"] * 0.8, 3)
            if shape == "cone":
                part["top_diameter"] = _num(item.get("top_diameter"), 0.0, 1e5) or 0.0
        elif shape == "sphere":
            part["diameter"] = _num(item.get("diameter"), 0.01, 1e5) or 10.0
        if shape != "none":
            part["at"] = _vec(item.get("at"))
            rotate = _vec(item.get("rotate"), (0, 0, 0), -720, 720)
            if any(rotate):
                part["rotate"] = rotate
            holes = []
            for hole in item.get("holes") or []:
                if isinstance(hole, dict) and _num(hole.get("diameter"), 0.1, 1e4):
                    axis = str(hole.get("axis", "z")).lower()
                    holes.append({"diameter": float(hole["diameter"]), "at": _vec(hole.get("at")),
                                  "axis": axis if axis in ("x", "y", "z") else "z"})
            if holes:
                part["holes"] = holes[:60]
            through = [str(x) for x in item.get("passes_through") or [] if isinstance(x, str)]
            if through:
                part["passes_through"] = through[:20]
        part["qty"] = max(1, int(_num(item.get("qty"), 1, 1e5) or 1)) if shape == "none" else 1
        part["material"] = str(item.get("material") or "")[:80]
        part["colour"] = _colour(item.get("colour") or item.get("color"))
        make = str(item.get("make") or ("buy" if part["status"] == "new" else "existing")).lower()
        part["make"] = make if make in MAKES else "other"
        for key, size in (("spec", 160), ("buy", 240), ("notes", 600)):
            if item.get(key):
                part[key] = str(item[key])[:size]
        for key, high in (("cost", 1e6), ("mass_g", 1e7), ("volts", 1000), ("watts", 1e5), ("supply_watts", 1e6)):
            number = _num(item.get(key), 0, high)
            if number is not None:
                part[key] = number
        source = str(item.get("sizes_from") or "photo-estimate").lower()
        part["sizes_from"] = source if source in SOURCES else "photo-estimate"
        part["confidence"] = _num(item.get("confidence"), 0, 1) if _num(item.get("confidence"), 0, 1) is not None else 0.5
        parts.append(part)
    if not parts:
        raise ValueError("The spec has no parts.")
    spec["parts"] = parts
    ids = {p["id"] for p in parts}
    for part in parts:
        if "passes_through" in part:
            part["passes_through"] = [x for x in part["passes_through"] if x in ids and x != part["id"]]
            if not part["passes_through"]:
                del part["passes_through"]
    spec["joints"] = _tidy_joints(raw["joints"] if "joints" in raw else keep.get("joints"), parts)
    old = {m.get("letter"): m for m in keep.get("measurements", [])}
    measurements, letters = [], set()
    for item in raw.get("measurements") or []:
        if not isinstance(item, dict):
            continue
        letter = re.sub(r"[^A-Z]", "", str(item.get("letter", "")).upper())[:2]
        if not letter or letter in letters:
            continue
        letters.add(letter)
        m = {"letter": letter, "what": str(item.get("what") or "")[:200],
             "estimate_mm": _num(item.get("estimate_mm"), 0, 1e6), "why": str(item.get("why") or "")[:200]}
        if item.get("part") in ids:
            m["part"] = item["part"]
            axis = str(item.get("axis", "")).lower()
            if axis in ("x", "y", "z", "diameter", "length"):
                m["axis"] = axis
        photo = _num(item.get("photo"), 1, MAX_PHOTOS)
        line = item.get("line")
        if photo and isinstance(line, (list, tuple)) and len(line) == 4 and all(_num(v, 0, 1) is not None for v in line):
            m["photo"], m["line"] = int(photo), [float(v) for v in line]
        value = _num(item.get("value_mm"), 0, 1e6)
        if value is None and letter in old:
            value = old[letter].get("value_mm")
        if value is not None:
            m["value_mm"] = value
        measurements.append(m)
    spec["measurements"] = measurements
    spec["unknowns"] = [str(u)[:300] for u in (raw.get("unknowns") or []) if u][:30]
    plan = raw.get("plan") if "plan" in raw else keep.get("plan")
    spec["plan"] = plan if isinstance(plan, dict) else None
    return spec


AXES = {"x": 0, "y": 1, "z": 2}
JOINT_TYPES = ("revolute", "slider")


def _direction(value):
    """A unit vector from [dx, dy, dz] or "x"/"y"/"z" (None when it has no length)."""
    if isinstance(value, str) and value.lower().lstrip("+-") in AXES:
        v = [0.0, 0.0, 0.0]
        v[AXES[value.lower().lstrip("+-")]] = -1.0 if value.startswith("-") else 1.0
        return v
    v = _vec(value, (0, 0, 0))
    length = math.sqrt(sum(c * c for c in v))
    return [round(c / length, 6) for c in v] if length > 1e-9 else None


def _tidy_joints(raw, parts):
    """Joints that can be built: real parts, each part on one joint at most, an axis, and no loops."""
    shaped = {p["id"]: p for p in parts if p["shape"] != "none"}
    joints, seen, taken = [], set(), set()
    for n, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        axis = _direction(item.get("axis"))
        moving = [x for x in item.get("parts") or [] if isinstance(x, str) and x in shaped and x not in taken]
        if not axis or not moving:
            continue
        base = re.sub(r"[^a-z0-9-]+", "-", str(item.get("id") or item.get("name") or f"joint-{n + 1}").lower()).strip("-") or f"joint-{n + 1}"
        jid, k = base[:60], 2
        while jid in seen:
            jid, k = f"{base[:56]}-{k}", k + 1
        seen.add(jid)
        taken.update(moving)
        kind = str(item.get("type", "revolute")).lower()
        joint = {"id": jid, "name": " ".join(str(item.get("name") or jid).split())[:80],
                 "type": kind if kind in JOINT_TYPES else "revolute", "parts": moving,
                 "origin": _vec(item.get("origin"), shaped[moving[0]]["at"]), "axis": axis}
        on = item.get("on")
        if isinstance(on, str) and on in shaped and on not in moving:
            joint["on"] = on
        low = _num(item.get("min"), -1e5, 1e5)
        high = _num(item.get("max"), -1e5, 1e5)
        if low is not None and high is not None and high > low:
            joint["min"], joint["max"] = min(low, 0.0), max(high, 0.0)     # the pose modelled is inside the range
        if item.get("drive") in shaped:
            joint["drive"] = item["drive"]
        if item.get("notes"):
            joint["notes"] = str(item["notes"])[:400]
        joints.append(joint)
    owner = {pid: j["id"] for j in joints for pid in j["parts"]}
    for joint in joints:                    # a joint carried by its own descendant would be a loop: drop the "on"
        seen_ids, current = {joint["id"]}, owner.get(joint.get("on"))
        while current:
            if current in seen_ids:
                joint.pop("on", None)
                break
            seen_ids.add(current)
            current = owner.get(next((j.get("on") for j in joints if j["id"] == current), None))
    return joints[:40]


def joint_parent(spec, joint):
    """The id of the joint this one rides on, or None when it is on the frame."""
    on = joint.get("on")
    return next((j["id"] for j in spec.get("joints", []) if on in j["parts"]), None)


def _rotation(rotate):
    """3x3 matrix for rotations about world X, then Y, then Z (degrees)."""
    rx, ry, rz = (math.radians(a) for a in (rotate or (0, 0, 0)))
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    X = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    Y = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    Z = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mul(Z, mul(Y, X))


def extent(part):
    """The part's size along x, y, z before rotation (mm)."""
    shape = part["shape"]
    if shape == "box":
        return list(part["size"])
    if shape == "sphere":
        return [part["diameter"]] * 3
    if shape in ("cylinder", "tube", "cone"):
        d = max(part["diameter"], part.get("top_diameter", 0))
        size = [d, d, d]
        size[AXES[part["axis"]]] = part["length"]
        return size
    return [0, 0, 0]


def box(part):
    """World axis-aligned bounds (min xyz, max xyz) of a part, rotation included."""
    half = [s / 2 for s in extent(part)]
    matrix = _rotation(part.get("rotate"))
    corners = [[sx * half[0], sy * half[1], sz * half[2]] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    world = [[sum(matrix[i][k] * c[k] for k in range(3)) + part["at"][i] for i in range(3)] for c in corners]
    return [min(w[i] for w in world) for i in range(3)], [max(w[i] for w in world) for i in range(3)]


def volume_mm3(part):
    shape = part["shape"]
    if shape == "box":
        v = part["size"][0] * part["size"][1] * part["size"][2]
    elif shape == "cylinder":
        v = math.pi * (part["diameter"] / 2) ** 2 * part["length"]
    elif shape == "tube":
        v = math.pi * ((part["diameter"] / 2) ** 2 - (part["inner_diameter"] / 2) ** 2) * part["length"]
    elif shape == "cone":
        r1, r2 = part["diameter"] / 2, part.get("top_diameter", 0) / 2
        v = math.pi * part["length"] * (r1 * r1 + r1 * r2 + r2 * r2) / 3
    elif shape == "sphere":
        v = math.pi * part["diameter"] ** 3 / 6
    else:
        return 0.0
    for hole in part.get("holes", []):
        v -= math.pi * (hole["diameter"] / 2) ** 2 * min(extent(part)[AXES[hole["axis"]]], 1e5)
    return max(v, 0.0)


def mass_g(part):
    if part.get("mass_g") is not None:
        return part["mass_g"] * part.get("qty", 1)
    material = part.get("material", "").lower()
    density = next((d for name, d in sorted(DENSITY.items(), key=lambda kv: -len(kv[0])) if name in material), None)
    if density is None or part["shape"] == "none":
        return None
    hollow = 0.15 if any(w in material for w in ("extrusion", "v-slot", "t-slot", "8020", "80/20")) else 1.0
    return volume_mm3(part) * 1e-9 * density * 1000 * (0.45 if hollow < 1 else 1)


def _active(spec):
    return [p for p in spec["parts"] if p["status"] != "remove"]


# ---------- Motion: moving the joints and finding what a moving part hits ----------

def _mat_vec(m, v):
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _axis_turn(axis, degrees):
    """Rotation matrix about a unit axis (Rodrigues)."""
    x, y, z = axis
    a = math.radians(degrees)
    c, s, t = math.cos(a), math.sin(a), 1 - math.cos(a)
    return [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]


def _joint_move(joint, value):
    """(R, t) taking a point at the modelled pose to where it is with the joint at value (degrees or mm)."""
    if joint["type"] == "slider":
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [joint["axis"][k] * value for k in range(3)]
    r = _axis_turn(joint["axis"], value)
    o = joint["origin"]
    ro = _mat_vec(r, o)
    return r, [o[k] - ro[k] for k in range(3)]


def _compose(outer, inner):
    (ra, ta), (rb, tb) = outer, inner
    rt = _mat_vec(ra, tb)
    return _mat_mul(ra, rb), [rt[k] + ta[k] for k in range(3)]


def pose(spec, values):
    """{part id: (R, t)} for every part on a joint, with the joints at values {joint id: degrees or mm}."""
    joints = {j["id"]: j for j in spec.get("joints", [])}
    moves = {}

    def move_of(jid, depth=0):
        if jid in moves:
            return moves[jid]
        joint = joints[jid]
        own = _joint_move(joint, values.get(jid, 0.0))
        parent = joint_parent(spec, joint) if depth < 40 else None
        moves[jid] = _compose(move_of(parent, depth + 1), own) if parent else own
        return moves[jid]
    return {pid: move_of(j["id"]) for j in joints.values() for pid in j["parts"]}


def _obb(part, move=None, shrink=1.0):
    """(centre, three unit axes, three half sizes) of the part's box, moved by (R, t)."""
    turn = _rotation(part.get("rotate"))
    centre = list(part["at"])
    if move:
        turn = _mat_mul(move[0], turn)
        centre = [c + d for c, d in zip(_mat_vec(move[0], centre), move[1])]
    axes = [[turn[i][k] for i in range(3)] for k in range(3)]
    return centre, axes, [max(s / 2 - shrink, 0.05) for s in extent(part)]


def _overlap(a, b):
    """How far two boxes overlap along the axis that separates them best (<= 0 when they don't touch)."""
    (ca, aa, ha), (cb, ab, hb) = a, b
    d = [cb[k] - ca[k] for k in range(3)]
    tests = list(aa) + list(ab)
    for u in aa:
        for v in ab:
            cross = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            size = math.sqrt(sum(c * c for c in cross))
            if size > 1e-6:
                tests.append([c / size for c in cross])
    least = float("inf")
    for axis in tests:
        reach = (sum(h * abs(sum(x * y for x, y in zip(u, axis))) for h, u in zip(ha, aa))
                 + sum(h * abs(sum(x * y for x, y in zip(v, axis))) for h, v in zip(hb, ab)))
        gap = reach - abs(sum(x * y for x, y in zip(d, axis)))
        if gap <= 0:
            return gap
        least = min(least, gap)
    return least


def _spins_in_place(part, joint):
    """A round part turning about its own centre line (a wheel on its axle) looks the same at every angle."""
    if joint["type"] != "revolute" or part["shape"] not in ("cylinder", "tube", "cone", "sphere"):
        return False
    rel = [part["at"][k] - joint["origin"][k] for k in range(3)]
    along = sum(rel[k] * joint["axis"][k] for k in range(3))
    off = math.sqrt(max(sum(r * r for r in rel) - along * along, 0.0))
    if part["shape"] == "sphere":
        return off < 0.5
    own = _mat_vec(_rotation(part.get("rotate")), [1.0 if part["axis"] == a else 0.0 for a in "xyz"])
    return off < 0.5 and abs(sum(own[k] * joint["axis"][k] for k in range(3))) > 0.999


def sweep_values(joint, samples=12):
    """The joint positions a sweep visits: its range, or a full turn for a joint without limits."""
    if "min" in joint:
        return [joint["min"] + (joint["max"] - joint["min"]) * i / (samples - 1) for i in range(samples)]
    if joint["type"] == "revolute":
        return [360.0 * i / samples for i in range(samples)]
    return []


def motion_checks(spec, samples=12):
    """Each joint swept through its range on its own: the first place a moving part runs into something."""
    parts = {p["id"]: p for p in _active(spec) if p["shape"] != "none"}
    joints = spec.get("joints", [])
    meant = {frozenset((p["id"], other)) for p in parts.values() for other in p.get("passes_through", [])}
    rest = {pid: _obb(p) for pid, p in parts.items()}
    hits = []
    for joint in joints:
        family, grew = {joint["id"]}, True
        while grew:
            grew = False
            for j in joints:
                if j["id"] not in family and joint_parent(spec, j) in family:
                    family.add(j["id"])
                    grew = True
        moving = [pid for j in joints if j["id"] in family for pid in j["parts"] if pid in parts
                  and not (j["id"] == joint["id"] and _spins_in_place(parts[pid], joint))]
        others = [pid for pid in parts if pid not in {x for j in joints if j["id"] in family for x in j["parts"]}]
        pairs = [(m, o) for m in moving for o in others
                 if frozenset((m, o)) not in meant and _overlap(rest[m], rest[o]) <= 0]
        found = {}
        for value in sweep_values(joint, samples):
            if not value or not pairs:
                continue
            moved = pose(spec, {joint["id"]: value})
            for m, o in pairs:
                if (m, o) not in found and _overlap(_obb(parts[m], moved.get(m)), rest[o]) > 2.0:
                    found[(m, o)] = value
        for (m, o), value in sorted(found.items(), key=lambda kv: abs(kv[1])):
            hits.append({"joint": joint["id"], "joint_name": joint["name"], "a": parts[m]["name"],
                         "b": parts[o]["name"], "a_id": m, "b_id": o, "at": round(value, 1),
                         "unit": "mm" if joint["type"] == "slider" else "°"})
    return hits[:30]


def checks(spec):
    """What a builder would want to know before cutting anything: clashes, floating parts, guesses, power."""
    parts = [p for p in _active(spec) if p["shape"] != "none"]
    bounds = {p["id"]: box(p) for p in parts}
    clashes, floating = [], []
    meant = {frozenset((p["id"], other)) for p in parts for other in p.get("passes_through", [])}
    for i, a in enumerate(parts):
        amin, amax = bounds[a["id"]]
        touching = amin[2] <= 2.0          # standing on the floor
        for b in parts[i + 1:]:
            bmin, bmax = bounds[b["id"]]
            depth = [min(amax[k], bmax[k]) - max(amin[k], bmin[k]) for k in range(3)]
            if all(d > 3.0 for d in depth) and frozenset((a["id"], b["id"])) not in meant:
                small = min(volume_mm3(a), volume_mm3(b)) or 1
                if depth[0] * depth[1] * depth[2] > 0.05 * small and not (a["shape"] == "tube" or b["shape"] == "tube"):
                    true_depth = _overlap(_obb(a, shrink=0), _obb(b, shrink=0))   # tilted parts: their real boxes
                    if true_depth > 3.0:
                        clashes.append((a, b, min(true_depth, min(depth))))
        if not touching:
            for b in parts:
                if b is a:
                    continue
                bmin, bmax = bounds[b["id"]]
                if all(min(amax[k], bmax[k]) - max(amin[k], bmin[k]) > -2.0 for k in range(3)):
                    touching = True
                    break
        if not touching:
            floating.append(a)
    guesses = [p for p in _active(spec) if p["shape"] != "none" and p["status"] == "existing"
               and p["sizes_from"] in ("photo-estimate", "guess") and p["confidence"] < 0.6]
    draw = sum(p.get("watts", 0) for p in _active(spec) if not p.get("supply_watts"))
    supply = sum(p.get("supply_watts", 0) for p in _active(spec))
    masses = [mass_g(p) for p in _active(spec)]
    total_mass = sum(m for m in masses if m)
    cost = sum((p.get("cost") or 0) * p.get("qty", 1) for p in _active(spec) if p["status"] in ("new", "change"))
    open_measurements = [m for m in spec.get("measurements", []) if m.get("value_mm") is None]
    lo = [min(bounds[p][0][k] for p in bounds) for k in range(3)] if bounds else [0, 0, 0]
    hi = [max(bounds[p][1][k] for p in bounds) for k in range(3)] if bounds else [0, 0, 0]
    return {"clashes": [{"a": a["name"], "b": b["name"], "a_id": a["id"], "b_id": b["id"], "depth_mm": round(d, 1)}
                        for a, b, d in clashes[:30]],
            "floating": [{"name": p["name"], "id": p["id"]} for p in floating[:30]],
            "guesses": [{"name": p["name"], "id": p["id"], "confidence": p["confidence"]} for p in guesses],
            "power": {"draw_w": round(draw, 1), "supply_w": round(supply, 1),
                      "ok": (supply >= draw * 1.3) if draw else None},
            "mass_kg": round(total_mass / 1000, 2), "mass_unknown": sum(1 for m in masses if m is None),
            "cost_usd": round(cost, 2), "open_measurements": [m["letter"] for m in open_measurements],
            "overall_mm": [round(hi[k] - lo[k], 1) for k in range(3)],
            "joints": len(spec.get("joints", [])), "motion": motion_checks(spec)}


def bill(spec):
    """The parts list: identical pieces counted together, removed parts left out."""
    rows = {}
    for p in _active(spec):
        size = size_text(p, "mm")
        key = (p["status"], p["name"], size, p.get("material", ""), p.get("spec", ""))
        row = rows.setdefault(key, {"status": p["status"], "name": p["name"], "qty": 0, "size_mm": size,
                                    "material": p.get("material", ""), "make": p["make"], "spec": p.get("spec", ""),
                                    "buy": p.get("buy", ""), "cost_each": p.get("cost"), "group": p["group"],
                                    "sizes_from": p["sizes_from"], "confidence": p["confidence"],
                                    "notes": p.get("notes", ""), "ids": []})
        row["qty"] += p.get("qty", 1)
        row["ids"].append(p["id"])
    order = {"existing": 0, "change": 1, "new": 2}
    return sorted(rows.values(), key=lambda r: (order.get(r["status"], 3), r["group"], r["name"]))


def _length(mm, units):
    if units == "inch":                     # to the nearest sixteenth, the way a tape measure reads
        sixteenths = round(mm / 25.4 * 16)
        whole, part = divmod(sixteenths, 16)
        if not part:
            return f"{whole} in"
        top, bottom = part, 16
        while top % 2 == 0:
            top, bottom = top // 2, bottom // 2
        return f"{whole} {top}/{bottom} in" if whole else f"{top}/{bottom} in"
    return f"{mm:.0f} mm" if mm >= 10 else f"{mm:.1f} mm"


def size_text(part, units="mm"):
    shape = part["shape"]
    if shape == "box":
        return " x ".join(_length(v, units) for v in part["size"])
    if shape == "sphere":
        return f"⌀{_length(part['diameter'], units)}"
    if shape in ("cylinder", "cone"):
        return f"⌀{_length(part['diameter'], units)} x {_length(part['length'], units)}"
    if shape == "tube":
        return f"⌀{_length(part['diameter'], units)} / ⌀{_length(part['inner_diameter'], units)} x {_length(part['length'], units)}"
    return ""


# ---------- Real measurements from the owner ----------

UNIT_MM = {"mm": 1, "millimetre": 1, "millimeter": 1, "cm": 10, "centimetre": 10, "centimeter": 10, "m": 1000,
           "metre": 1000, "meter": 1000, "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4, "ft": 304.8,
           "foot": 304.8, "feet": 304.8, "'": 304.8}
NUMBER = r"(\d+/\d+|\d+(?:\.\d+)?(?:\s+\d+/\d+)?)"
UNIT = r"(mm|millimet(?:re|er)s?|cm|centimet(?:re|er)s?|met(?:re|er)s?|m|inch(?:es)?|in|\"|feet|foot|ft|')"


def _value(number):
    total = 0.0
    for piece in number.split():
        if "/" in piece:
            top, bottom = piece.split("/")
            total += float(top) / float(bottom) if float(bottom) else 0
        else:
            total += float(piece)
    return total


def parse_measurements(text, default_units="inch"):
    """{"A": mm, ...} from "A is 610 mm, B 24 1/2 in, C: 2 ft 3 in, D=31"."""
    found = {}
    pattern = re.compile(r"\b([A-Za-z]{1,2})\b\s*(?:is|=|:|-|was|measures)?\s*" + NUMBER + r"\s*" + UNIT + r"?"
                         r"(?:\s*(?:and\s*)?" + NUMBER + r"\s*(inch(?:es)?|in|\"))?", re.I)
    for match in pattern.finditer(text or ""):
        letter = match.group(1).upper()
        if letter in ("IS", "AT", "IT", "OR", "TO", "BY", "OF", "ON", "IN", "MM", "CM", "FT", "M"):
            continue
        unit = (match.group(3) or "").lower().rstrip("s") if match.group(3) else ""
        unit = {"millimetre": "mm", "millimeter": "mm", "centimetre": "cm", "centimeter": "cm", "metre": "m",
                "meter": "m", "inche": "in", "inch": "in", "feet": "ft", "foot": "ft"}.get(unit, unit)
        mm = _value(match.group(2)) * UNIT_MM.get(unit or ("in" if default_units == "inch" else "mm"), 1)
        if match.group(4):
            mm += _value(match.group(4)) * 25.4
        if 0 < mm < 1e6:
            found[letter] = round(mm, 2)
    return found


def apply_measurements(spec, values):
    """Record the owner's numbers, and set a part's size straight away where a measurement is one size of one part."""
    known = {m["letter"]: m for m in spec.get("measurements", [])}
    unknown = [letter for letter in values if letter not in known]
    if unknown:
        raise ValueError(f"There's no measurement {', '.join(unknown)}; the sheet has {', '.join(known) or 'none'}.")
    parts = {p["id"]: p for p in spec["parts"]}
    for letter, mm in values.items():
        m = known[letter]
        m["value_mm"] = mm
        part = parts.get(m.get("part"))
        axis = m.get("axis")
        if not part or not axis:
            continue
        if part["shape"] == "box" and axis in AXES:
            part["size"][AXES[axis]] = mm
        elif part["shape"] in ("cylinder", "tube", "cone", "sphere") and axis == "diameter":
            part["diameter"] = mm
        elif part["shape"] in ("cylinder", "tube", "cone") and axis in ("length", part.get("axis")):
            part["length"] = mm
        else:
            continue
        part["sizes_from"], part["confidence"] = "measured", 0.95
    return spec


# ---------- Fable ----------

def settings():
    saved = preferences.read().get("blueprint")
    saved = saved if isinstance(saved, dict) else {}
    return {"effort": saved.get("effort") if saved.get("effort") in ("low", "medium", "high") else "medium",
            "model": "qwen" if saved.get("model") == "qwen" else "fable"}


ASK_SECONDS = 1800      # a whole machine from twenty photos, joints and all, can take longer than a workshop build


def ask(system, prompt, images):
    """Fable's answer as a spec. Replaced in tests."""
    import asyncio
    import workshop
    text = []
    model = workshop.model_id(settings()["model"])
    if model == workshop.QWEN_MODEL:
        workshop.generate(model, settings()["effort"], system, prompt, images or None, on_text=text.append)
    else:
        asyncio.run(asyncio.wait_for(workshop._stream(model, settings()["effort"], system, prompt, images or None,
                                                      lambda t: None, text.append, threading.Event()), ASK_SECONDS))
    return extract_json("".join(text))


def _spec_for_prompt(spec):
    clean = {k: v for k, v in spec.items() if k not in ("id", "history", "created", "updated", "source", "photo_count")}
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def _count(spec):
    shaped = [p for p in _active(spec) if p["shape"] != "none"]
    return f"{len(shaped)} parts"


# ---------- Fusion ----------

FUSION_SCRIPT = r'''
import adsk.core, adsk.fusion, base64, json, math, os

DATA = json.loads(base64.b64decode("__DATA__").decode("utf-8"))


def run(_context):
    app = adsk.core.Application.get()
    doc = None
    for open_doc in app.documents:      # rebuild in this project's own design while it has never been saved
        try:
            product = adsk.fusion.Design.cast(open_doc.products.itemByProductType("DesignProductType"))
            mark = product.attributes.itemByName("jarvis", "blueprint") if product else None
            if mark and mark.value == DATA["project"] and not open_doc.isSaved:
                doc = open_doc
        except Exception:
            pass
    if doc:
        doc.activate()
        design = adsk.fusion.Design.cast(app.activeProduct)
        for old in [design.rootComponent.occurrences.item(i) for i in range(design.rootComponent.occurrences.count)]:
            old.deleteMe()
        for old in [design.rootComponent.bRepBodies.item(i) for i in range(design.rootComponent.bRepBodies.count)]:
            old.deleteMe()
        if design.designType != adsk.fusion.DesignTypes.DirectDesignType:
            design.designType = adsk.fusion.DesignTypes.DirectDesignType      # bodies are added without history
    else:
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.DirectDesignType
        design.attributes.add("jarvis", "blueprint", DATA["project"])
    design.fusionUnitsManager.distanceDisplayUnits = (adsk.fusion.DistanceUnits.InchDistanceUnits if DATA["inches"]
                                                      else adsk.fusion.DistanceUnits.MillimeterDistanceUnits)
    root = design.rootComponent
    tbm = adsk.fusion.TemporaryBRepManager.get()
    I = adsk.core.Matrix3D.create()

    def P(v):
        return adsk.core.Point3D.create(v[0] / 10, v[1] / 10, v[2] / 10)

    lib = app.materialLibraries.itemByName("Fusion Appearance Library")
    base = lib.appearances.itemByName("Paint - Enamel Glossy (Grey)") if lib else None
    looks = {}

    def look(colour):
        if not base:
            return None
        if colour not in looks:
            name = "Jarvis " + colour
            found = design.appearances.itemByName(name) or design.appearances.addByCopy(base, name)
            prop = adsk.core.ColorProperty.cast(found.appearanceProperties.itemById("opaque_albedo"))
            if prop:
                prop.value = adsk.core.Color.create(int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16), 255)
            looks[colour] = found
        return looks[colour]

    AX = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}

    def rod(centre, axis, length, diameter, top=None):
        d = AX[axis]
        a = [centre[i] - d[i] * length / 2 for i in range(3)]
        b = [centre[i] + d[i] * length / 2 for i in range(3)]
        return tbm.createCylinderOrCone(P(a), diameter / 20, P(b), (diameter if top is None else top) / 20)

    def solid(part):
        s, c = part["shape"], [0.0, 0.0, 0.0]
        if s == "box":
            box = adsk.core.OrientedBoundingBox3D.create(P(c), adsk.core.Vector3D.create(1, 0, 0),
                                                         adsk.core.Vector3D.create(0, 1, 0),
                                                         part["size"][0] / 10, part["size"][1] / 10, part["size"][2] / 10)
            body = tbm.createBox(box)
        elif s == "cylinder":
            body = rod(c, part["axis"], part["length"], part["diameter"])
        elif s == "cone":
            body = rod(c, part["axis"], part["length"], part["diameter"], max(part.get("top_diameter", 0), 0.001))
        elif s == "tube":
            body = rod(c, part["axis"], part["length"], part["diameter"])
            tbm.booleanOperation(body, rod(c, part["axis"], part["length"] * 1.02, part["inner_diameter"]),
                                 adsk.fusion.BooleanTypes.DifferenceBooleanType)
        elif s == "sphere":
            body = tbm.createSphere(P(c), part["diameter"] / 20)
        else:
            return None
        reach = max(part.get("size") or [part.get("length", 0), part.get("diameter", 0)]) * 2.2 + 10
        for hole in part.get("holes", []):
            tbm.booleanOperation(body, rod(hole["at"], hole["axis"], reach, hole["diameter"]),
                                 adsk.fusion.BooleanTypes.DifferenceBooleanType)
        turn = adsk.core.Matrix3D.create()
        for angle, axis in zip(part.get("rotate", [0, 0, 0]), ((1, 0, 0), (0, 1, 0), (0, 0, 1))):
            if angle:
                step = adsk.core.Matrix3D.create()
                step.setToRotation(math.radians(angle), adsk.core.Vector3D.create(*axis), adsk.core.Point3D.create(0, 0, 0))
                turn.transformBy(step)
        move = adsk.core.Matrix3D.create()
        move.translation = adsk.core.Vector3D.create(part["at"][0] / 10, part["at"][1] / 10, part["at"][2] / 10)
        turn.transformBy(move)
        tbm.transform(body, turn)
        return body

    owner = {pid: j["id"] for j in DATA["joints"] for pid in j["parts"]}
    links, axes = {}, {}
    for joint in DATA["joints"]:        # each moving assembly is one top-level component with its own axis line
        occ = root.occurrences.addNewComponent(I)
        occ.component.name = ("Moves - " + joint["name"])[:120]
        sketch = occ.component.sketches.add(occ.component.xYConstructionPlane)
        sketch.name = "Axis"
        o, d = joint["origin"], joint["axis"]
        axes[joint["id"]] = sketch.sketchCurves.sketchLines.addByTwoPoints(P(o), P([o[k] + d[k] * 20 for k in range(3)]))
        occ.component.isSketchFolderLightBulbOn = False
        links[joint["id"]] = occ

    groups, tops, top_of, made, failed = {}, {}, {}, 0, []
    for part in DATA["parts"]:
        if part["shape"] == "none" or part["status"] == "remove":
            continue
        if part["id"] in owner:
            holder = links[owner[part["id"]]]
        else:
            group = part["group"]
            if group not in groups:
                occ = root.occurrences.addNewComponent(I)
                occ.component.name = group
                groups[group], tops[group] = occ.component, occ
            holder = tops[group]
        top_of[part["id"]] = holder
        occ = holder.component.occurrences.addNewComponent(I)
        prefix = {"new": "NEW - ", "change": "CHANGE - "}.get(part["status"], "")
        occ.component.name = (prefix + part["name"] + " [" + part["id"] + "]")[:120]
        try:
            body = solid(part)
            added = occ.component.bRepBodies.add(body)
            added.name = part["name"]
            appearance = look(part["colour"])
            if appearance:
                added.appearance = appearance
            made += 1
        except Exception as e:
            failed.append(part["id"] + ": " + str(e)[:120])

    motions, joint_failed, notes = {}, [], []
    if DATA["joints"]:
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType      # joints need a design with history
        frame = adsk.core.ObjectCollection.create()
        for occ in tops.values():
            frame.add(occ)
        try:
            if frame.count:
                root.rigidGroups.add(frame, True).name = "Frame"
            for occ in tops.values():
                occ.isGrounded = True
        except Exception as e:
            notes.append("frame: " + str(e)[:100])
        for jid, occ in links.items():
            try:
                one = adsk.core.ObjectCollection.create()
                one.add(occ)
                root.rigidGroups.add(one, True)
            except Exception as e:
                notes.append(jid + " rigid: " + str(e)[:80])
        D = adsk.fusion.JointDirections
        for joint in DATA["joints"]:
            jid = joint["id"]
            try:
                on = joint.get("on")
                other = (links[owner[on]] if on in owner else top_of.get(on)) or next(iter(tops.values()), None)
                if other is None:
                    raise RuntimeError("nothing fixed to turn on")
                line = axes[jid].createForAssemblyContext(links[jid])
                geometry = adsk.fusion.JointGeometry.createByCurve(line, adsk.fusion.JointKeyPointTypes.StartKeyPoint)
                given = root.asBuiltJoints.createInput(links[jid], other, geometry)
                if joint["type"] == "slider":
                    given.setAsSliderJointMotion(D.ZAxisJointDirection)
                else:
                    given.setAsRevoluteJointMotion(D.ZAxisJointDirection)
                made_joint = root.asBuiltJoints.add(given)
                made_joint.name = joint["name"][:100]
                if joint["type"] == "slider":
                    motion = adsk.fusion.SliderJointMotion.cast(made_joint.jointMotion)
                    limits, scale = motion.slideLimits, 0.1
                else:
                    motion = adsk.fusion.RevoluteJointMotion.cast(made_joint.jointMotion)
                    limits, scale = motion.rotationLimits, math.pi / 180
                if "min" in joint:
                    limits.isMinimumValueEnabled = True
                    limits.minimumValue = joint["min"] * scale
                    limits.isMaximumValueEnabled = True
                    limits.maximumValue = joint["max"] * scale
                motions[jid] = (motion, joint["type"], scale)
            except Exception as e:
                joint_failed.append(jid + ": " + str(e)[:120])
        root.isJointsFolderLightBulbOn = False      # no joint glyphs in the pictures

    def set_pose(values):
        for jid, (motion, kind, scale) in motions.items():
            value = values.get(jid, 0.0) * scale
            if kind == "slider":
                motion.slideValue = value
            else:
                motion.rotationValue = value

    out = DATA["out"]
    os.makedirs(out, exist_ok=True)
    views = {}
    vp = app.activeViewport
    for name, orient in (("front", adsk.core.ViewOrientations.FrontViewOrientation),
                         ("right", adsk.core.ViewOrientations.RightViewOrientation),
                         ("top", adsk.core.ViewOrientations.TopViewOrientation),
                         ("iso", adsk.core.ViewOrientations.IsoTopRightViewOrientation)):
        cam = vp.camera
        cam.cameraType = (adsk.core.CameraTypes.PerspectiveCameraType if name == "iso"
                          else adsk.core.CameraTypes.OrthographicCameraType)
        cam.viewOrientation = orient
        cam.isFitView = True
        cam.isSmoothTransition = False
        vp.camera = cam
        vp.fit()
        path = os.path.join(out, name + ".png").replace("\\", "/")
        if vp.saveAsImageFile(path, 1400, 1000):
            views[name] = path
    step = os.path.join(out, "model.step").replace("\\", "/")
    em = design.exportManager
    em.execute(em.createSTEPExportOptions(step, root))
    archive = os.path.join(out, "model.f3d").replace("\\", "/")
    em.execute(em.createFusionArchiveExportOptions(archive, root))
    frames = []
    if motions and DATA["motion"]:
        cam = vp.camera
        cam.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
        cam.viewOrientation = adsk.core.ViewOrientations.IsoTopRightViewOrientation
        cam.isSmoothTransition = False
        vp.camera = cam
        vp.fit()
        cam = vp.camera            # keep the angle, aim at the whole sweep, back off until it all fits
        look = cam.target.vectorTo(cam.eye)
        look.normalize()
        target = P(DATA["view"]["centre"])
        half = max(cam.perspectiveAngle, 0.2) / 2
        distance = DATA["view"]["radius"] / 10 / math.sin(half) * 1.08
        cam.target = target
        cam.eye = adsk.core.Point3D.create(target.x + look.x * distance, target.y + look.y * distance,
                                           target.z + look.z * distance)
        cam.isFitView = False
        vp.camera = cam
        for n, values in enumerate(DATA["motion"]):
            set_pose(values)
            adsk.doEvents()
            path = os.path.join(out, "motion-%03d.png" % n).replace("\\", "/")
            if vp.saveAsImageFile(path, 900, 675):
                frames.append(path)
        set_pose({})
    print(json.dumps({"made": made, "failed": failed, "views": views, "step": step, "f3d": archive,
                      "document": doc.name, "joints": len(motions), "joint_failed": joint_failed,
                      "notes": notes, "frames": frames}))
'''


MOTION_FRAMES = 48


def motion_path(spec, frames=MOTION_FRAMES):
    """Joint values for each frame of the animation: every joint out to its max, back through to its min, home;
    a joint with no limits turns once."""
    path = []
    for n in range(frames):
        t = n / frames
        values = {}
        for joint in spec.get("joints", []):
            if "min" in joint:
                lo, hi = joint["min"], joint["max"]
                values[joint["id"]] = (hi * t * 4 if t < 0.25 else hi + (lo - hi) * (t - 0.25) * 2 if t < 0.75
                                       else lo * (1 - (t - 0.75) * 4))
            elif joint["type"] == "revolute":
                values[joint["id"]] = 360.0 * t
            values[joint["id"]] = round(values.get(joint["id"], 0.0), 3)
        path.append(values)
    return path


def _view_for(spec, path):
    """The sphere (centre, radius in mm) that holds the machine through the whole animation, for the camera."""
    parts = {p["id"]: p for p in _active(spec) if p["shape"] != "none"}
    if not parts:
        return {"centre": [0, 0, 0], "radius": 100}
    lo, hi = [1e9] * 3, [-1e9] * 3
    for values in (path[::2] or [{}]):
        moved = pose(spec, values) if values else {}
        for pid, part in parts.items():
            centre, axes_, half = _obb(part, moved.get(pid), shrink=0)
            for k in range(3):
                reach = sum(h * abs(a[k]) for h, a in zip(half, axes_))
                lo[k], hi[k] = min(lo[k], centre[k] - reach), max(hi[k], centre[k] + reach)
    return {"centre": [round((lo[k] + hi[k]) / 2, 1) for k in range(3)],
            "radius": round(max(math.sqrt(sum((hi[k] - lo[k]) ** 2 for k in range(3))) / 2, 10), 1)}


def fusion_script(spec, out_dir):
    active = {p["id"] for p in _active(spec) if p["shape"] != "none"}
    joints = [dict(j, parts=[pid for pid in j["parts"] if pid in active]) for j in spec.get("joints", [])]
    joints = [j for j in joints if j["parts"]]
    trimmed = dict(spec, joints=joints)
    path = motion_path(trimmed) if joints else []
    data = {"inches": spec.get("units_shown") == "inch", "out": str(out_dir).replace("\\", "/"), "project": spec["id"],
            "parts": [{k: p[k] for k in ("id", "name", "group", "status", "shape", "size", "diameter", "inner_diameter",
                                          "top_diameter", "length", "axis", "at", "rotate", "holes", "colour") if k in p}
                      for p in spec["parts"]],
            "joints": joints, "motion": path, "view": _view_for(trimmed, path)}
    for part in data["parts"]:
        if part["status"] in STATUS_COLOUR:
            part["colour"] = STATUS_COLOUR[part["status"]]
    encoded = base64.b64encode(json.dumps(data).encode("utf-8")).decode("ascii")
    return FUSION_SCRIPT.replace("__DATA__", encoded)


def build_in_fusion(spec):
    """A new Fusion design from the spec, plus four pictures, a STEP and an .f3d. {made, failed, views, step, f3d}."""
    import fusion_link
    out = _folder(spec["id"]) / "fusion"
    if out.is_dir():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    printed = fusion_link.run_script(fusion_script(spec, out), timeout=900)
    result = extract_json(printed)
    result["gif"] = _gif(out)
    spec["fusion"] = {"at": time.time(), "document": result.get("document"), "made": result.get("made"),
                      "failed": result.get("failed", []), "joints": result.get("joints", 0),
                      "joint_failed": result.get("joint_failed", [])}
    return result


def _gif(folder):
    """The motion frames Fusion saved, as one looping animation (motion.gif). Returns its path or None."""
    frames = sorted(Path(folder).glob("motion-*.png"))
    if not frames:
        return None
    from PIL import Image
    images = [Image.open(f).convert("RGB").resize((720, 540)) for f in frames]
    palette = images[len(images) // 2].quantize(colors=200)
    path = Path(folder) / "motion.gif"
    images = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    images[0].save(path, save_all=True, append_images=images[1:], duration=90, loop=0, optimize=True)
    for f in frames:
        f.unlink(missing_ok=True)
    return path


# ---------- The bench preview (three.js on the Jarvis page) ----------

PREVIEW_SETUP = """const M = (hex, metal, glow) => new THREE.MeshStandardMaterial({ color: hex, metalness: metal, roughness: metal > .5 ? .35 : .6, emissive: glow ? 0x0a4a52 : 0x000000 });
const turn = (o, r) => { const m = new THREE.Matrix4(), s = new THREE.Matrix4(); const axes = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 1, 0)]; for (let i = 0; i < 3; i++) if (r[i]) m.premultiply(s.makeRotationAxis(axes[i], r[i] * Math.PI / 180)); o.quaternion.setFromRotationMatrix(m); };
const AX = { x: [0, 0, Math.PI / 2], y: [Math.PI / 2, 0, 0], z: [0, 0, 0] };
const shape = (p) => {
  const mm = v => v / 1000; let g;
  if (p.s === 'box') g = new THREE.BoxGeometry(mm(p.size[0]), mm(p.size[2]), mm(p.size[1]));
  else if (p.s === 'sphere') g = new THREE.SphereGeometry(mm(p.d / 2), 24, 16);
  else if (p.s === 'tube') { const r = new THREE.Shape(); r.absarc(0, 0, mm(p.d / 2), 0, Math.PI * 2); const h = new THREE.Path(); h.absarc(0, 0, mm(p.id / 2), 0, Math.PI * 2, true); r.holes.push(h); g = new THREE.ExtrudeGeometry(r, { depth: mm(p.l), bevelEnabled: false, curveSegments: 28 }); g.translate(0, 0, -mm(p.l) / 2); g.rotateX(Math.PI / 2); }
  else g = new THREE.CylinderGeometry(mm((p.s === 'cone' ? p.td : p.d) / 2), mm(p.d / 2), mm(p.l), 28);
  if (p.s !== 'box' && p.s !== 'sphere') { const a = AX[p.ax]; g.rotateX(a[0]); g.rotateZ(a[2]); }
  const mesh = new THREE.Mesh(g, M(p.c, p.metal, p.glow)); mesh.castShadow = mesh.receiveShadow = true;
  const holder = new THREE.Group(); holder.add(mesh); turn(holder, p.r || [0, 0, 0]);
  holder.position.set(mm(p.at[0]), mm(p.at[2]), -mm(p.at[1])); return holder;
};"""


def preview_scene(spec):
    """The spec as a workshop scene: one step per group, one api.part per piece, pulled apart from the centre."""
    parts = [p for p in _active(spec) if p["shape"] != "none"]
    if not parts:
        raise ValueError("There's nothing with a shape to show.")
    bounds = [box(p) for p in parts]
    lo = [min(b[0][k] for b in bounds) for k in range(3)]
    hi = [max(b[1][k] for b in bounds) for k in range(3)]
    centre = [(lo[k] + hi[k]) / 2 for k in range(3)]
    span = max(hi[k] - lo[k] for k in range(3)) / 1000 or 0.1
    shift = [-centre[0], -centre[1], -lo[2]]           # stand it on the floor, centred
    steps = {}
    for p in parts:
        at = [p["at"][k] + shift[k] for k in range(3)]
        direction = [p["at"][k] - centre[k] for k in range(3)]
        length = math.sqrt(sum(d * d for d in direction)) or 1
        push = [round(d / length * span * 0.6, 4) for d in direction]
        data = {"s": p["shape"], "at": [round(v, 2) for v in at], "c": STATUS_COLOUR.get(p["status"], p["colour"]),
                "metal": 0.8 if any(w in p.get("material", "").lower() for w in ("steel", "alumin", "brass", "metal", "iron")) else 0.05,
                "glow": p["status"] == "new"}
        if p.get("rotate"):
            data["r"] = p["rotate"]
        if p["shape"] == "box":
            data["size"] = p["size"]
        else:
            data["d"] = p["diameter"]
            if p["shape"] != "sphere":
                data.update(l=p["length"], ax=p["axis"], id=p.get("inner_diameter", 0), td=p.get("top_diameter", 0))
        about = (f"{size_text(p, spec.get('units_shown', 'mm'))}, {p.get('material') or 'material unknown'}"
                 + (f", {p['spec']}" if p.get("spec") else "") + f". {p['status'].upper()}, sizes {p['sizes_from']}."
                 + (f" {p['notes']}" if p.get("notes") else ""))
        line = (f"api.part({json.dumps(p['name'])}, {json.dumps(about[:380])}, shape({json.dumps(data)}), "
                f"[{push[0]}, {push[2]}, {-push[1]}]);")
        steps.setdefault(p["group"], []).append(line)
    return {"title": spec["title"], "setup": PREVIEW_SETUP,
            "steps": [{"name": f"Placing the {group.lower()}", "code": "\n".join(lines)} for group, lines in steps.items()]}


def show_on_bench(spec):
    """Put the preview on the Workshop tab of the Jarvis page. Returns what the workshop says about the page."""
    import workshop
    made = preview_scene(spec)
    scene = {"id": f"blueprint-{spec['id']}"[:80], "title": spec["title"], "request": f"Blueprint: {spec['title']}",
             "setup": made["setup"], "steps": made["steps"], "versions": [], "created": time.time(),
             "updated": time.time(), "picture": False, "blueprint": spec["id"],
             "spoken": f"{spec['title']}, from the blueprint."}
    workshop._save(scene)
    workshop.open_scene(scene["id"])
    return workshop.on_screen()


# ---------- What the owner gets: measuring sheet, parts list, build packet ----------

def measuring_sheet(spec, out_dir):
    """Each photo that has measurements, with the lines drawn on it and lettered. Returns the image paths."""
    from PIL import Image, ImageDraw, ImageFont
    out_dir.mkdir(parents=True, exist_ok=True)
    made, files = [], photos(spec)
    by_photo = {}
    for m in spec.get("measurements", []):
        if m.get("photo") and m.get("line") and m["photo"] <= len(files):
            by_photo.setdefault(m["photo"], []).append(m)
    for number, items in sorted(by_photo.items()):
        image = Image.open(files[number - 1]).convert("RGB")
        draw = ImageDraw.Draw(image)
        w, h = image.size
        size = max(18, w // 40)
        try:
            font = ImageFont.truetype("arialbd.ttf", size)
        except OSError:
            font = ImageFont.load_default()
        for m in items:
            x1, y1, x2, y2 = (m["line"][0] * w, m["line"][1] * h, m["line"][2] * w, m["line"][3] * h)
            colour = (40, 220, 120) if m.get("value_mm") is not None else (255, 196, 0)
            draw.line((x1, y1, x2, y2), fill=(0, 0, 0), width=max(5, w // 220))
            draw.line((x1, y1, x2, y2), fill=colour, width=max(3, w // 320))
            for x, y in ((x1, y1), (x2, y2)):
                r = max(5, w // 200)
                draw.ellipse((x - r, y - r, x + r, y + r), fill=colour, outline=(0, 0, 0))
            tx, ty = (x1 + x2) / 2, (y1 + y2) / 2
            box_ = draw.textbbox((tx, ty), m["letter"], font=font, anchor="mm")
            pad = size // 4
            draw.rectangle((box_[0] - pad, box_[1] - pad, box_[2] + pad, box_[3] + pad), fill=(0, 0, 0))
            draw.text((tx, ty), m["letter"], fill=colour, font=font, anchor="mm")
        path = out_dir / f"measure-photo-{number}.jpg"
        image.save(path, quality=88)
        made.append(path)
    return made


def write_parts_list(spec, out_dir):
    units = spec.get("units_shown", "mm")
    rows = bill(spec)
    header = ["Status", "Qty", "Name", "Group", "Size (mm)", "Material", "Make/buy", "Standard or product",
              "Where to buy", "Cost each (USD)", "Sizes from", "Confidence", "Notes"]
    with open(out_dir / "parts-list.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in rows:
            writer.writerow([r["status"], r["qty"], r["name"], r["group"], r["size_mm"], r["material"], r["make"],
                             r["spec"], r["buy"], r["cost_each"] if r["cost_each"] is not None else "",
                             r["sizes_from"], round(r["confidence"], 2), r["notes"]])
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        book = Workbook()
        sheet = book.active
        sheet.title = "Parts"
        sheet.append(header)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        fills = {"new": "D9F4F7", "change": "FCE9CF"}
        for r in rows:
            sheet.append([r["status"], r["qty"], r["name"], r["group"], r["size_mm"], r["material"], r["make"],
                          r["spec"], r["buy"], r["cost_each"], r["sizes_from"], round(r["confidence"], 2), r["notes"]])
            if r["status"] in fills:
                for cell in sheet[sheet.max_row]:
                    cell.fill = PatternFill("solid", fgColor=fills[r["status"]])
        last = sheet.max_row
        sheet.append([])
        sheet.append(["", "", "Total for new and changed parts", "", "", "", "", "", "",
                      f'=SUMPRODUCT((A2:A{last}<>"existing")*B2:B{last}*J2:J{last})'])
        for column, width in zip("ABCDEFGHIJKLM", (9, 5, 28, 14, 26, 22, 10, 30, 30, 10, 14, 10, 50)):
            sheet.column_dimensions[column].width = width
        measures = book.create_sheet("Measurements")
        measures.append(["Letter", "What", "Estimate (mm)", "Measured (mm)", "Measured (in)", "Why"])
        for cell in measures[1]:
            cell.font = Font(bold=True)
        for n, m in enumerate(spec.get("measurements", []), start=2):
            measures.append([m["letter"], m["what"], m.get("estimate_mm"), m.get("value_mm"),
                             f"=IF(D{n}=\"\",\"\",D{n}/25.4)", m.get("why", "")])
        for column, width in zip("ABCDEF", (8, 50, 14, 14, 14, 50)):
            measures.column_dimensions[column].width = width
        book.save(out_dir / "parts-list.xlsx")
    except PermissionError:
        pass        # the owner has it open in Excel; the CSV is still fresh


def _html_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _img(path, alt):
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    kind = {".png": "png", ".gif": "gif"}.get(Path(path).suffix.lower(), "jpeg")
    return f'<img src="data:image/{kind};base64,{data}" alt="{_html_escape(alt)}">'


def write_packet(spec, out_dir, sheets):
    """One self-contained page to print or keep on a phone in the garage."""
    e = _html_escape
    c = checks(spec)
    units = spec.get("units_shown", "mm")
    plan = spec.get("plan") or {}
    rows = bill(spec)
    views = [(name, out_dir / f"view-{name}.png") for name in ("iso", "front", "right", "top")]
    def money(value):
        return "" if value is None else f"${value:,.2f}"
    parts_html = "".join(
        f"<tr class='{r['status']}'><td>{e(r['status'])}</td><td>{r['qty']}</td><td>{e(r['name'])}</td>"
        f"<td>{e(r['size_mm'])}</td><td>{e(r['material'])}</td><td>{e(r['make'])}</td><td>{e(r['spec'])}</td>"
        f"<td>{e(r['buy'])}</td><td>{money(r['cost_each'])}</td>"
        f"<td>{e(r['sizes_from'])} ({r['confidence']:.0%})</td><td>{e(r['notes'])}</td></tr>" for r in rows)
    measure_rows = "".join(
        f"<tr><td><b>{e(m['letter'])}</b></td><td>{e(m['what'])}</td>"
        f"<td>{_length(m['estimate_mm'], units) if m.get('estimate_mm') else ''}</td>"
        f"<td>{_length(m['value_mm'], units) if m.get('value_mm') is not None else '<span class=blank>________</span>'}</td>"
        f"<td>{e(m.get('why', ''))}</td></tr>" for m in spec.get("measurements", []))

    def items(key):
        return "".join(f"<li>{e(x)}</li>" for x in plan.get(key) or [])
    changes = "".join(f"<li><b>{e(x.get('what', ''))}</b>: {e(x.get('why', ''))} <i>{e(x.get('how', ''))}</i></li>"
                      for x in plan.get("changes") or [] if isinstance(x, dict))
    wiring = "".join(f"<tr><td>{e(w.get('from', ''))}</td><td>{e(w.get('to', ''))}</td><td>{e(w.get('what', ''))}</td></tr>"
                     for w in plan.get("wiring") or [] if isinstance(w, dict))
    problems = ([f"{x['a']} and {x['b']} occupy the same space ({x['depth_mm']} mm)" for x in c["clashes"]]
                + [f"{x['name']} isn't touching anything" for x in c["floating"]]
                + [f"Moving {x['joint_name']}: {x['a']} runs into {x['b']} at {x['at']}{x['unit']}" for x in c["motion"]])
    names = {p["id"]: p["name"] for p in spec["parts"]}

    def travel(j):
        unit = "mm" if j["type"] == "slider" else "°"
        if "min" in j:
            return f"{j['min']:g}{unit} to {j['max']:g}{unit}"
        return "turns all the way round" if j["type"] == "revolute" else "free"
    joint_rows = "".join(
        f"<tr><td><b>{e(j['name'])}</b></td><td>{'turns' if j['type'] == 'revolute' else 'slides'}</td>"
        f"<td>{e(travel(j))}</td><td>{e(', '.join(names.get(p, p) for p in j['parts']))}</td>"
        f"<td>{e(names.get(j.get('on'), 'the frame'))}</td><td>{e(names.get(j.get('drive'), j.get('drive') or 'by hand / free'))}</td>"
        f"<td>{e(j.get('notes', ''))}</td></tr>" for j in spec.get("joints", []))
    motion_gif = out_dir / "motion.gif"
    power = c["power"]
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(spec['title'])} - build packet</title>
<style>
body{{font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:0 auto;max-width:1100px;padding:24px;color:#1b1f23;background:#fff}}
h1{{margin:0 0 4px}} h2{{margin-top:32px;border-bottom:2px solid #1b1f23;padding-bottom:4px}}
.meta{{color:#555}} table{{border-collapse:collapse;width:100%;font-size:12.5px}} td,th{{border:1px solid #ccd;padding:4px 6px;vertical-align:top;text-align:left}}
th{{background:#eef1f4}} tr.new td{{background:#e3f7f9}} tr.change td{{background:#fdf0dc}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}} img{{width:100%;border:1px solid #ccd;border-radius:4px}}
.blank{{color:#999}} .facts span{{display:inline-block;margin:0 18px 6px 0}} .warn{{color:#a33}}
@media print{{h2{{break-after:avoid}} .grid img{{break-inside:avoid}} body{{padding:0}}}}
</style></head><body>
<h1>{e(spec['title'])}</h1>
<div class="meta">Build packet from Jarvis, {datetime.date.today():%B %d, %Y}. Sizes in {'inches' if units == 'inch' else 'millimetres'}; the parts list also gives mm.
Cyan rows and parts are new, orange ones change.</div>
<p>{e(spec.get('summary', ''))}</p>
<div class="facts"><span><b>Overall</b> {' x '.join(_length(v, units) for v in c['overall_mm'])} (W x D x H)</span>
<span><b>Weight</b> about {c['mass_kg']} kg{f" (+{c['mass_unknown']} parts unknown)" if c['mass_unknown'] else ''}</span>
<span><b>New parts cost</b> about ${c['cost_usd']:,.2f}</span>
{f"<span><b>Power</b> {power['draw_w']} W drawn of {power['supply_w']} W {'(enough)' if power['ok'] else '<b class=warn>(not enough spare)</b>'}</span>" if power['draw_w'] else ''}</div>
{('<h2>Plan: ' + e(plan.get('goal', '')) + '</h2><p>' + e(plan.get('summary', '')) + '</p>') if plan else ''}
{('<h3>What changes and why</h3><ul>' + changes + '</ul>') if changes else ''}
<h2>The model</h2><div class="grid">{''.join(_img(p, n) for n, p in views if p.is_file()) or '<p>Build it in Fusion to get the pictures.</p>'}</div>
{('<h2>How it moves</h2><p>Each of these is a joint in the Fusion model: drag the part, or right-click the joint and Animate. ' + ('Every joint is moved through its range in the animation, all at once.</p><div class="grid">' + _img(motion_gif, 'motion') + '</div>' if motion_gif.is_file() else '</p>') + '<table><tr><th>Joint</th><th></th><th>Travel from the pose shown</th><th>Moving parts</th><th>On</th><th>Driven by</th><th>Notes</th></tr>' + joint_rows + '</table>') if joint_rows else ''}
<h2>Measurements</h2><p>Measure these on the real machine and tell Jarvis ("A is 24 and a half inches"); the model is rebuilt around them.</p>
<table><tr><th></th><th>From where to where</th><th>Estimate</th><th>Measured</th><th>Why it matters</th></tr>{measure_rows}</table>
<div class="grid">{''.join(_img(p, 'measuring photo') for p in sheets)}</div>
<h2>Parts list</h2><table><tr><th>Status</th><th>Qty</th><th>Part</th><th>Size (mm)</th><th>Material</th><th>Make / buy</th><th>Standard or product</th><th>Where</th><th>Each</th><th>Sizes from</th><th>Notes</th></tr>{parts_html}</table>
{('<h2>Wiring</h2><table><tr><th>From</th><th>To</th><th>Cable / signal</th></tr>' + wiring + '</table>') if wiring else ''}
{('<h2>Software</h2><ul>' + items('software') + '</ul>') if plan.get('software') else ''}
{('<h2>Build steps</h2><ol>' + items('steps') + '</ol>') if plan.get('steps') else ''}
{('<h2>Risks and safety</h2><ul>' + items('risks') + '</ul>') if plan.get('risks') else ''}
<h2>Checks</h2><ul>{''.join(f'<li class=warn>{e(p)}</li>' for p in problems) or '<li>No clashes or floating parts found.</li>'}
<li>{len(c['guesses'])} existing parts are still estimates from the photos{': ' + e(', '.join(sorted({g['name'] for g in c['guesses']}))) if c['guesses'] else ''}.</li></ul>
{('<h2>Still unknown</h2><ul>' + ''.join(f'<li>{e(u)}</li>' for u in spec.get('unknowns', [])) + '</ul>') if spec.get('unknowns') else ''}
<p class="meta">How the scale was set: {e(spec.get('scale_basis', ''))}</p>
</body></html>"""
    path = out_dir / "build-packet.html"
    path.write_text(html, encoding="utf-8")
    return path


def _pdf(html_path):
    """Print the packet to PDF with headless Chrome. Returns the path, or None when Chrome isn't there."""
    import testing_guard
    if testing_guard.under_test():
        return None
    try:
        import chrome_browser
        if not chrome_browser.CHROME:
            return None
        pdf = html_path.with_suffix(".pdf")
        subprocess.run([chrome_browser.CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", html_path.as_uri()], timeout=90, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return pdf if pdf.is_file() else None
    except (OSError, subprocess.SubprocessError):
        return None


def outbox(spec):
    name = re.sub(r'[<>:"/\\|?*]+', "", spec["title"]).strip() or "Machine"
    return OUTBOX / name


def packet(spec):
    """Write everything the owner builds from into Documents\\Jarvis Blueprints\\<name>. Returns the folder."""
    out = outbox(spec)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("measure-photo-*.jpg"):
        old.unlink(missing_ok=True)
    fusion = _folder(spec["id"]) / "fusion"
    for name in ("iso", "front", "right", "top"):
        if (fusion / f"{name}.png").is_file():
            shutil.copyfile(fusion / f"{name}.png", out / f"view-{name}.png")
    for name in ("model.step", "model.f3d", "motion.gif"):
        if not (fusion / name).is_file():
            (out / name).unlink(missing_ok=True)       # an old one would no longer match the model
        else:
            shutil.copyfile(fusion / name, out / name)
    sheets = measuring_sheet(spec, out)
    write_parts_list(spec, out)
    (out / "spec.json").write_text(json.dumps({k: v for k, v in spec.items() if k != "history"}, ensure_ascii=False,
                                              indent=1), encoding="utf-8")
    page = write_packet(spec, out, sheets)
    _pdf(page)
    return out


# ---------- Running the long steps in the background ----------

def _announce(text, note):
    import hud
    hud.commands.put({"label": "Blueprint", "say": text, "note": note})


def _status_line(spec):
    c = checks(spec)
    bits = [f'"{spec["title"]}": {_count(spec)}, overall {" x ".join(_length(v, spec.get("units_shown", "mm")) for v in c["overall_mm"])}']
    if c["open_measurements"]:
        bits.append(f"measurements still to take: {', '.join(c['open_measurements'])}")
    if c["guesses"]:
        bits.append(f"{len(c['guesses'])} parts still estimated from photos")
    if c["clashes"]:
        bits.append(f"{len(c['clashes'])} clashes (" + "; ".join(f"{x['a']} / {x['b']}" for x in c["clashes"][:4]) + ")")
    if c["floating"]:
        bits.append(f"{len(c['floating'])} floating parts")
    if c["joints"]:
        bits.append(f"{c['joints']} joints" + (f", and moving them: " + "; ".join(
            f"{x['a']} hits {x['b']} at {x['at']}{x['unit']} on {x['joint_name']}" for x in c["motion"][:4])
            if c["motion"] else ", all moving clear"))
    if c["power"]["draw_w"]:
        bits.append(f"power {c['power']['draw_w']} W of {c['power']['supply_w']} W" if c["power"]["supply_w"]
                    else f"power {c['power']['draw_w']} W drawn, no supply with a known rating")
    if c["cost_usd"]:
        bits.append(f"new parts about ${c['cost_usd']:,.0f}")
    return "; ".join(bits) + "."


def _run(kind, job):
    if not _work.acquire(blocking=False):
        raise ValueError(f"I'm still working on the blueprint ({STATE['busy']}). It'll say when it's done.")
    with _lock:
        STATE.update(busy=kind, started=time.time(), error="")

    def awake(on):
        """Keep the PC from sleeping by itself while this thread works (a deliberate sleep still wins)."""
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if on else 0x80000000)
        except (AttributeError, OSError):
            pass

    def go():
        awake(True)
        try:
            spoken, note = job()
            _announce(spoken, note)
        except Exception as e:
            reason = str(e) if isinstance(e, (ValueError, RuntimeError)) else type(e).__name__
            print(f"(blueprint: {kind} failed: {e!r})", flush=True)
            with _lock:
                STATE["error"] = reason
            _announce(f"The blueprint {kind} didn't finish, sir: {reason[:200]}",
                      f"[BLUEPRINT] {kind} failed: {reason[:600]}. Nothing was changed.")
        finally:
            awake(False)
            with _lock:
                STATE["busy"] = ""
            _work.release()
    threading.Thread(target=go, daemon=True, name=f"blueprint-{kind}").start()


def _finish_round(spec, label, check_after=False):
    """After the spec changes: save, rebuild in Fusion when it is running, preview on the bench, write the packet."""
    import fusion_link
    save(spec, label)
    fusion_note = ""
    if fusion_link.available():
        try:
            result = build_in_fusion(spec)
            if check_after:
                spec = _visual_check(spec)
                result = build_in_fusion(spec)
            fusion_note = f" Built in Fusion as a new design ({result.get('made')} bodies"
            fusion_note += f", {result['joints']} working joints)." if result.get("joints") else ")."
            if check_after:
                fusion_note += " Checked against the photos and rebuilt."
            if result.get("failed"):
                fusion_note += f" {len(result['failed'])} parts couldn't be made: {'; '.join(result['failed'][:3])}."
            if result.get("joint_failed"):
                fusion_note += f" {len(result['joint_failed'])} joints couldn't be made: {'; '.join(result['joint_failed'][:3])}."
            save(spec)
        except Exception as e:
            fusion_note = f" Fusion couldn't build it: {str(e)[:300]}."
    else:
        fusion_note = " Fusion isn't running, so there's no Fusion model or STEP this time."
    shown = ""
    try:
        shown = show_on_bench(spec)
    except Exception as e:
        shown = f" The bench preview failed: {e!r}."
    folder = packet(spec)
    return spec, fusion_note, shown, folder


def _visual_check(spec):
    shots = []
    for name in ("front", "right", "top", "iso"):
        path = _folder(spec["id"]) / "fusion" / f"{name}.png"
        if path.is_file():
            shots.append(_jpeg(path.read_bytes(), 1200))
    if not shots:
        return spec
    images = _photo_bytes(spec, 1200) + shots
    raw = ask(SYSTEM_CHECK, f"{len(images) - len(shots)} photographs, then {len(shots)} pictures of the CAD model "
                            f"(front, right, top, angle). The spec:\n{_spec_for_prompt(spec)}", images)
    return tidy(raw, keep=spec)


# ---------- What the tool does ----------

def start(source, about=""):
    """New project from photos: Fable reads them, then the model, the bench preview and the packet are made."""
    images = _gather(source)
    title = about.strip() or "machine"
    project_id = _slug(title)
    folder = _folder(project_id)
    (folder / "photos").mkdir(parents=True, exist_ok=True)
    for n, data in enumerate(images, 1):
        (folder / "photos" / f"{n:02d}.jpg").write_bytes(data)
    _set_current(project_id)

    def job():
        raw = ask(SYSTEM_READ, f"{len(images)} photographs of the owner's machine, numbered from 1 in the order "
                               f"shown. What the owner says about it: {about or 'nothing yet'}", images)
        spec = tidy(raw, keep={"id": project_id, "created": time.time(), "source": str(source)[:300],
                               "photo_count": len(images)})
        spec, fusion_note, shown, folder_out = _finish_round(spec, "read from photos", check_after=True)
        c = checks(spec)
        count = len(c["open_measurements"])
        built = " It's in Fusion and on the workshop bench." if "Fusion as" in fusion_note else " It's on the workshop bench."
        return (f"I've drawn up {spec['title']} from the photos, sir: {_count(spec)}.{built} "
                + (f"To make it exact there are {count} measurements to take, lettered on the photos in Documents, "
                   "Jarvis Blueprints." if count else "There's nothing left to measure."),
                f"[BLUEPRINT] Read the photos into a spec. {_status_line(spec)}{fusion_note}{shown} Packet: {folder_out}. "
                f"The owner gives measurements with blueprint(action=measure, request='A is 24 in, B 610 mm').")
    _run("read", job)
    how_long = "a few minutes" if len(images) <= 4 else "ten to twenty minutes with this many photos"
    return (f"Reading {len(images)} photo{'s' if len(images) != 1 else ''} into a blueprint. That takes {how_long} "
            "(read, build in Fusion with its joints, check against the photos); I'll say when it's ready.")


def measure(text):
    spec = load()
    values = parse_measurements(text, spec.get("units_shown", "inch"))
    if not values:
        raise ValueError('Give each measurement with its letter, like "A is 24 and a half inches, B 610 mm".')
    apply_measurements(spec, values)
    save(spec, "measured " + ", ".join(values))
    said = ", ".join(f"{k} {_length(v, spec.get('units_shown', 'mm'))}" for k, v in values.items())

    def job():
        current = load()
        raw = ask(SYSTEM_REVISE, "The owner measured the real machine: " + "; ".join(
            f"{m['letter']} ({m['what']}) = {m['value_mm']} mm" for m in current["measurements"] if m.get("value_mm") is not None)
            + f"\n\nThe spec:\n{_spec_for_prompt(current)}", _photo_bytes(current, 1200))
        new = tidy(raw, keep=current)
        apply_measurements(new, {m["letter"]: m["value_mm"] for m in current["measurements"]
                                 if m.get("value_mm") is not None and m["letter"] in {x["letter"] for x in new["measurements"]}})
        new, fusion_note, shown, folder_out = _finish_round(new, "reworked around measurements")
        left = checks(new)["open_measurements"]
        return (f"The blueprint is reworked around your measurements, sir." + (f" Still to measure: {', '.join(left)}." if left else " That's every measurement."),
                f"[BLUEPRINT] Reworked around {said}. {_status_line(new)}{fusion_note}{shown} Packet: {folder_out}.")
    _run("measurements", job)
    return f"Recorded {said}. Reworking the model around them now; I'll say when it's rebuilt."


def revise(text):
    spec = load()

    def job():
        raw = ask(SYSTEM_REVISE, f"The owner's correction: {text}\n\nThe spec:\n{_spec_for_prompt(spec)}",
                  _photo_bytes(spec, 1200))
        new, fusion_note, shown, folder_out = _finish_round(tidy(raw, keep=spec), "corrected: " + text[:80])
        return ("The blueprint is corrected, sir.", f"[BLUEPRINT] Corrected ({text[:200]}). {_status_line(new)}{fusion_note}{shown} Packet: {folder_out}.")
    _run("correction", job)
    return "Correcting the blueprint; I'll say when it's rebuilt."


def upgrade(goal):
    spec = load()
    if not goal.strip():
        raise ValueError("Say what it should become, like 'an AI robot arm that sorts parts by colour'.")

    def job():
        raw = ask(SYSTEM_UPGRADE, f"What the owner wants it to become: {goal}\n\nThe spec of the machine as it is:\n"
                                  f"{_spec_for_prompt(spec)}", _photo_bytes(spec, 1200))
        new = tidy(raw, keep=spec)
        if not isinstance(new.get("plan"), dict):
            new["plan"] = {"goal": goal}
        new["plan"].setdefault("goal", goal)
        new, fusion_note, shown, folder_out = _finish_round(new, "upgrade: " + goal[:80])
        c = checks(new)
        added = [p for p in _active(new) if p["status"] == "new"]
        changed = [p for p in _active(new) if p["status"] == "change"]
        return (f"The upgrade is designed, sir: {len(added)} new parts and {len(changed)} changes, about "
                f"${c['cost_usd']:,.0f} to buy. The build packet is in Documents, Jarvis Blueprints.",
                f"[BLUEPRINT] Designed the upgrade ({goal[:200]}). {(new['plan'] or {}).get('summary', '')[:600]} "
                f"{_status_line(new)}{fusion_note}{shown} Packet: {folder_out}.")
    _run("upgrade", job)
    return "Designing the upgrade. It takes ten to twenty minutes; I'll say when the plan and model are ready."


def rebuild():
    spec = load()

    def job():
        new, fusion_note, shown, folder_out = _finish_round(spec, "")
        return ("The blueprint is rebuilt, sir.", f"[BLUEPRINT] Rebuilt. {_status_line(new)}{fusion_note}{shown} Packet: {folder_out}.")
    _run("rebuild", job)
    return "Rebuilding the model and packet."


def check():
    spec = load()

    def job():
        import fusion_link
        if not fusion_link.available():
            raise RuntimeError("Fusion isn't running, and the check compares Fusion's pictures with the photos")
        build_in_fusion(spec)
        new, fusion_note, shown, folder_out = _finish_round(_visual_check(spec), "checked against the photos")
        return ("I've checked the model against the photos and fixed what disagreed, sir.",
                f"[BLUEPRINT] Checked. {_status_line(new)}{fusion_note}{shown} Packet: {folder_out}.")
    _run("check", job)
    return "Comparing the model with the photos; a couple of minutes."


def undo():
    spec = load()
    versions = sorted((_folder(spec["id"]) / "versions").glob("*.json"))
    if not versions:
        raise ValueError("There's nothing to undo.")
    previous = versions[-1]
    (_folder(spec["id"]) / "spec.json").write_text(previous.read_text(encoding="utf-8"), encoding="utf-8")
    previous.unlink()
    return "Took back the last change. Say rebuild to update Fusion and the packet."


def status():
    spec = load()
    c = checks(spec)
    with _lock:
        busy = STATE["busy"]
    lines = [_status_line(spec)]
    if busy:
        lines.insert(0, f"Working on: {busy} (for {round(time.time() - STATE['started'])} s).")
    rows = bill(spec)
    lines.append("Parts: " + "; ".join(f"{r['qty']} x {r['name']} ({r['size_mm']}, {r['status']})" for r in rows[:40]))
    open_ = [m for m in spec.get("measurements", []) if m.get("value_mm") is None]
    if open_:
        lines.append("To measure: " + "; ".join(f"{m['letter']}: {m['what']} (estimate {_length(m['estimate_mm'] or 0, spec.get('units_shown', 'mm'))})" for m in open_))
    if spec.get("plan"):
        lines.append("Plan: " + str(spec["plan"].get("summary", ""))[:600])
    lines.append(f"Files: {outbox(spec)}")
    return "\n".join(lines)


def open_project(words=""):
    found = projects()
    if not found:
        raise ValueError("There are no blueprint projects yet.")
    words = (words or "").lower().split()
    pick = next((p for p in found if all(w in p["title"].lower() for w in words)), None) if words else found[0]
    if not pick:
        raise ValueError("No blueprint matches that. There are: " + ", ".join(p["title"] for p in found[:8]))
    _set_current(pick["id"])
    spec = load(pick["id"])
    return f"Opened {spec['title']}. " + show_on_bench(spec) + " " + _status_line(spec)
