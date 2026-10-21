"""Physical Windows desktop geometry, including monitors left/above the primary."""
import ctypes
from dataclasses import dataclass
import math

import win32api

# Establish physical pixels before a screenshot/mouse library selects DPI scaling.
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    ctypes.windll.shcore.SetProcessDpiAwareness(2)


@dataclass(frozen=True)
class Monitor:
    name: str
    rect: tuple[int, int, int, int]
    primary: bool = False


@dataclass(frozen=True)
class Layout:
    monitors: tuple[Monitor, ...]

    @property
    def bounds(self):
        return (min(m.rect[0] for m in self.monitors), min(m.rect[1] for m in self.monitors),
                max(m.rect[2] for m in self.monitors), max(m.rect[3] for m in self.monitors))

    @property
    def size(self):
        left, top, right, bottom = self.bounds
        return right - left, bottom - top

    def shot_size(self, long_edge):
        width, height = self.size
        scale = min(1.0, long_edge / max(width, height))
        return max(1, round(width * scale)), max(1, round(height * scale))

    def to_native(self, coord, shot_size, edge=False):
        x, y = coord
        sw, sh = shot_size
        limit_x, limit_y = (sw, sh) if edge else (sw - 1, sh - 1)
        if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= limit_x and 0 <= y <= limit_y):
            raise ValueError("Coordinate is outside the desktop screenshot.")
        left, top, _, _ = self.bounds
        width, height = self.size
        return left + round(x * width / sw), top + round(y * height / sh)

    def to_shot(self, coord, shot_size):
        left, top, _, _ = self.bounds
        width, height = self.size
        return round((coord[0] - left) * shot_size[0] / width), round((coord[1] - top) * shot_size[1] / height)

    def contains(self, x, y):
        return any(l <= x < r and t <= y < b for l, t, r, b in (m.rect for m in self.monitors))

    def describe(self, shot_size):
        parts = []
        for monitor in self.monitors:
            l, t, r, b = monitor.rect
            start, end = self.to_shot((l, t), shot_size), self.to_shot((r, b), shot_size)
            parts.append(f"{monitor.name}{' (primary)' if monitor.primary else ''}: screenshot region {(*start, *end)}")
        return "; ".join(parts)


def current_layout():
    monitors = []
    for handle, _, rect in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(handle)
        monitors.append(Monitor(info["Device"].removeprefix("\\\\.\\"), tuple(rect), bool(info["Flags"] & 1)))
    if not monitors:
        raise RuntimeError("Windows reports no active monitors.")
    return Layout(tuple(sorted(monitors, key=lambda m: m.name)))
