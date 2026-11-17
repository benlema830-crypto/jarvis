"""Cursor companion: a small Jarvis orb that rides along beside the mouse pointer, with his replies in a speech
bubble next to it.

"Follow my cursor" turns it on and "go back to normal" turns it off (the cursor_companion tool); the choice is
saved, so it comes back after a restart. While it's on, the desktop app tucks its corner orb away (it reads
`cursor_companion` from /settings).

The orb is a miniature of the page's orb (hud/shell-orb.js): a hollow hologram shell of block outlines stacked in
rings, with tiny sparks inside, coloured by his state (standby, listening, thinking, speaking). Its blocks step in
and out with what he is doing; it never bounces. The bubble is the page's dark panel with its teal mono label. Both are overlay_ui layers: on top, never
focused, and the mouse passes through them, so they can't take a click. They step aside while a full-screen app
(a game, a video) is in front.
"""
import math
import threading
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import overlay_ui as ui

ORB = 76                       # the orb's window, in pixels at 100% scaling (the shell itself is ~55)
FRAMES = 48                    # one animation loop
FPS = 24
OFFSET = (16, 20)              # from the pointer's tip to the orb window's corner
BUBBLE_WIDTH, BUBBLE_LINES = 300, 5
HOLD = 9.0                     # seconds a finished reply stays in the bubble
PREF = "cursor_companion"

_lock = threading.Lock()
_frames = {}                   # (state, scale) -> [Image]
_companion = None


# ---------- The orb ----------

_STATES = ("standby", "listening", "thinking", "speaking", "offline")
_OUTER = ((-60, 5), (-30, 9), (0, 10), (30, 9), (60, 5))     # rings of the outer shell: latitude in degrees, blocks
_INNER = ((-40, 5), (0, 7), (40, 5))                         # the inner shell, turning the other way
_STEP = .07                                                  # blocks move out in whole steps of this (1 = the shell's radius)


def _noise(*values):
    """A fixed pseudo-random number in 0..1 for these values (the same every run, so the loop repeats exactly)."""
    x = math.sin(sum(v * w for v, w in zip(values, (127.1, 311.7, 74.7, 19.3))) + 4.1) * 43758.5453
    return x - math.floor(x)


def _steps_out(state, phase, voice, lat, lon, ring, block, direction):
    """How many steps a block of the outer shell sits out at this point of the loop: one pattern per state,
    the same patterns as the page's orb. Everything repeats exactly once per loop."""
    front = math.acos(max(-1.0, min(1.0, math.cos(lat) * math.sin(lon) * _COS_PITCH + math.sin(lat) * _SIN_PITCH)))
    if state == "listening":          # ripples spreading from the side facing you
        return round(1.5 * math.sin(front * 6 - phase * math.tau * 2) * math.exp(-front * .8))
    if state == "thinking":           # blocks pop at random, and a scan line sweeps round
        pop = 1.6 if _noise(ring, block, math.floor(phase * 4)) > .74 else 0
        away = (lon - phase * math.tau + math.pi) % math.tau - math.pi
        return round(pop + 1.4 * math.exp(-away * away * 6) * math.cos(lat))
    if state == "speaking":           # his voice pushes the middle band out, in lobes that travel round the ring
        lobe = .5 + .5 * math.sin(lon * 3 + phase * math.tau * direction + ring)
        return round(3.2 * voice * (.25 + lobe * lobe) * math.cos(lat) ** .6)
    if state == "standby":            # calm: one band climbing from the bottom to the top
        away = lat / (math.pi / 2) - (-1.25 + 2.5 * phase)
        return round(1.2 * math.exp(-away * away * 9))
    return 0


_PITCH = .32                       # tipped towards you a little, so the top shows
_COS_PITCH, _SIN_PITCH = math.cos(_PITCH), math.sin(_PITCH)


def render_orb(state="standby", frame=0, s=1.0):
    """One frame of the little hologram shell, RGBA, ORB*s pixels square.

    Two shells of block outlines stacked in rings, each ring turning on its own, a dashed arc between them and tiny
    white sparks inside. Nothing solid, nothing in the middle, and it does not bounce: only the blocks move. A soft
    dark disc sits behind the light so it still reads when the pointer is over a white window."""
    state = state if state in _STATES else "standby"
    colour = np.array(ui.CORE.get(state, ui.CORE["standby"]), dtype=np.float32) / 255
    white = np.array(ui.CORE_WHITE, dtype=np.float32) / 255
    size = round(ORB * s)
    k = 3                                                   # drawn 3x and scaled down, for smooth edges
    n = size * k
    phase = (frame % FRAMES) / FRAMES
    radius = n * .36                                        # where the outer blocks rest; it never changes
    centre = (n - 1) / 2
    voice = abs(math.sin(phase * math.pi * 3)) ** 1.4 * (.6 + .4 * math.sin(phase * math.tau)) if state == "speaking" else 0
    # Rings turn by whole block-widths per loop, so the last frame runs into the first. Thinking clicks them round.
    if state == "thinking":
        clicks = phase * 2
        turned = (math.floor(clicks) + (clicks % 1) ** 2 * (3 - 2 * (clicks % 1))) / 2 * 2
    else:
        turned = phase

    def project(lat, lon, reach):
        x, y, z = math.cos(lat) * math.cos(lon) * reach, math.sin(lat) * reach, math.cos(lat) * math.sin(lon) * reach
        y, z = y * _COS_PITCH - z * _SIN_PITCH, y * _SIN_PITCH + z * _COS_PITCH
        near = 4.6 / (4.6 - z)
        return centre + x * radius * near, centre - y * radius * near, z

    light = Image.new("L", (n, n), 0)                       # everything in his colour
    hot = Image.new("L", (n, n), 0)                         # the white sparks
    pen, spark_pen = ImageDraw.Draw(light), ImageDraw.Draw(hot)
    thin, wide = max(1, round(.55 * k * s)), max(2, round(.85 * k * s))
    strokes = []                                            # (depth, points, brightness, width, fill), far ones drawn first

    def quad(corners, outer, inner, bright, lit):
        top = [project(a, b, outer) for a, b in corners]
        depth = sum(p[2] for p in top) / 4
        shade = bright * (1 if depth > 0 else .3)           # the far side is dimmer
        face = [(x, y) for x, y, _ in top]
        strokes.append((depth, face + face[:1], shade, wide if inner else thin, shade * lit))
        if inner:                                           # the block's sides, down to its inner end
            base = [project(a, b, inner) for a, b in corners]
            for (x1, y1, _), (x2, y2, _) in zip(top, base):
                strokes.append((depth - .01, [(x1, y1), (x2, y2)], shade * .4, thin, 0))

    def block(lat, lon, half_lat, half_lon, outer, inner, bright, lit):
        quad([(lat - half_lat, lon - half_lon), (lat - half_lat, lon + half_lon),
              (lat + half_lat, lon + half_lon), (lat + half_lat, lon - half_lon)], outer, inner, bright, lit)

    for ring, (degrees, count) in enumerate(_OUTER):
        lat, direction = math.radians(degrees), 1 if ring % 2 else -1
        for b in range(count):
            lon = (b + direction * turned) / count * math.tau
            out = _steps_out(state, phase, voice, lat, lon, ring, b, direction)
            block(lat, lon, math.radians(12), math.pi / count * .78, 1 + out * _STEP, .82, 1, .1 + .13 * max(0, out))
    for pole in (1, -1):                                    # one small pin closes each pole
        quad([(pole * math.radians(78), math.pi / 4 + quarter * math.pi / 2) for quarter in range(4)], 1, .82, .9, .18)
    for ring, (degrees, count) in enumerate(_INNER):
        lat, direction = math.radians(degrees), -1 if ring % 2 else 1
        for b in range(count):
            block(lat, (b + direction * phase) / count * math.tau, math.radians(15), math.pi / count * .7, .58, 0, .5, 0)
    # A dashed arc between the two shells, tilted, creeping round by one dash per loop.
    for dash in range(14):
        points = []
        for i in range(4):
            u = (dash + turned + i / 3 * .55) / 14 * math.tau
            lat, lon = math.asin(math.sin(u) * math.sin(.6)), math.atan2(math.sin(u) * math.cos(.6), math.cos(u))
            points.append(project(lat, lon + .7, .72))
        depth = sum(p[2] for p in points) / 4
        strokes.append((depth, [(x, y) for x, y, _ in points], .55 if depth > 0 else .16, thin, 0))
    for _, points, bright, width, fill in sorted(strokes, key=lambda stroke: stroke[0]):
        if fill and len(points) > 3:
            pen.polygon(points[:4], fill=round(255 * min(1, fill)))
        pen.line(points, fill=round(255 * min(1, bright)), width=width)

    # Tiny sparks inside the shell: a jagged white hair that lives three frames and re-forms on each of them.
    busy = {"standby": 3, "listening": 6, "thinking": 12, "speaking": 10}.get(state, 0)
    for i in range(busy):
        seed = _STATES.index(state) * 100 + i
        age = (frame - math.floor(_noise(seed, 1) * FRAMES)) % FRAMES
        if age > 2:
            continue
        lat, lon = math.asin(_noise(seed, 2) * 1.6 - .8), _noise(seed, 3) * math.tau
        reach, points = .5 + .24 * _noise(seed, 4), []
        for j in range(4):
            wobble = (_noise(seed, 5, j, age) - .5) * .16
            points.append(project(lat + j * .07 + wobble, lon + j * .09 * (1 if seed % 2 else -1) - wobble, reach)[:2])
        spark_pen.line(points, fill=round(255 * (1 - age * .28)), width=thin)

    blur = ImageFilter.GaussianBlur
    lit = np.asarray(light, np.float32) / 255 + np.asarray(light.filter(blur(k * s * 2.2)), np.float32) / 255 * .9
    sparks = np.asarray(hot, np.float32) / 255 + np.asarray(hot.filter(blur(k * s * 1.6)), np.float32) / 255 * 1.4
    glow = np.clip(colour * lit[..., None] + white * sparks[..., None], 0, 1)
    glow_alpha = glow.max(axis=2)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    d = np.hypot(xx - centre, yy - centre) / (radius * 1.2)
    backing = np.clip(1 - d ** 6, 0, 1) * .62                 # the dark disc behind the light, fading out at its rim
    alpha = 1 - (1 - backing) * (1 - glow_alpha)
    dark = np.array([.016, .024, .043], np.float32)
    rgb = (glow + dark * (backing * (1 - glow_alpha))[..., None]) / np.maximum(alpha, 1e-4)[..., None]
    image = Image.fromarray((np.dstack([np.clip(rgb, 0, 1), alpha[..., None]]) * 255).astype(np.uint8), "RGBA")
    return image.resize((size, size), Image.LANCZOS)


def frames(state, s=1.0):
    key = (state if state in ui.CORE else "standby", round(s, 2))
    with _lock:
        cached = _frames.get(key)
    if cached is None:
        cached = [render_orb(key[0], i, s) for i in range(FRAMES)]
        with _lock:
            _frames[key] = cached
    return cached


# ---------- The speech bubble ----------

def render_bubble(text, state="speaking", s=1.0, tail="left"):
    """His words in the page's dark panel, with a small tail pointing at the orb. Long replies show their last
    lines (the reply grows as he speaks). Returns (image, margin)."""
    pad = round(12 * s)
    body, label_face = ui.font(13.5 * s), ui.font(10 * s, mono=True)
    width_limit = round(BUBBLE_WIDTH * s) - pad * 2
    if text:
        lines = ui.wrap(text, body, width_limit - body.getlength("…"))   # room for a leading ellipsis
        if len(lines) > BUBBLE_LINES:
            lines = lines[-BUBBLE_LINES:]
            lines[0] = "…" + lines[0]
        colour = ui.INK
    else:
        lines, colour = ["Thinking…" if state == "thinking" else "Listening…"], ui.MUTED
    label = "Jarvis" + {"thinking": " · thinking", "listening": " · listening"}.get(state, "")
    lh = ui.line_height(body, 1.12)
    label_width = sum(label_face.getlength(c) + 1.4 * s for c in label.upper()) + 12 * s
    inner = max(max(body.getlength(line) for line in lines), label_width, 90 * s)
    width = round(inner + pad * 2)
    height = round(pad + ui.line_height(label_face) + 4 * s + len(lines) * lh + pad * .8)
    image, margin = ui.panel(width, height, round(12 * s), glow=ui.CORE.get(state, ui.CORE["speaking"]),
                             glow_alpha=55, glow_radius=round(10 * s))
    draw = ImageDraw.Draw(image, "RGBA")
    # The tail: a small notch on the side facing the orb, level with it.
    ty, size = margin + min(height / 2, 26 * s), 7 * s
    if tail == "left":
        x = margin + 1
        draw.polygon([(x, ty - size), (x - size, ty), (x, ty + size)], fill=(*ui.PANEL, 238))
        draw.line([(x, ty - size), (x - size, ty), (x, ty + size)], fill=(*ui.LINE, 72), width=1)
    else:
        x = margin + width - 2
        draw.polygon([(x, ty - size), (x + size, ty), (x, ty + size)], fill=(*ui.PANEL, 238))
        draw.line([(x, ty - size), (x + size, ty), (x, ty + size)], fill=(*ui.LINE, 72), width=1)
    x, y = margin + pad, margin + pad - 2 * s
    dot = ui.smooth_ellipse((round(8 * s), round(8 * s)), (1, 1, 7 * s, 7 * s),
                            fill=(*ui.CORE.get(state, ui.CORE["standby"]), 255))
    image.alpha_composite(dot, (int(x), int(y + ui.line_height(label_face) / 2 - 4 * s)))
    ui.tracked(draw, (x + 12 * s, y), label, label_face, (*ui.ACCENT, 255), 1.4 * s)
    y += ui.line_height(label_face) + 4 * s
    for line in lines:
        draw.text((x, y), line, font=body, fill=(*colour, 255))
        y += lh
    return image, margin


# ---------- Following the pointer ----------

def place(pointer, work, orb, bubble=None, s=1.0):
    """Where the orb and bubble windows go for a pointer position: the orb just below-right of the pointer
    (flipped when that would leave the screen), the bubble beside the orb on whichever side has room.
    bubble is (width, height, margin) of the bubble image. Returns (orb xy, bubble xy or None, tail side)."""
    left, top, right, bottom = work
    px, py = pointer
    ox, oy = px + OFFSET[0] * s, py + OFFSET[1] * s
    if ox + orb > right:
        ox = px - OFFSET[0] * s - orb
    if oy + orb > bottom:
        oy = py - OFFSET[1] * s - orb
    ox, oy = min(max(ox, left), right - orb), min(max(oy, top), bottom - orb)
    if not bubble:
        return (round(ox), round(oy)), None, "left"
    width, height, margin = bubble
    panel_w, panel_h = width - margin * 2, height - margin * 2
    centre_y = oy + orb / 2
    by = centre_y - min(panel_h / 2, 26 * s)                     # level with the tail
    on_right = (ox + orb * .78 + 6 * s, "left")
    on_left = (ox + orb * .22 - 6 * s - panel_w, "right")
    fits_right, fits_left = on_right[0] + panel_w <= right, on_left[0] >= left
    away = on_right if px <= ox else on_left                      # the side away from the pointer, if it fits
    bx, tail = away if (fits_right if away is on_right else fits_left) else (on_right if fits_right else on_left)
    bx, by = min(max(bx, left), right - panel_w), min(max(by, top), bottom - panel_h)
    return (round(ox), round(oy)), (round(bx - margin), round(by - margin)), tail


def _fullscreen_in_front():
    """True while a full-screen app (a game, a video) covers the monitor it's on."""
    import win32api
    import win32gui
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or win32gui.GetClassName(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        rect = win32gui.GetWindowRect(hwnd)
        info = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))
        return tuple(rect) == tuple(info["Monitor"])
    except Exception:
        return False


class Companion:
    """Lives on the overlay thread (overlay_ui.HOST)."""

    def __init__(self):
        import hud
        self.events = hud.subscribe()
        self.state = hud.current_state()
        self.reply, self.reply_at, self.reply_done = "", 0.0, True
        self.orb = ui.Layer("Jarvis companion")
        self.bubble = ui.Layer("Jarvis companion bubble")
        self.position = None
        self.bubble_content = None                 # (text, state, scale) the bubble image shows
        self.bubble_text = ""
        self.bubble_tail = "left"
        self.bubble_image, self.bubble_margin = None, 0
        self.bubble_alpha = 0.0
        self.frame, self.last_frame = 0, 0.0
        self.screens, self.screens_at = ui.monitors(), time.monotonic()
        self.hidden_for_fullscreen, self.checked_fullscreen = False, 0.0
        self.orb_alpha = 0.0

    def close(self):
        import hud
        hud.unsubscribe(self.events)
        self.orb.destroy()
        self.bubble.destroy()

    def _drain(self, now):
        while True:
            try:
                event = self.events.get_nowait()
            except Exception:
                return
            kind = event.get("type")
            if kind == "state":
                self.state = event.get("state", self.state)
                if self.state in ("standby", "listening") and not self.reply_done:
                    self.reply_done, self.reply_at = True, now
            elif kind == "you":
                self.reply, self.reply_done = "", False
            elif kind == "jarvis":
                text = str(event.get("text") or "").strip()
                if text and not text.startswith("(to "):          # replies sent to the phone/Telegram stay there
                    self.reply = f"{self.reply} {text}".strip()[-1200:]
                    self.reply_at, self.reply_done = now, self.state not in ("speaking", "thinking")

    def tick(self, now):
        import win32api
        self._drain(now)
        if now - self.screens_at > 5:
            self.screens, self.screens_at = ui.monitors(), now
        if now - self.checked_fullscreen > 1:
            self.hidden_for_fullscreen, self.checked_fullscreen = _fullscreen_in_front(), now
        pointer = win32api.GetCursorPos()
        _, work, s = ui.monitor_at(*pointer, self.screens)
        state = self.state if self.state in ui.CORE else "standby"
        orb_frames = frames(state, s)
        orb_size = orb_frames[0].width

        # The bubble: his reply while he's on it and a few seconds after; "Thinking…" before the first words.
        want_text = self.reply if (self.reply and (not self.reply_done or now - self.reply_at < HOLD)) else ""
        wants_bubble = bool(want_text) or (state == "thinking" and not self.reply_done)
        target_alpha = 0.0 if self.hidden_for_fullscreen else 1.0
        self.orb_alpha += (target_alpha - self.orb_alpha) * .25
        self.bubble_alpha += ((1.0 if wants_bubble and target_alpha else 0.0) - self.bubble_alpha) * .25
        if wants_bubble and (want_text or self.state, state, round(s, 2)) != self.bubble_content:
            self.bubble_content = (want_text or self.state, state, round(s, 2))
            self.bubble_image, self.bubble_margin = render_bubble(want_text, state, s, self.bubble_tail)
            self.bubble_text = want_text
        bubble_size = None
        if self.bubble_image is not None and (wants_bubble or self.bubble_alpha > .02):
            bubble_size = (self.bubble_image.width, self.bubble_image.height, self.bubble_margin)

        orb_xy, bubble_xy, tail = place(pointer, work, orb_size, bubble_size, s)
        if self.position is None or abs(orb_xy[0] - self.position[0]) + abs(orb_xy[1] - self.position[1]) > 900:
            self.position = orb_xy                              # first frame, or jumped to the other monitor
        else:                                                   # glide after the pointer
            self.position = (self.position[0] + (orb_xy[0] - self.position[0]) * .35,
                             self.position[1] + (orb_xy[1] - self.position[1]) * .35)
        moved = (round(self.position[0]) - orb_xy[0], round(self.position[1]) - orb_xy[1])

        if now - self.last_frame >= 1 / FPS:
            self.frame, self.last_frame = (self.frame + 1) % FRAMES, now
        self.orb.push(orb_frames[self.frame], (round(self.position[0]), round(self.position[1])),
                      255 * self.orb_alpha)
        if bubble_xy:
            if tail != self.bubble_tail:                        # the bubble changed sides: point the tail at the orb
                self.bubble_tail = tail
                self.bubble_image, self.bubble_margin = render_bubble(self.bubble_text, self.bubble_content[1], s,
                                                                      tail)
            self.bubble.push(self.bubble_image, (bubble_xy[0] + moved[0], bubble_xy[1] + moved[1]),
                             255 * self.bubble_alpha)
        elif self.bubble.shown:
            self.bubble.push(alpha=0)
        return True


def _start():
    global _companion
    if _companion is None:
        _companion = Companion()
        ui.HOST.tick("companion", _companion.tick)
    return True


def _stop():
    global _companion
    ui.HOST.untick("companion")
    if _companion is not None:
        _companion.close()
        _companion = None
    return True


def active():
    return _companion is not None


def enable(on, remember=True):
    """Turn the companion on or off (and save the choice). Returns whether it is on now."""
    if on:
        frames("standby")                                   # render the first loop before it appears
        ui.HOST.call(_start, timeout=20)
    else:
        ui.HOST.call(_stop)
    if remember:
        import preferences
        preferences.update(**{PREF: bool(on)})
    try:
        import hud
        hud.emit("settings", **hud.settings())               # the app hides or brings back its corner orb
    except Exception:
        pass
    return active()


def wanted():
    import preferences
    return bool(preferences.read().get(PREF))


def restore():
    """At start-up: bring the companion back if it was on when Jarvis last ran."""
    import testing_guard
    if testing_guard.under_test() or not wanted():
        return False
    try:
        return enable(True, remember=False)
    except Exception as e:
        print(f"(cursor companion didn't start: {e!r})", flush=True)
        return False
