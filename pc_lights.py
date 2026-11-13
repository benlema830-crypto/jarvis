"""The lights around the desk, and the screens themselves: off for sleeping, back on afterwards.

Three things glow in the bedroom at night while the PC works: the keyboard, case and graphics card (OpenRGB, kept
moving by scripts/rgb_flow.py), the LED strips behind the monitors (WLED through Home Assistant, "monitor
lights"), and the two screens. On 2026-11-12 "turn my computer lights off and my monitors off, an agent is running
but I'm trying to sleep" got the ceiling lights dimmed instead, and then the PC put to sleep, which stopped the
agent. This switches each of the three, and nothing else on the PC stops.

Each part reports what was observed: the backlights are read back through Home Assistant, the PC lights from
OpenRGB's own record of what each device shows. Windows gives no reading for screens that are powered down, so
that part says "sent".
"""
import ctypes
import importlib.util
import struct
import subprocess
import sys
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
FLOW = HERE / "scripts" / "rgb_flow.py"
BACKLIGHTS = "monitor lights"     # the Home Assistant group of both monitor strips (data/home-device-defaults.json)
PARTS = ("backlights", "rgb", "screens")
WORDS = {"all": PARTS, "everything": PARTS, "": PARTS,
         "rgb": ("rgb",), "pc": ("rgb",), "pc lights": ("rgb",), "computer lights": ("rgb",), "keyboard": ("rgb",),
         "case": ("rgb",), "lights": ("backlights", "rgb"), "backlights": ("backlights",),
         "monitor lights": ("backlights",), "backlight": ("backlights",), "led strips": ("backlights",),
         "screens": ("screens",), "monitors": ("screens",), "displays": ("screens",), "screen": ("screens",)}
HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MOUSEEVENTF_MOVE = 0xFFFF, 0x0112, 0xF170, 0x0001
SCREENS_OFF_AFTER = 4   # seconds, so the reply is on screen (or said) before they go dark


def _flow_module():
    spec = importlib.util.spec_from_file_location("rgb_flow", FLOW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def flow_processes():
    """The running scripts/rgb_flow.py processes (it is started at login from the Startup folder)."""
    found = []
    for process in psutil.process_iter(["cmdline"]):
        try:
            if any("rgb_flow.py" in part for part in process.info["cmdline"] or []):
                found.append(process)
        except (psutil.Error, TypeError):
            pass
    return found


def parse_colours(d):
    """[(r, g, b), ...] the controller reports for its LEDs (OpenRGB protocol 0 controller description)."""
    o = 4 + 4  # data size, device type

    def u16():
        nonlocal o
        v = struct.unpack_from("<H", d, o)[0]
        o += 2
        return v

    def skip(n):
        nonlocal o
        o += n

    # Read each length first: "o += u16()" would add to the offset from before u16() moved it.
    for _ in range(5):                 # name, description, version, serial, location
        skip(u16())
    modes = u16()
    skip(4)                            # active mode
    for _ in range(modes):
        skip(u16())                    # name
        skip(4 * 9)
        skip(4 * u16())                # mode colours
    for _ in range(u16()):             # zones
        skip(u16())
        skip(4 * 4)
        skip(u16())                    # matrix
    for _ in range(u16()):             # LEDs: name, value
        skip(u16())
        skip(4)
    count = u16()
    return [tuple(d[o + 4 * i: o + 4 * i + 3]) for i in range(count)]


def _rgb_off():
    stopped = flow_processes()
    for process in stopped:
        try:
            process.terminate()
        except psutil.Error:
            pass
    psutil.wait_procs(stopped, timeout=3)
    flow = _flow_module()
    try:
        rgb = flow.OpenRGB()
    except OSError:
        return "Keyboard and PC lights: NOT DONE, the OpenRGB service isn't answering."
    try:
        counts = rgb.led_counts()
        for _ in range(2):                       # twice: the keyboard can drop the first frame after a mode change
            for index, leds in enumerate(counts):
                rgb.direct(index)
                if leds:
                    rgb.paint(index, leds, (0, 0, 0))
            time.sleep(.3)
        lit = 0
        for index, leds in enumerate(counts):
            rgb.sock.sendall(flow.packet(index, flow.REQUEST_CONTROLLER_DATA))
            if any(any(colour) for colour in parse_colours(rgb._reply(flow.REQUEST_CONTROLLER_DATA))):
                lit += 1
    except (OSError, ConnectionError, struct.error, IndexError):
        return "Keyboard and PC lights: off was sent, but OpenRGB didn't answer the check afterwards. NOT CONFIRMED."
    finally:
        rgb.close()
    devices = sum(1 for leds in counts if leds)
    if lit:
        return (f"Keyboard and PC lights: NOT CONFIRMED, {lit} of {devices} devices still report a colour after "
                "being switched off.")
    return f"Keyboard and PC lights: Confirmed off on all {devices} devices (the keyboard, the case and the graphics card)."


def _rgb_on():
    if flow_processes():
        return "Keyboard and PC lights were already on (the colour flow is running), so nothing changed."
    python = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(python if python.exists() else sys.executable), str(FLOW)], cwd=str(HERE),
                     creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if flow_processes():
            return "Keyboard and PC lights: Confirmed on, the colour flow is running again."
        time.sleep(.2)
    return "Keyboard and PC lights: NOT CONFIRMED, the colour flow didn't start."


def _backlights(on):
    import home_assistant
    try:
        return "Monitor backlights: " + home_assistant.control(BACKLIGHTS, "turn_on" if on else "turn_off")
    except Exception as error:
        return f"Monitor backlights: NOT DONE ({error})."


def _screens_power(state):
    ctypes.windll.user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, state)


def _screens(on):
    import threading
    if on:
        _screens_power(-1)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, 0, 1, 0, 0)   # some monitors only wake on input
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, 0, -1, 0, 0)
        return "Screens: wake sent."
    timer = threading.Timer(SCREENS_OFF_AFTER, _screens_power, args=(2,))
    timer.daemon = True
    timer.start()
    return (f"Screens: both go dark in {SCREENS_OFF_AFTER} seconds (sent; Windows can't confirm it). They come back "
            "when the mouse or keyboard is touched, or when asked for.")


def _status():
    import home_assistant
    lines = ["Status:", "Keyboard and PC lights: " + ("on, the colour flow is running" if flow_processes()
                                           else "the colour flow is not running, so they are off or frozen")]
    try:
        lines.append("Monitor backlights: " + home_assistant.status(BACKLIGHTS))
    except Exception as error:
        lines.append(f"Monitor backlights: unknown ({error})")
    lines.append("Screens: Windows doesn't report whether they are powered down.")
    return "\n".join(lines)


def control(action, what="all", running=()):
    """Switch the chosen lights. `running` is the background work going on, named in the result so the owner
    hears that it carries on."""
    action = action.strip().lower().replace("turn_", "").replace("turn ", "")
    if action == "status":
        return _status()
    if action not in ("on", "off"):
        raise ValueError("Use on, off or status.")
    key = what.strip().lower().replace("_", " ")
    if key not in WORDS:
        raise ValueError("Choose what to switch: all, rgb (keyboard and PC lights), backlights (the strips behind "
                         "the monitors) or screens.")
    on = action == "on"
    work = {"backlights": _backlights, "rgb": lambda lit: _rgb_on() if lit else _rgb_off(), "screens": _screens}
    lines = [work[part](on) for part in WORDS[key]]
    if not on:
        lines.append("Nothing else was touched: the PC stays awake" +
                     (f", and {', '.join(running)} keep{'s' if len(running) == 1 else ''} running." if running
                      else " and anything running carries on."))
    return "\n".join(lines)
