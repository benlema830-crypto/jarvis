"""Cursor companion: a small Jarvis orb that rides along beside the mouse pointer, with his replies in a speech
bubble next to it.

"Follow my cursor" turns it on and "go back to normal" turns it off (the cursor_companion tool); the choice is
saved, so it comes back after a restart. While it's on, the desktop app tucks its corner orb away (it reads
`cursor_companion` from /settings).

The orb is a miniature of the page's violet holographic core (hud/holo.js): a glowing sphere with two orbit rings
and a travelling spark, coloured by his state (standby, listening, thinking, speaking) and breathing faster as he
talks. The bubble is the page's dark panel with its teal mono label. Both are overlay_ui layers: on top, never
focused, and the mouse passes through them, so they can't take a click. They step aside while a full-screen app
(a game, a video) is in front.
"""
import math
import threading
import time

import numpy as np
from PIL import Image, ImageDraw

import overlay_ui as ui

ORB = 76                       # the orb's window, in pixels at 100% scaling (the sphere itself is ~40)
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

def render_orb(state="standby", frame=0, s=1.0):
    """One frame of the little holographic core, RGBA, ORB*s pixels square."""
    colour = np.array(ui.CORE.get(state, ui.CORE["standby"]), dtype=np.float32) / 255
    white = np.array(ui.CORE_WHITE, dtype=np.float32) / 255
    size = round(ORB * s)
    k = 3                                                   # drawn 3x and scaled down, for smooth edges
    n = size * k
    phase = frame / FRAMES * math.tau
    breathe = {"speaking": .10 * (0.5 + 0.5 * math.sin(phase * 4)), "listening": .05 + .03 * math.sin(phase * 2),
               "thinking": .04 * math.sin(phase * 3)}.get(state, .035 * math.sin(phase))
    radius = n * .25 * (1 + breathe)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    cx = cy = (n - 1) / 2
    d = np.hypot(xx - cx, yy - cy) / radius                 # 1 at the sphere's edge

    # Halo: soft light around the sphere, stronger as he speaks.
    halo = np.exp(-np.maximum(d - .55, 0) ** 2 / .32) * (.42 + breathe * 2.2)
    rgb = np.zeros((n, n, 3), np.float32) + colour
    alpha = np.clip(halo, 0, 1) * (d > .2)
    # Sphere body: dark glass with a bright rim (fresnel) and a hot core.
    inside = d < 1
    rim = np.clip(d, 0, 1) ** 3
    core = np.exp(-(d / (.42 + breathe)) ** 2)
    body = (np.array([.04, .035, .09], np.float32) * (1 - rim[..., None]) + colour * rim[..., None] * .95)
    body = body * (1 - core[..., None]) + (white * .9 + colour * .1) * core[..., None]
    shine = np.exp(-(((xx - cx + radius * .38) / (radius * .28)) ** 2 + ((yy - cy + radius * .42) / (radius * .2)) ** 2))
    body = np.clip(body + shine[..., None] * .35, 0, 1)
    edge = np.clip((1 - d) * radius / k, 0, 1)              # one-pixel soft edge
    rgb = np.where(inside[..., None], body * edge[..., None] + rgb * (1 - edge[..., None]), rgb)
    alpha = np.where(inside, edge * .97 + alpha * (1 - edge), alpha)
    sphere = Image.fromarray(np.dstack([rgb, alpha[..., None]]).__mul__(255).astype(np.uint8), "RGBA")

    # Two orbit rings tilted across the sphere; the half behind it is drawn first and dimmer.
    spin = phase * (2 if state == "thinking" else 1)
    back = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    front = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw_back, draw_front = ImageDraw.Draw(back, "RGBA"), ImageDraw.Draw(front, "RGBA")
    ring_colour = tuple(int(v * 255) for v in colour)
    spark = tuple(ui.CORE_SPARK)
    for reach, tilt, turn, speed in ((1.5, .32, -.35, 1), (1.32, .55, .9, -1)):
        points = []
        for i in range(73):
            u = i / 72 * math.tau + spin * speed
            x, y, z = math.cos(u) * reach, math.sin(u) * reach * tilt, math.sin(u)
            rx = x * math.cos(turn) - y * math.sin(turn)
            ry = x * math.sin(turn) + y * math.cos(turn)
            points.append((cx + rx * radius, cy + ry * radius, z))
        for (x1, y1, z1), (x2, y2, z2) in zip(points, points[1:]):
            behind = z1 + z2 < 0
            (draw_back if behind else draw_front).line(
                (x1, y1, x2, y2), fill=(*ring_colour, 70 if behind else 200), width=max(1, round(1.3 * k * s)))
        x, y, z = points[0]                                  # the spark rides the ring
        if z >= 0:
            r = 2.2 * k * s
            draw_front.ellipse((x - r * 2.2, y - r * 2.2, x + r * 2.2, y + r * 2.2), fill=(*ring_colour, 60))
            draw_front.ellipse((x - r, y - r, x + r, y + r), fill=(*spark, 255))
    image = Image.alpha_composite(Image.alpha_composite(back, sphere), front)
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
