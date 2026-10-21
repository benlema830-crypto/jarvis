"""Move actual app windows without depending on keyboard focus or screenshots."""
import re
import time

import desktop  # establish physical-pixel DPI awareness first
import psutil
import win32api
import win32con
import win32gui
import win32process
import worksafe


def quick_action(text):
    """Recognize only single explicit commands; leave conversation/compound requests to the AI."""
    text = text.strip().rstrip(".!?")
    text = re.sub(r"^(?:(?:can|could|would) you\s+)?(?:please\s+)?", "", text, flags=re.I)
    text = re.sub(r",?\s+please$", "", text, flags=re.I)
    if re.search(r"\b(?:and|then|before|after|unless|if|except)\b|[;\n]", text, re.I):
        return None
    match = re.fullmatch(r"(minimize|maximize|restore|center)\s+(.+)", text, re.I)
    if match:
        return "control_app_window", {"app": match[2], "action": match[1].lower()}
    match = re.fullmatch(r"move\s+(.+?)\s+to\s+(?:my |the )?(second|secondary|primary|main|left|right)\s+(?:monitor|screen)", text, re.I)
    if match:
        return "move_app_window", {"app": match[1], "monitor": match[2].lower()}
    return None


def windows():
    result = []
    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or worksafe.is_blocked(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process = psutil.Process(pid).name()
        except (psutil.Error, OSError):
            process = ""
        result.append({"id": hwnd, "title": title, "process": process})
    win32gui.EnumWindows(visit, None)
    return result


def choose_window(items, name, foreground):
    query = " ".join(name.lower().split()).strip()
    if query in ("active", "current", "active window", "current window"):
        matches = [w for w in items if w["id"] == foreground]
    elif query in ("roblox studio", "roblox studios", "studio"):
        matches = [w for w in items if w["process"].lower() == "robloxstudiobeta.exe" or "roblox studio" in w["title"].lower()]
    else:
        matches = [w for w in items if query and (query in w["title"].lower() or query in w["process"].lower())]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"No visible window matches {name}.")
    active = [w for w in matches if w["id"] == foreground]
    if active:
        return active[0]
    raise ValueError("Several windows match. Ask which one: " + "; ".join(w["title"] for w in matches))


def monitors():
    return [(handle, win32api.GetMonitorInfo(handle)) for handle, _, _ in win32api.EnumDisplayMonitors()]


def choose_monitor(items, target):
    target = target.strip().lower()
    if target in ("second", "secondary", "other", "non-primary", "second monitor", "2nd"):
        matches = [(h, i) for h, i in items if not i["Flags"] & 1]
    elif target in ("primary", "main", "first"):
        matches = [(h, i) for h, i in items if i["Flags"] & 1]
    elif target in ("left", "right"):
        if not items:
            matches = []
        else:
            edge = min if target == "left" else max
            pos = edge(i["Monitor"][0] for _, i in items)
            matches = [(h, i) for h, i in items if i["Monitor"][0] == pos]
    else:
        number = re.fullmatch(r"(?:display\s*|monitor\s*)?(\d+)", target)
        matches = [(h, i) for h, i in items if number and i["Device"].upper().endswith("DISPLAY" + number[1])]
    if len(matches) != 1:
        raise ValueError("Specify the target monitor: " + "; ".join(i["Device"].removeprefix("\\\\.\\") + (" (primary)" if i["Flags"] & 1 else " (secondary)") for _, i in items))
    return matches[0]


def fit_rect(rect, work):
    left, top, right, bottom = work
    width = min(max(1, rect[2] - rect[0]), right - left)
    height = min(max(1, rect[3] - rect[1]), bottom - top)
    return left + (right - left - width) // 2, top + (bottom - top - height) // 2, width, height


def placement(action, rect, work):
    left, top, right, bottom = work
    middle = left + (right - left) // 2
    if action == "snap_left":
        return left, top, middle - left, bottom - top
    if action == "snap_right":
        return middle, top, right - middle, bottom - top
    return fit_rect(rect, work)


def control(name, action, target=""):
    """Normal window operations. Closing sends WM_CLOSE, never kills a process."""
    if action not in ("minimize", "maximize", "restore", "snap_left", "snap_right", "center", "close", "activate"):
        raise ValueError("Unknown window action.")
    window = choose_window(windows(), name, win32gui.GetForegroundWindow())
    hwnd, title = window["id"], window["title"]
    if not win32gui.IsWindow(hwnd) or worksafe.is_blocked(hwnd):
        raise ValueError("The selected window is no longer available.")
    if action == "close":
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        for _ in range(5):
            if not win32gui.IsWindow(hwnd):
                return f"{title} closed."
            time.sleep(0.05)
        return f"Close requested for {title}. It is still open and may be asking to save; I haven't dismissed any dialogs."
    if action in ("snap_left", "snap_right", "center"):
        if target:
            _, info = choose_monitor(monitors(), target)
        else:
            info = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST))
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        expected = placement(action, win32gui.GetWindowRect(hwnd), info["Work"])
        win32gui.SetWindowPos(hwnd, 0, *expected, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        x, y, width, height = expected
        expected_rect = (x, y, x + width, y + height)
        for _ in range(10):
            if all(abs(a - b) <= 12 for a, b in zip(win32gui.GetWindowRect(hwnd), expected_rect)):
                return f"{title} arranged: {action.replace('_', ' ')}."
            time.sleep(0.05)
        raise RuntimeError("The app did not accept the requested size or position.")
    if action == "activate":
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        check = lambda: win32gui.GetForegroundWindow() == hwnd
    else:
        code = {"minimize": win32con.SW_MINIMIZE, "maximize": win32con.SW_MAXIMIZE, "restore": win32con.SW_RESTORE}[action]
        win32gui.ShowWindow(hwnd, code)
        def check():
            if action == "minimize":
                return bool(win32gui.IsIconic(hwnd))
            show = win32gui.GetWindowPlacement(hwnd)[1]
            return show == win32con.SW_SHOWMAXIMIZED if action == "maximize" else not win32gui.IsIconic(hwnd) and show != win32con.SW_SHOWMAXIMIZED
    for _ in range(10):
        if check():
            return f"{title}: {action} completed."
        time.sleep(0.05)
    raise RuntimeError(f"Windows did not confirm {action} for {title}.")


def move(name, target="secondary"):
    window = choose_window(windows(), name, win32gui.GetForegroundWindow())
    handle, info = choose_monitor(monitors(), target)
    hwnd = window["id"]
    if not win32gui.IsWindow(hwnd) or worksafe.is_blocked(hwnd):
        raise ValueError("The selected window is no longer available.")
    maximized = win32gui.GetWindowPlacement(hwnd)[1] == win32con.SW_SHOWMAXIMIZED
    if win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST) == handle and not win32gui.IsIconic(hwnd):
        return f"{window['title']} is already on {info['Device'].removeprefix(chr(92) + chr(92) + '.' + chr(92))}."
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    x, y, width, height = fit_rect(win32gui.GetWindowRect(hwnd), info["Work"])
    win32gui.SetWindowPos(hwnd, 0, x, y, width, height, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
    if maximized:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    for _ in range(10):
        if win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST) == handle:
            return f"{window['title']} moved to the {'primary' if info['Flags'] & 1 else 'secondary'} monitor."
        time.sleep(0.05)
    raise RuntimeError("Windows did not move the window to the requested monitor. It may be elevated or refuse repositioning.")
