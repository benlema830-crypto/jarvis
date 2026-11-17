"""See-through windows that Jarvis draws over the desktop: his explanation cards and the cursor companion.

Each overlay is a borderless "layered" window filled from a PIL image with real per-pixel transparency, so soft
glows and rounded panels sit on top of whatever is underneath. They are always on top, never take the keyboard
focus, have no taskbar button, and (unless made clickable, like the cards' close button) the mouse passes straight
through them. All of them live on one background thread that pumps their messages and runs their animations.

The look is the Jarvis page's own: the dark panels, teal accent, hairline borders and mono labels of hud/brain.css,
and the cyan hologram shell of hud/shell-orb.js for the orb.
"""
import ctypes
import ctypes.wintypes as wt
import functools
import queue
import threading
import time

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import desktop  # noqa: F401 - makes this process work in physical pixels on every monitor, before any window

# ---------- Palette and type, from hud/brain.css and hud/holo.js ----------

PANEL = (10, 17, 21)            # --panel-solid
RAISE = (16, 26, 31)            # --raise
INK = (223, 233, 230)           # --ink
MUTED = (155, 175, 173)         # --muted
FAINT = (130, 152, 149)         # --faint
ACCENT = (94, 234, 212)         # --accent (teal)
LINE = (130, 220, 200)          # --line-strong is this at 28%
AMBER = (245, 184, 61)          # --amber
CORE = {"standby": (94, 234, 212), "listening": (34, 211, 238), "speaking": (125, 211, 252),
        "thinking": (245, 184, 61), "offline": (100, 116, 139)}     # holo.js THEMES.cyan.states, the orb's starting colours
CORE_SPARK = (167, 243, 228)    # noteSpark
CORE_WHITE = (240, 255, 252)    # the orb's sparks


@functools.lru_cache(maxsize=64)
def font(size, weight="regular", mono=False):
    """Segoe UI Variable (the page's --sans) or Consolas (its --mono fallback), at a pixel size."""
    size = max(6, round(size))
    try:
        if mono:
            return ImageFont.truetype("consolab.ttf" if weight != "regular" else "consola.ttf", size)
        face = ImageFont.truetype("SegUIVar.ttf", size)
        face.set_variation_by_name({"regular": "Regular", "semibold": "Semibold Text",
                                    "bold": "Bold Text"}.get(weight, "Regular"))
        return face
    except (OSError, ValueError):
        try:
            return ImageFont.truetype({"regular": "segoeui.ttf", "semibold": "seguisb.ttf",
                                       "bold": "segoeuib.ttf"}.get(weight, "segoeui.ttf"), size)
        except OSError:
            return ImageFont.load_default()


def wrap(text, face, width, max_lines=None):
    """Words -> lines that fit `width` pixels. Over max_lines, the last kept line ends with an ellipsis."""
    words = []
    for word in str(text).split():
        while face.getlength(word) > width and len(word) > 1:   # a very long word (a link, a path): break it
            cut = len(word) - 1
            while cut > 1 and face.getlength(word[:cut] + "-") > width:
                cut -= 1
            words.append(word[:cut] + "-")
            word = word[cut:]
        words.append(word)
    lines, line = [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if face.getlength(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and face.getlength(last + "…") > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def line_height(face, spacing=1.18):
    ascent, descent = face.getmetrics()
    return round((ascent + descent) * spacing)


def tracked(draw, xy, text, face, fill, tracking=1.5):
    """Letter-spaced uppercase, like the page's small mono headings. Returns the width drawn."""
    x, y = xy
    for char in str(text).upper():
        draw.text((x, y), char, font=face, fill=fill)
        x += face.getlength(char) + tracking
    return x - xy[0]


def panel(width, height, radius, fill=PANEL, fill_alpha=248, border=LINE, border_alpha=72, glow=ACCENT,
          glow_alpha=46, glow_radius=14, margin=None):
    """A rounded dark panel with a hairline border and a soft accent glow around it, anti-aliased.
    Returns (image, margin): the panel's top-left sits at (margin, margin) in the image."""
    margin = glow_radius * 2 if margin is None else margin
    scale = 3
    W, H = width + margin * 2, height + margin * 2
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if glow_alpha:
        halo = Image.new("L", (W, H), 0)
        ImageDraw.Draw(halo).rounded_rectangle((margin, margin, margin + width, margin + height), radius,
                                               fill=glow_alpha)
        halo = halo.filter(ImageFilter.GaussianBlur(glow_radius))
        image = Image.merge("RGBA", (*(Image.new("L", (W, H), c) for c in glow), halo))
    big = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle((0, 0, width * scale - 1, height * scale - 1), radius * scale,
                           fill=(*border, border_alpha))
    inset = scale  # one real pixel of border
    draw.rounded_rectangle((inset, inset, width * scale - 1 - inset, height * scale - 1 - inset),
                           max(0, (radius - 1) * scale), fill=(*fill, fill_alpha))
    body = big.resize((width, height), Image.LANCZOS)
    hole = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hole.paste(body, (margin, margin))
    # The glow shows around the panel, not through its translucent body.
    if glow_alpha:
        mask = Image.new("L", (W, H), 0)
        mask.paste(body.getchannel("A"), (margin, margin))
        image.putalpha(ImageChops.subtract(image.getchannel("A"), mask))
    return Image.alpha_composite(image, hole), margin


def smooth_ellipse(size, box, fill=None, outline=None, width=1):
    """An anti-aliased circle or ellipse on a transparent image of `size`."""
    scale = 4
    big = Image.new("RGBA", (size[0] * scale, size[1] * scale), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse([v * scale for v in box], fill=fill, outline=outline, width=width * scale)
    return big.resize(size, Image.LANCZOS)


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


# ---------- Monitors ----------

def monitors():
    """[(monitor rect, work area rect, scale)] in physical pixels; scale is the monitor's DPI / 96."""
    import win32api
    found = []
    for handle, _, rect in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(handle)
        dpi_x, dpi_y = ctypes.c_uint(96), ctypes.c_uint(96)
        try:
            ctypes.windll.shcore.GetDpiForMonitor(ctypes.c_void_p(int(handle)), 0, ctypes.byref(dpi_x),
                                                  ctypes.byref(dpi_y))
        except (AttributeError, OSError):
            pass
        found.append((tuple(info["Monitor"]), tuple(info["Work"]), max(1.0, dpi_x.value / 96)))
    return found


def monitor_at(x, y, screens=None):
    """The (monitor, work area, scale) holding a point, or the nearest one."""
    screens = screens or monitors()
    for screen in screens:
        left, top, right, bottom = screen[0]
        if left <= x < right and top <= y < bottom:
            return screen

    def distance(screen):
        left, top, right, bottom = screen[0]
        return max(left - x, 0, x - right + 1) ** 2 + max(top - y, 0, y - bottom + 1) ** 2
    return min(screens, key=distance)


# ---------- Win32: one layered window ----------

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE,
                                   wt.DWORD]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
                                       ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]
user32.UpdateLayeredWindow.restype = wt.BOOL
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]

HWND_TOPMOST = wt.HWND(-1)
SWP_NOSIZE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x10, 0x40
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOPMOST = 0x80000, 0x20, 0x8
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x8000000
WM_MOUSEACTIVATE, WM_LBUTTONUP, WM_SETCURSOR, WM_DESTROY = 0x21, 0x202, 0x20, 0x2
MA_NOACTIVATE, SW_SHOWNOACTIVATE = 3, 4
CLASS = "JarvisOverlay"


def premultiplied_bgra(image):
    """PIL RGBA -> the premultiplied BGRA bytes UpdateLayeredWindow wants."""
    image = image.convert("RGBA")
    red, green, blue, alpha = image.split()
    red, green, blue = (ImageChops.multiply(c, alpha) for c in (red, green, blue))
    return Image.merge("RGBA", (blue, green, red, alpha)).tobytes()


_windows = {}        # hwnd -> Layer, for the window procedure
_class_ready = False


def _window_proc(hwnd, message, wparam, lparam):
    import win32gui
    layer = _windows.get(hwnd)
    if message == WM_MOUSEACTIVATE:
        return MA_NOACTIVATE                       # clicking the close button never takes the focus
    if message == WM_SETCURSOR and layer and layer.on_click:
        win32gui.SetCursor(win32gui.LoadCursor(0, 32649))   # the hand
        return 1
    if message == WM_LBUTTONUP and layer and layer.on_click:
        try:
            layer.on_click()
        except Exception as e:
            print(f"(overlay click: {e!r})", flush=True)
        return 0
    if message == WM_DESTROY:
        _windows.pop(hwnd, None)
        return 0
    return win32gui.DefWindowProc(hwnd, message, wparam, lparam)


class Layer:
    """One see-through window. Create, push and destroy it only on the overlay thread (HOST.call)."""

    def __init__(self, title="Jarvis overlay", on_click=None):
        global _class_ready
        import win32api
        import win32gui
        instance = win32api.GetModuleHandle(None)
        if not _class_ready:
            window_class = win32gui.WNDCLASS()
            window_class.lpfnWndProc, window_class.lpszClassName, window_class.hInstance = _window_proc, CLASS, instance
            window_class.hCursor = win32gui.LoadCursor(0, 32512)
            win32gui.RegisterClass(window_class)
            _class_ready = True
        self.on_click = on_click
        style = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if not on_click:
            style |= WS_EX_TRANSPARENT                 # the mouse goes straight through
        self.hwnd = win32gui.CreateWindowEx(style, CLASS, title, 0x80000000, 0, 0, 1, 1, 0, 0, instance, None)
        _windows[self.hwnd] = self
        self.size = (0, 0)
        self.position = (0, 0)
        self.alpha = 255
        self.bits = None
        self.source = None
        self.shown = False

    def push(self, image=None, position=None, alpha=None):
        """Show `image` (or the last one) at `position` (or the last one) with an overall opacity 0-255."""
        before = (self.source, self.position, self.alpha)
        if image is not None and image is not self.source:       # the same picture again: reuse its pixels
            self.bits, self.size, self.source = premultiplied_bgra(image), image.size, image
        if position is not None:
            self.position = (int(position[0]), int(position[1]))
        if alpha is not None:
            self.alpha = max(0, min(255, int(alpha)))
        if not self.bits:
            return False
        if self.shown and self.source is before[0] and (self.position, self.alpha) == before[1:]:
            return True                                           # nothing changed: skip the redraw
        width, height = self.size
        screen = user32.GetDC(None)
        memory = gdi32.CreateCompatibleDC(screen)
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(header), 0, ctypes.byref(pixels), None, 0)
        ok = False
        if bitmap and pixels.value:
            ctypes.memmove(pixels, self.bits, len(self.bits))
            old = gdi32.SelectObject(memory, bitmap)
            ok = bool(user32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(wt.POINT(*self.position)),
                                                 ctypes.byref(wt.SIZE(width, height)), memory,
                                                 ctypes.byref(wt.POINT(0, 0)), 0,
                                                 ctypes.byref(BLENDFUNCTION(0, 0, self.alpha, 1)), 2))
            gdi32.SelectObject(memory, old)
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)
        if ok and not self.shown:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self.shown = True
        return ok

    def move(self, x, y):
        """Move without redrawing; stays on top and never activates."""
        self.position = (int(x), int(y))
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, self.position[0], self.position[1], 0, 0,
                            SWP_NOSIZE | SWP_NOACTIVATE)

    def rect(self):
        return (*self.position, self.position[0] + self.size[0], self.position[1] + self.size[1])

    def destroy(self):
        import win32gui
        try:
            win32gui.DestroyWindow(self.hwnd)
        except Exception:
            pass
        _windows.pop(self.hwnd, None)


# ---------- The overlay thread ----------

class Host:
    """Owns every overlay window: runs calls handed to it, pumps window messages and ticks animations."""
    FAST, IDLE = 1 / 40, 0.05

    def __init__(self):
        self.calls = queue.Queue()
        self.tickers = {}          # name -> function(now) returning False to stop ticking
        self.thread = None
        self.lock = threading.Lock()

    def _ensure(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, daemon=True, name="jarvis-overlays")
            self.thread.start()

    def call(self, fn, *args, timeout=8):
        """Run fn(*args) on the overlay thread and return its result (or raise its error)."""
        if threading.current_thread() is self.thread:
            return fn(*args)
        self._ensure()
        done, box = threading.Event(), {}
        self.calls.put((fn, args, done, box))
        if not done.wait(timeout):
            raise TimeoutError("The on-screen overlay didn't respond.")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def tick(self, name, fn):
        """Call fn(now) every frame on the overlay thread until it returns False or is replaced/removed."""
        self.call(self.tickers.__setitem__, name, fn)

    def untick(self, name):
        self.call(self.tickers.pop, name, None)

    def _loop(self):
        import win32gui
        while True:
            try:
                win32gui.PumpWaitingMessages()
            except Exception:
                pass
            while True:
                try:
                    fn, args, done, box = self.calls.get_nowait()
                except queue.Empty:
                    break
                try:
                    box["result"] = fn(*args)
                except Exception as e:
                    box["error"] = e
                done.set()
            now = time.monotonic()
            for name, fn in list(self.tickers.items()):
                try:
                    keep = fn(now)
                except Exception as e:
                    print(f"(overlay {name} stopped: {e!r})", flush=True)
                    keep = False
                if keep is False and self.tickers.get(name) is fn:
                    self.tickers.pop(name, None)
            time.sleep(self.FAST if self.tickers else self.IDLE)


HOST = Host()
