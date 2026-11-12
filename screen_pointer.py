"""Pointing: Jarvis shows the owner where something is on their screen, without touching it.

"Where do I click to change the resolution?" He looks at the screen (look_at_screen), then draws a ring with a
short label over the control for a few seconds. The ring is a small always-on-top window that the mouse passes
straight through, so it can't take a click or the keyboard, and it goes away by itself. A new pointer replaces
the last one.

Coordinates arrive in the pixels of the screenshot Jarvis was shown; `remember_look` keeps how that picture
maps onto the real desktop, and `to_native` turns one into the other.
"""
import threading
import time

SECONDS = 8
MAX_SECONDS = 30
LOOK_FRESH_SECONDS = 180
RING, WIDTH, HEIGHT = 26, 380, 190       # ring radius and the size of the little window, in pixels
KEY = 0x00010101                         # the colour made see-through (never drawn otherwise)
ACCENT, INK, PLATE = 0x00D4EA5E, 0x00FFFFFF, 0x00140E06   # BGR: teal ring, white text, dark label plate
CLASS = "JarvisScreenPointer"

_lock = threading.Lock()
_look = None        # {"size": (w, h), "box": (left, top, right, bottom), "at": time}
_current = None     # {"hwnd", "until"}
_registered = False


def remember_look(size, box):
    """Called when Jarvis is shown a screenshot: the picture's size and the desktop rectangle it covers."""
    global _look
    with _lock:
        _look = {"size": tuple(size), "box": tuple(box), "at": time.time()}


def to_native(x, y, now=None):
    """A point in the last screenshot -> the same point on the real desktop. Raises ValueError when there is no
    recent screenshot to measure against, or the point is outside it."""
    with _lock:
        look = _look
    if not look or (now or time.time()) - look["at"] > LOOK_FRESH_SECONDS:
        raise ValueError("Look at the screen first (look_at_screen), then point at what you saw.")
    width, height = look["size"]
    if not (0 <= x <= width and 0 <= y <= height):
        raise ValueError(f"That point is outside the screenshot, which is {width} by {height}.")
    left, top, right, bottom = look["box"]
    return (round(left + x * (right - left) / width), round(top + y * (bottom - top) / height))


def _window_proc(hwnd, message, wparam, lparam):
    import win32con
    import win32gui
    state = _states.get(hwnd)
    if message == win32con.WM_PAINT and state:
        dc, paint = win32gui.BeginPaint(hwnd)
        try:
            _draw(dc, state)
        finally:
            win32gui.EndPaint(hwnd, paint)
        return 0
    if message == win32con.WM_TIMER and state:
        if time.time() >= state["until"]:
            win32gui.DestroyWindow(hwnd)
        else:
            state["phase"] = (state["phase"] + 1) % 16
            win32gui.InvalidateRect(hwnd, None, True)
        return 0
    if message == win32con.WM_DESTROY:
        _states.pop(hwnd, None)
        win32gui.PostQuitMessage(0)
        return 0
    return win32gui.DefWindowProc(hwnd, message, wparam, lparam)


_states = {}


def _draw(dc, state):
    import win32con
    import win32gui
    import win32ui
    cx, cy = state["ring"]
    pulse = abs(8 - state["phase"])            # 0..8..0: the outer ring breathes so the eye finds it
    background = win32gui.CreateSolidBrush(KEY)
    win32gui.FillRect(dc, (0, 0, WIDTH, HEIGHT), background)
    win32gui.DeleteObject(background)
    hollow = win32gui.GetStockObject(win32con.NULL_BRUSH)
    for radius, thickness, colour in ((RING + 6 + pulse, 3, INK), (RING, 5, ACCENT), (4, 4, ACCENT)):
        pen = win32gui.CreatePen(win32con.PS_SOLID, thickness, colour)
        old_pen, old_brush = win32gui.SelectObject(dc, pen), win32gui.SelectObject(dc, hollow)
        win32gui.Ellipse(dc, cx - radius, cy - radius, cx + radius, cy + radius)
        win32gui.SelectObject(dc, old_pen)
        win32gui.SelectObject(dc, old_brush)
        win32gui.DeleteObject(pen)
    if state["label"]:
        left, top, right, bottom = state["plate"]
        plate = win32gui.CreateSolidBrush(PLATE)
        pen = win32gui.CreatePen(win32con.PS_SOLID, 2, ACCENT)
        old_pen, old_brush = win32gui.SelectObject(dc, pen), win32gui.SelectObject(dc, plate)
        win32gui.RoundRect(dc, left, top, right, bottom, 12, 12)
        win32gui.SelectObject(dc, old_pen)
        win32gui.SelectObject(dc, old_brush)
        win32gui.DeleteObject(pen)
        win32gui.DeleteObject(plate)
        font = win32ui.CreateFont({"name": "Segoe UI", "height": 20, "weight": 600})
        old_font = win32gui.SelectObject(dc, font.GetSafeHandle())
        win32gui.SetBkMode(dc, win32con.TRANSPARENT)
        win32gui.SetTextColor(dc, INK)
        win32gui.DrawText(dc, state["label"], -1, (left + 8, top + 5, right - 8, bottom - 5),
                          win32con.DT_CENTER | win32con.DT_WORDBREAK | win32con.DT_NOPREFIX)
        win32gui.SelectObject(dc, old_font)


def layout(x, y, label, bounds):
    """Where the little window goes and where the ring and label sit inside it, keeping all of it on the desktop:
    (window left, window top, ring centre in the window, label plate or None)."""
    left, top, right, bottom = bounds
    below = y + HEIGHT - RING - 14 <= bottom             # room for the label under the ring?
    win_left = min(max(x - WIDTH // 2, left), right - WIDTH)
    win_top = y - RING - 16 if below else y - HEIGHT + RING + 16
    win_top = min(max(win_top, top), bottom - HEIGHT)
    ring = (x - win_left, y - win_top)
    if not label:
        return win_left, win_top, ring, None
    lines = 1 + len(label) // 34
    plate_height = 12 + 24 * min(lines, 3)
    plate_top = ring[1] + RING + 22 if below else ring[1] - RING - 22 - plate_height
    plate_top = min(max(plate_top, 2), HEIGHT - plate_height - 2)
    return win_left, win_top, ring, (10, plate_top, WIDTH - 10, plate_top + plate_height)


def _run(x, y, label, seconds, bounds, ready):
    global _registered
    import win32api
    import win32con
    import win32gui
    try:
        instance = win32api.GetModuleHandle(None)
        if not _registered:
            window_class = win32gui.WNDCLASS()
            window_class.lpfnWndProc, window_class.lpszClassName, window_class.hInstance = _window_proc, CLASS, instance
            window_class.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
            win32gui.RegisterClass(window_class)
            _registered = True
        win_left, win_top, ring, plate = layout(x, y, label, bounds)
        style = (win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST
                 | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE)
        hwnd = win32gui.CreateWindowEx(style, CLASS, "Jarvis pointer", win32con.WS_POPUP, win_left, win_top, WIDTH, HEIGHT,
                                       0, 0, instance, None)
        _states[hwnd] = {"ring": ring, "plate": plate, "label": label, "until": time.time() + seconds, "phase": 0}
        win32gui.SetLayeredWindowAttributes(hwnd, KEY, 0, win32con.LWA_COLORKEY)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
        import ctypes
        ctypes.windll.user32.SetTimer(hwnd, 1, 70, None)   # WM_TIMER drives the pulse and the expiry
        with _lock:
            global _current
            _current = {"hwnd": hwnd, "until": time.time() + seconds}
        ready.set()
        win32gui.PumpMessages()
    except Exception as e:
        print(f"(screen pointer: {e!r})", flush=True)
        ready.set()


def hide():
    """Take the pointer off the screen now."""
    global _current
    with _lock:
        current, _current = _current, None
    if current:
        try:
            import win32con
            import win32gui
            win32gui.PostMessage(current["hwnd"], win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass


def show(x, y, label="", seconds=SECONDS, bounds=None):
    """Draw the pointer at a point on the real desktop. Returns once it is on screen (or has failed)."""
    if bounds is None:
        import desktop
        bounds = desktop.current_layout().bounds
    left, top, right, bottom = bounds
    if not (left <= x < right and top <= y < bottom):
        raise ValueError("That point isn't on any screen.")
    label = " ".join(str(label or "").split())[:100]
    seconds = min(max(float(seconds or SECONDS), 2), MAX_SECONDS)
    hide()
    ready = threading.Event()
    threading.Thread(target=_run, args=(int(x), int(y), label, seconds, bounds, ready), daemon=True,
                     name="screen-pointer").start()
    ready.wait(3)
    with _lock:
        return _current is not None
