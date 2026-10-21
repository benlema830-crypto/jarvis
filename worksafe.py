"""Work-safe mode: keeps Outlook and Teams (which may hold CUI) away from Jarvis.

- Their windows are blacked out of every screenshot Jarvis or the agent takes.
- The agent can't click or type into them.
- The clipboard isn't read while one of them is in front.
- The activity log records them only as "work app", with no window title.

This covers the desktop apps and the web versions in a browser.

JARVIS_ALLOW_OUTLOOK=1 in .env lifts this for Outlook (personal accounts only on this PC);
Teams stays blocked either way.
"""

import ctypes
import os
import re

import desktop

import psutil
import win32gui
import win32process

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixel coordinates (harmless if already set)
except OSError:
    pass

OUTLOOK_PROCESSES = {"outlook.exe", "olk.exe"}
TEAMS_PROCESSES = {"ms-teams.exe", "teams.exe", "msteams.exe"}
# Outlook / Teams in a browser tab or as an installed web app, e.g. "Mail - Ben - Outlook - Google Chrome"
OUTLOOK_TITLE = re.compile(r"(?:^|[-|–]\s)(?:Microsoft\s+)?Outlook(?:\s|$)", re.I)
TEAMS_TITLE = re.compile(r"Microsoft Teams", re.I)
GA_ROOT = 2


def outlook_allowed() -> bool:
    return os.getenv("JARVIS_ALLOW_OUTLOOK", "").strip().lower() in ("1", "true", "yes", "on")


def blocked_processes() -> set[str]:
    return TEAMS_PROCESSES if outlook_allowed() else TEAMS_PROCESSES | OUTLOOK_PROCESSES


def blocked_apps() -> str:
    """How to name the blocked apps in messages and prompts."""
    return "Teams" if outlook_allowed() else "Outlook or Teams"


def _process_name(hwnd) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name().lower()
    except (psutil.Error, ValueError, OSError):
        return ""


def title_blocked(title: str) -> bool:
    title = title.strip()
    return bool(TEAMS_TITLE.search(title) or (not outlook_allowed() and OUTLOOK_TITLE.search(title)))


def is_blocked(hwnd) -> bool:
    if not hwnd:
        return False
    return _process_name(hwnd) in blocked_processes() or title_blocked(win32gui.GetWindowText(hwnd))


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
    """Capture all monitors (or a physical-pixel region), masking work-app windows."""
    from PIL import ImageDraw, ImageGrab

    bounds = bbox if bbox is not None else desktop.current_layout().bounds
    img = ImageGrab.grab(bbox=bounds, all_screens=True).convert("RGB")
    ox, oy = bounds[:2]
    draw = ImageDraw.Draw(img)
    for left, top, right, bottom in blocked_rects():
        box = [max(0, left - ox), max(0, top - oy), min(img.width - 1, right - ox), min(img.height - 1, bottom - oy)]
        if box[2] < box[0] or box[3] < box[1]:
            continue
        draw.rectangle(box, fill=(0, 0, 0))
        draw.text((box[0] + 20, box[1] + 20), "Work app hidden by Jarvis work-safe mode", fill=(200, 200, 200))
    return img
