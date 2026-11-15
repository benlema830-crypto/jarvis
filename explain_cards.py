"""Visual explanations: Jarvis lays a few short cards over the screen while he talks something through.

"Visually explain this page." He looks at the screen, then shows a small stack of cards (key facts, a timeline,
steps, a flow diagram, a short summary) beside the part of the screen he's explaining, with glowing corner
brackets around that part. They are drawn in the Jarvis page's own style (overlay_ui), sit on top of everything,
never take the focus, and the mouse passes through them, so work carries on underneath. They go away by
themselves, from the small close button on the title card (which also doesn't take the focus), or when he is
asked to clear them. A new explanation replaces the last.
"""
import threading
import time

from PIL import Image, ImageDraw, ImageFilter

import overlay_ui as ui

SECONDS, MIN_SECONDS, MAX_SECONDS = 60, 10, 300
MAX_CARDS, MAX_ITEMS, MAX_ITEM_CHARS = 4, 6, 160
KINDS = {"facts": "KEY FACTS", "timeline": "TIMELINE", "steps": "STEPS", "flow": "HOW IT FITS", "summary": "IN SHORT"}
ALIASES = {"fact": "facts", "key facts": "facts", "list": "facts", "bullets": "facts", "points": "facts",
           "diagram": "flow", "process": "flow", "chain": "flow", "step": "steps", "how to": "steps",
           "history": "timeline", "dates": "timeline", "note": "summary", "text": "summary", "overview": "summary"}
CARD_WIDTH, GAP, PAD = 340, 14, 16

_lock = threading.Lock()
_current = None      # the explanation on screen: {"layers", "until", ...}


def _clean(text, limit):
    return " ".join(str(text or "").split())[:limit]


def normalize(cards, title=""):
    """What the model sent -> (title, [{"kind", "title", "items"}]) with everything trimmed to fit on screen."""
    if isinstance(cards, dict):
        cards = [cards]
    if not isinstance(cards, list):
        raise ValueError("cards must be a list of cards.")
    tidy = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        kind = _clean(card.get("kind") or card.get("type") or "facts", 30).lower()
        kind = kind if kind in KINDS else ALIASES.get(kind, "facts")
        items = card.get("items") or card.get("points") or []
        if isinstance(items, str):
            items = [items]
        if kind == "summary" and not items and card.get("text"):
            items = [card["text"]]
        items = [_clean(item, MAX_ITEM_CHARS) for item in items if _clean(item, MAX_ITEM_CHARS)][:MAX_ITEMS]
        if items:
            tidy.append({"kind": kind, "title": _clean(card.get("title"), 48), "items": items})
        if len(tidy) == MAX_CARDS:
            break
    if not tidy:
        raise ValueError("Give at least one card with items, e.g. {\"kind\": \"facts\", \"title\": \"Key facts\", "
                         "\"items\": [\"...\"]}.")
    return _clean(title, 70), tidy


def split_label(item, limit=26):
    """'1998 - Founded in Menlo Park' -> ('1998', 'Founded in Menlo Park'); no short label -> ('', item)."""
    for mark in (" — ", " – ", " - ", ": "):
        head, found, tail = item.partition(mark)
        if found and head.strip() and tail.strip() and len(head) <= limit:
            return head.strip(), tail.strip()
    return "", item


# ---------- Drawing ----------

def _text(draw, xy, text, face, colour, alpha=255):
    draw.text(xy, text, font=face, fill=(*colour, alpha))


def _dot(image, centre, radius, colour, glow=True):
    """A small glowing status light, like the page's."""
    x, y = centre
    size = int(radius * 6)
    light = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if glow:
        halo = Image.new("L", (size, size), 0)
        ImageDraw.Draw(halo).ellipse((size / 2 - radius * 1.6, size / 2 - radius * 1.6, size / 2 + radius * 1.6,
                                      size / 2 + radius * 1.6), fill=120)
        halo = halo.filter(ImageFilter.GaussianBlur(radius))
        light = Image.merge("RGBA", (*(Image.new("L", (size, size), c) for c in colour), halo))
    core = ui.smooth_ellipse((size, size), (size / 2 - radius, size / 2 - radius, size / 2 + radius,
                                            size / 2 + radius), fill=(*colour, 255))
    light = Image.alpha_composite(light, core)
    image.alpha_composite(light, (int(x - size / 2), int(y - size / 2)))


def _card_body(card, inner, s):
    """Measure a card's body and return (height, draw(image, left, top))."""
    body, small = ui.font(14 * s), ui.font(13 * s)
    mono, semibold = ui.font(12 * s, mono=True), ui.font(14 * s, "semibold")
    lh, gap = ui.line_height(body), round(8 * s)
    kind, items = card["kind"], card["items"]
    rows = []      # (height, painter(image, draw, x, y))

    if kind == "facts":
        for item in items:
            key, value = split_label(item)
            if key:
                key_width = round(inner * .38)
                keys = ui.wrap(key, small, key_width - 8 * s, 2)
                values = ui.wrap(value, body, inner - key_width, 4)
                height = max(len(keys) * ui.line_height(small), len(values) * lh)

                def paint(image, draw, x, y, keys=keys, values=values, key_width=key_width):
                    for i, line in enumerate(keys):
                        _text(draw, (x, y + i * ui.line_height(small) + s), line, small, ui.MUTED)
                    for i, line in enumerate(values):
                        _text(draw, (x + key_width, y + i * lh), line, body, ui.INK)
            else:
                lines = ui.wrap(item, body, inner - 16 * s, 4)
                height = len(lines) * lh

                def paint(image, draw, x, y, lines=lines):
                    _dot(image, (x + 4 * s, y + lh / 2), 2.6 * s, ui.ACCENT)
                    for i, line in enumerate(lines):
                        _text(draw, (x + 16 * s, y + i * lh), line, body, ui.INK)
            rows.append((height, paint))

    elif kind == "timeline":
        for item in items:
            when, what = split_label(item)
            lines = ui.wrap(what, body, inner - 24 * s, 3)
            height = (ui.line_height(mono) if when else 0) + len(lines) * lh

            def paint(image, draw, x, y, when=when, lines=lines):
                _dot(image, (x + 5 * s, y + 8 * s), 4 * s, ui.ACCENT)
                top = y
                if when:
                    _text(draw, (x + 24 * s, top), when.upper(), mono, ui.ACCENT)
                    top += ui.line_height(mono)
                for i, line in enumerate(lines):
                    _text(draw, (x + 24 * s, top + i * lh), line, body, ui.INK)
            rows.append((height, paint))

    elif kind == "steps":
        for number, item in enumerate(items, 1):
            lines = ui.wrap(item, body, inner - 34 * s, 4)
            height = max(len(lines) * lh, round(24 * s))

            def paint(image, draw, x, y, number=number, lines=lines):
                d = round(22 * s)
                ring = ui.smooth_ellipse((d + 2, d + 2), (1, 1, d, d), fill=(*ui.RAISE, 255),
                                         outline=(*ui.ACCENT, 200), width=max(1, round(1.4 * s)))
                image.alpha_composite(ring, (int(x), int(y)))
                label = str(number)
                _text(draw, (x + 1 + (d - mono.getlength(label)) / 2, y + (d - mono.size) / 2), label, mono,
                      ui.ACCENT)
                for i, line in enumerate(lines):
                    _text(draw, (x + 34 * s, y + i * lh + 1 * s), line, body, ui.INK)
            rows.append((height, paint))

    elif kind == "flow":
        node_pad, arrow = round(8 * s), round(18 * s)
        for index, item in enumerate(items):
            lines = ui.wrap(item, semibold if index == 0 else body, inner - node_pad * 2 - 4 * s, 3)
            node = len(lines) * lh + node_pad * 2
            height = node + (arrow if index < len(items) - 1 else 0)

            def paint(image, draw, x, y, lines=lines, node=node, index=index):
                box, _ = ui.panel(inner, node, round(8 * s), fill=ui.RAISE, fill_alpha=255,
                                  border=ui.ACCENT if index == 0 else ui.LINE, border_alpha=150 if index == 0 else 80,
                                  glow_alpha=0, margin=0)
                image.alpha_composite(box, (int(x), int(y)))
                face = semibold if index == 0 else body
                for i, line in enumerate(lines):
                    _text(draw, (x + (inner - face.getlength(line)) / 2, y + node_pad + i * lh), line, face, ui.INK)
                if index < len(items) - 1:
                    cx, top = x + inner / 2, y + node + 3 * s
                    draw.line((cx, top, cx, top + arrow - 7 * s), fill=(*ui.ACCENT, 190), width=max(1, round(1.5 * s)))
                    draw.line((cx - 5 * s, top + arrow - 11 * s, cx, top + arrow - 6 * s, cx + 5 * s,
                               top + arrow - 11 * s), fill=(*ui.ACCENT, 220), width=max(1, round(1.5 * s)))
            rows.append((height, paint))
        gap = 0

    else:  # summary
        lines = ui.wrap(" ".join(items), body, inner, 9)
        rows.append((len(lines) * lh, lambda image, draw, x, y: [
            _text(draw, (x, y + i * lh), line, body, ui.INK) for i, line in enumerate(lines)]))

    height = sum(h for h, _ in rows) + gap * (len(rows) - 1)

    def draw_rows(image, left, top):
        draw = ImageDraw.Draw(image, "RGBA")
        if kind == "timeline" and len(rows) > 1:            # the rail first, so the dots sit on it
            last = top + sum(h for h, _ in rows[:-1]) + gap * (len(rows) - 1)
            draw.line((left + 5 * s, top + 8 * s, left + 5 * s, last + 8 * s), fill=(*ui.ACCENT, 80),
                      width=max(1, round(1.5 * s)))
        y = top
        for index, (row_height, paint) in enumerate(rows):
            paint(image, draw, left, y)
            y += row_height + gap
            if kind == "facts" and index < len(rows) - 1:   # hairlines between facts, like the page's lists
                draw.line((left, y - gap / 2, left + inner, y - gap / 2), fill=(*ui.LINE, 26), width=1)
    return height, draw_rows


def render_card(card, s=1.0, width=CARD_WIDTH):
    """One card -> (image, margin): the panel starts at (margin, margin) in the image."""
    width, pad = round(width * s), round(PAD * s)
    inner = width - pad * 2
    label_face, title_face = ui.font(11 * s, mono=True), ui.font(16 * s, "semibold")
    title_lines = ui.wrap(card["title"], title_face, inner, 2) if card["title"] else []
    head = ui.line_height(label_face) + round(6 * s) + len(title_lines) * ui.line_height(title_face, 1.0)
    body_height, draw_body = _card_body(card, inner, s)
    height = pad + head + round(12 * s) + body_height + pad
    image, margin = ui.panel(width, height, round(14 * s), glow_radius=round(12 * s))
    draw = ImageDraw.Draw(image, "RGBA")
    x, y = margin + pad, margin + pad
    ui.tracked(draw, (x, y), KINDS[card["kind"]], label_face, (*ui.ACCENT, 255), 1.6 * s)
    y += ui.line_height(label_face) + round(6 * s)
    for line in title_lines:
        _text(draw, (x, y), line, title_face, ui.INK)
        y += ui.line_height(title_face, 1.0)
    y += round(4 * s)
    draw.line((x, y, x + inner, y), fill=(*ui.LINE, 46), width=1)
    y += round(8 * s)
    draw_body(image, x, y)
    return image, margin


def render_header(title, s=1.0, width=CARD_WIDTH, close_room=True):
    width, pad = round(width * s), round(PAD * s)
    label_face, title_face = ui.font(11 * s, mono=True), ui.font(18 * s, "semibold")
    inner = width - pad * 2 - (round(30 * s) if close_room else 0)
    lines = ui.wrap(title or "Here's the gist", title_face, inner, 2)
    height = pad + ui.line_height(label_face) + round(6 * s) + len(lines) * ui.line_height(title_face, 1.0) + pad
    image, margin = ui.panel(width, height, round(14 * s), glow_alpha=70, glow_radius=round(14 * s),
                             border=ui.ACCENT, border_alpha=90)
    draw = ImageDraw.Draw(image, "RGBA")
    x, y = margin + pad, margin + pad
    _dot(image, (x + 3 * s, y + ui.line_height(label_face) / 2 - 1), 3 * s, ui.ACCENT)
    ui.tracked(draw, (x + 14 * s, y), "Jarvis · visual brief", label_face, (*ui.ACCENT, 255), 1.6 * s)
    y += ui.line_height(label_face) + round(6 * s)
    for line in lines:
        _text(draw, (x, y), line, title_face, ui.INK)
        y += ui.line_height(title_face, 1.0)
    return image, margin


def render_close(s=1.0):
    d = round(26 * s)
    image = ui.smooth_ellipse((d + 4, d + 4), (2, 2, d + 1, d + 1), fill=(*ui.RAISE, 250),
                              outline=(*ui.LINE, 120), width=1)
    draw = ImageDraw.Draw(image, "RGBA")
    c, r, w = (d + 4) / 2, d * .2, max(1, round(1.6 * s))
    draw.line((c - r, c - r, c + r, c + r), fill=(*ui.INK, 230), width=w)
    draw.line((c - r, c + r, c + r, c - r), fill=(*ui.INK, 230), width=w)
    return image


def render_brackets(width, height, s=1.0):
    """Glowing HUD corner brackets around the area being explained (the window is `width` x `height`)."""
    pad, arm, thick = round(10 * s), round(28 * s), max(2, round(2 * s))
    marks = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(marks)
    l, t, r, b = pad, pad, width - pad - 1, height - pad - 1
    for x, y, dx, dy in ((l, t, 1, 1), (r, t, -1, 1), (l, b, 1, -1), (r, b, -1, -1)):
        draw.line((x, y, x + dx * arm, y), fill=(*ui.ACCENT, 235), width=thick)
        draw.line((x, y, x, y + dy * arm), fill=(*ui.ACCENT, 235), width=thick)
    glow = marks.filter(ImageFilter.GaussianBlur(round(5 * s)))
    return Image.alpha_composite(Image.alpha_composite(glow, glow), marks)


# ---------- Where the cards go ----------

def place(sizes, work, region=None, gap=GAP):
    """Panel sizes [(w, h)] -> top-left of each panel on the monitor's work area, stacked in one column (two
    when one doesn't fit). Beside the region when there's room on its right, else its left, else over its right
    edge; with no region, down the right-hand side of the screen."""
    left, top, right, bottom = work
    room = bottom - top - gap * 2
    columns, column, used = [], [], 0
    for index, (_, height) in enumerate(sizes):
        if column and used + gap + height > room:
            columns.append(column)
            column, used = [], 0
        used += (gap if column else 0) + height
        column.append(index)
    columns.append(column)
    width = max(w for w, _ in sizes)
    stack_width = len(columns) * width + (len(columns) - 1) * gap
    tallest = max(sum(sizes[i][1] for i in col) + gap * (len(col) - 1) for col in columns)
    if region:
        r_left, r_top, r_right, _ = region
        if right - r_right >= stack_width + gap * 2:
            x0 = r_right + gap
        elif r_left - left >= stack_width + gap * 2:
            x0 = r_left - gap - stack_width
        else:
            x0 = min(r_right, right) - gap - stack_width
        y0 = r_top
    else:
        x0, y0 = right - gap * 2 - stack_width, top + gap * 3
    x0 = min(max(x0, left + gap), right - gap - stack_width)
    y0 = min(max(y0, top + gap), bottom - gap - tallest)
    positions = [None] * len(sizes)
    for c, col in enumerate(columns):
        y = y0
        for index in col:
            positions[index] = (x0 + c * (width + gap), y)
            y += sizes[index][1] + gap
    return positions


def _foreground_point():
    import win32gui
    try:
        l, t, r, b = win32gui.GetWindowRect(win32gui.GetForegroundWindow())
        return (l + r) // 2, (t + b) // 2
    except Exception:
        return 0, 0


# ---------- On screen ----------

def show(title, cards, region=None, seconds=SECONDS):
    """Put the cards on screen. region: (left, top, right, bottom) on the real desktop, or None.
    Returns a short description of what was shown."""
    title, cards = normalize(cards, title)
    seconds = min(max(float(seconds or SECONDS), MIN_SECONDS), MAX_SECONDS)
    screens = ui.monitors()
    anchor = ((region[0] + region[2]) // 2, (region[1] + region[3]) // 2) if region else _foreground_point()
    monitor, work, s = ui.monitor_at(*anchor, screens)
    if region:   # keep the brackets on the monitor the area is on
        region = (max(region[0], monitor[0]), max(region[1], monitor[1]), min(region[2], monitor[2]),
                  min(region[3], monitor[3]))
        if region[2] - region[0] < 20 or region[3] - region[1] < 20:
            region = None
    pieces = [render_header(title, s)] + [render_card(card, s) for card in cards]
    sizes = [(img.width - 2 * m, img.height - 2 * m) for img, m in pieces]
    spots = place(sizes, work, region, round(GAP * s))
    close = render_close(s)
    plan = {"pieces": [(img, (x - m, y - m)) for (img, m), (x, y) in zip(pieces, spots)], "close": close,
            "close_at": (spots[0][0] + sizes[0][0] - round(PAD * s) - close.width + round(6 * s),
                         spots[0][1] + round(PAD * s) - round(4 * s)),
            "scale": s, "seconds": seconds}
    if region:
        pad = round(10 * s)
        box = (region[0] - pad, region[1] - pad, region[2] + pad, region[3] + pad)
        box = (max(box[0], monitor[0]), max(box[1], monitor[1]), min(box[2], monitor[2]), min(box[3], monitor[3]))
        plan["brackets"] = (render_brackets(box[2] - box[0], box[3] - box[1], s), (box[0], box[1]))
    ui.HOST.call(_mount, plan)
    where = "beside the area it explains" if region else "down the side of the screen"
    return {"cards": len(cards), "titles": [c["title"] or KINDS[c["kind"]].title() for c in cards],
            "seconds": int(seconds), "where": where, "monitor": monitor, "positions": spots}


def _mount(plan):
    """On the overlay thread: replace whatever is up with the new explanation and start its animation."""
    global _current
    _destroy(_current)
    began = time.monotonic()
    state = {"began": began, "until": began + plan["seconds"], "closing": None, "scale": plan["scale"],
             "layers": [], "done_entering": False}
    if "brackets" in plan:
        image, spot = plan["brackets"]
        state["layers"].append({"layer": ui.Layer("Jarvis explanation focus"), "image": image, "spot": spot,
                                "delay": 0.0, "rise": 0})
    for index, (image, spot) in enumerate(plan["pieces"]):
        state["layers"].append({"layer": ui.Layer("Jarvis explanation"), "image": image, "spot": spot,
                                "delay": 0.06 + 0.11 * index, "rise": round(14 * plan["scale"])})
    state["layers"].append({"layer": ui.Layer("Close Jarvis's explanation", on_click=lambda: hide()),
                            "image": plan["close"], "spot": plan["close_at"], "delay": 0.2, "rise": 0})
    for entry in state["layers"]:
        entry["layer"].push(entry["image"], (entry["spot"][0], entry["spot"][1] + entry["rise"]), 0)
    with _lock:
        _current = state
    ui.HOST.tick("explain", lambda now: _animate(state, now))


ENTER, LEAVE = 0.34, 0.28


def _animate(state, now):
    if state is not _current:
        return False
    if state["closing"] is None and now >= state["until"]:
        state["closing"] = now
    if state["closing"] is not None:
        fade = 1 - ui.ease_out((now - state["closing"]) / LEAVE)
        for entry in state["layers"]:
            entry["layer"].push(alpha=255 * fade)
        if fade <= 0:
            _destroy(state)
            return False
        return True
    if state["done_entering"]:
        return True
    finished = True
    for entry in state["layers"]:
        progress = (now - state["began"] - entry["delay"]) / ENTER
        if progress >= 1 and entry.get("settled"):
            continue
        finished = finished and progress >= 1
        eased = ui.ease_out(progress)
        x, y = entry["spot"]
        entry["layer"].push(position=(x, y + entry["rise"] * (1 - eased)), alpha=255 * eased)
        entry["settled"] = progress >= 1
    state["done_entering"] = finished
    return True


def _destroy(state):
    global _current
    if not state:
        return
    for entry in state["layers"]:
        entry["layer"].destroy()
    state["layers"] = []
    with _lock:
        if _current is state:
            _current = None


def _close():
    state = _current
    if state and state["closing"] is None:
        state["closing"] = time.monotonic()
        return True
    return False


def hide():
    """Fade the explanation away now. True if there was one on screen."""
    if _current is None:
        return False
    return bool(ui.HOST.call(_close))


def showing():
    return _current is not None
