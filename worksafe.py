"""Work-safe mode: keeps Outlook and Teams (which may hold CUI) away from Jarvis.

- Their windows are blacked out of every screenshot Jarvis or the agent takes.
- The agent can't click or type into them.
- The clipboard isn't read while one of them is in front.
- The activity log records them only as "work app", with no window title.

This covers the desktop apps and the web versions in a browser.
"""

import ctypes
import re

import psutil
import win32gui
import win32process

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixel coordinates (harmless if already set)
except OSError:
    pass

BLOCKED_PROCESSES = {"outlook.exe", "olk.exe", "ms-teams.exe", "teams.exe", "msteams.exe"}
# Outlook / Teams in a browser tab or as an installed web app, e.g. "Mail - Ben - Outlook - Google Chrome"
BLOCKED_TITLE = re.compile(r"(?:^|[-|–]\s)(?:Microsoft\s+)?Outlook(?:\s|$)|Microsoft Teams", re.I)
GA_ROOT = 2


def _process_name(hwnd) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name().lower()
    except (psutil.Error, ValueError, OSError):
        return ""


def title_blocked(title: str) -> bool:
    return bool(BLOCKED_TITLE.search(title.strip()))


def is_blocked(hwnd) -> bool:
    if not hwnd:
        return False
    return _process_name(hwnd) in BLOCKED_PROCESSES or title_blocked(win32gui.GetWindowText(hwnd))


def foreground_blocked() -> bool:
    return is_blocked(win32gui.GetForegroundWindow())


def point_blocked(x: int, y: int) -> bool:
    """Is the window under this screen point a work app?"""
    hwnd = win32gui.WindowFromPoint((int(x), int(y)))
    return is_blocked(win32gui.GetAncestor(hwnd, GA_ROOT) if hwnd else 0)


def blocked_rects() -> list[tuple[int, int, int, int]]:
    rects = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd) and is_blocked(hwnd):
            rects.append(win32gui.GetWindowRect(hwnd))

    win32gui.EnumWindows(visit, None)
    return rects


def grab(bbox: tuple[int, int, int, int] | None = None):
    """Screenshot of the primary screen (or `bbox`) with work-app windows blacked out."""
    from PIL import ImageDraw, ImageGrab

    img = ImageGrab.grab(bbox=bbox).convert("RGB")
    ox, oy = (bbox[0], bbox[1]) if bbox else (0, 0)
    draw = ImageDraw.Draw(img)
    for left, top, right, bottom in blocked_rects():
        box = [left - ox, top - oy, right - ox, bottom - oy]
        draw.rectangle(box, fill=(0, 0, 0))
        draw.text((box[0] + 20, box[1] + 20), "Work app hidden by Jarvis work-safe mode", fill=(200, 200, 200))
    return img
