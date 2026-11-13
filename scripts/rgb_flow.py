"""Keyboard and PC lights in one smooth flow: every OpenRGB device shows the same colour at the same moment,
drifting slowly through the rainbow.

Hardware rainbow modes on separate devices run at their own speeds and drift apart, so this drives them all
from one clock through the OpenRGB service's SDK server (127.0.0.1:6742). It reconnects if OpenRGB restarts
and picks up devices that appear later.

    pythonw scripts/rgb_flow.py [--period SECONDS] [--brightness 0-100]
"""
import argparse
import colorsys
import socket
import struct
import time

HOST, PORT = "127.0.0.1", 6742
FPS = 30
REQUEST_CONTROLLER_COUNT, REQUEST_CONTROLLER_DATA, SET_CLIENT_NAME = 0, 1, 50
UPDATE_LEDS, SET_CUSTOM_MODE = 1050, 1100
RESCAN_SECONDS = 60


def packet(device, kind, data=b""):
    return b"ORGB" + struct.pack("<III", device, kind, len(data)) + data


class OpenRGB:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=5)
        self.sock.sendall(packet(0, SET_CLIENT_NAME, b"Jarvis RGB flow\x00"))

    def _recv_exact(self, n):
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("OpenRGB closed the connection")
            out += chunk
        return out

    def _reply(self, kind):
        while True:
            magic, _device, got, size = struct.unpack("<4sIII", self._recv_exact(16))
            data = self._recv_exact(size)
            if magic == b"ORGB" and got == kind:
                return data

    def led_counts(self):
        """Number of LEDs on each controller, in controller order."""
        self.sock.sendall(packet(0, REQUEST_CONTROLLER_COUNT))
        count = struct.unpack("<I", self._reply(REQUEST_CONTROLLER_COUNT))[0]
        counts = []
        for i in range(count):
            self.sock.sendall(packet(i, REQUEST_CONTROLLER_DATA))
            counts.append(parse_led_count(self._reply(REQUEST_CONTROLLER_DATA)))
        return counts

    def direct(self, index):
        self.sock.sendall(packet(index, SET_CUSTOM_MODE))

    def paint(self, index, leds, rgb):
        colors = bytes((rgb[0], rgb[1], rgb[2], 0)) * leds
        body = struct.pack("<H", leds) + colors
        self.sock.sendall(packet(index, UPDATE_LEDS, struct.pack("<I", 4 + len(body)) + body))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def parse_led_count(d):
    """LED count from a protocol-0 controller description."""
    o = 4 + 4  # data size, device type

    def u16():
        nonlocal o
        v = struct.unpack_from("<H", d, o)[0]
        o += 2
        return v

    def u32():
        nonlocal o
        v = struct.unpack_from("<I", d, o)[0]
        o += 4
        return v

    def skip(n):
        nonlocal o
        o += n

    # read the length first: "o += u16()" would add to the offset from before u16() moved it
    for _ in range(5):            # name, description, version, serial, location
        skip(u16())
    modes = u16()
    u32()                         # active mode
    for _ in range(modes):
        skip(u16())               # name
        skip(4 * 9)               # value, flags, speed min/max, colors min/max, speed, direction, colour mode
        skip(4 * u16())           # mode colours
    for _ in range(u16()):        # zones
        skip(u16())               # name
        skip(4 * 4)               # type, leds min, leds max, leds count
        skip(u16())               # matrix (height, width, map), 0 when none
    return u16()


def colour(t, period, brightness):
    r, g, b = colorsys.hsv_to_rgb((t / period) % 1.0, 1.0, brightness)
    return round(r * 255), round(g * 255), round(b * 255)


def run(period, brightness):
    while True:
        try:
            rgb = OpenRGB()
        except OSError:
            time.sleep(5)  # OpenRGB not up yet (just logged in) — keep trying
            continue
        try:
            counts = rgb.led_counts()
            for i in range(len(counts)):
                rgb.direct(i)
            rescan = time.monotonic() + RESCAN_SECONDS
            while True:
                c = colour(time.time(), period, brightness)  # wall clock: a restart picks up the same colour
                for i, leds in enumerate(counts):
                    if leds:
                        rgb.paint(i, leds, c)
                time.sleep(1 / FPS)
                if time.monotonic() > rescan:  # a device plugged in later joins the flow
                    rescan = time.monotonic() + RESCAN_SECONDS
                    fresh = rgb.led_counts()
                    if fresh != counts:
                        counts = fresh
                        for i in range(len(counts)):
                            rgb.direct(i)
        except (OSError, ConnectionError, struct.error):
            rgb.close()
            time.sleep(3)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--period", type=float, default=30, help="seconds for one trip around the rainbow")
    ap.add_argument("--brightness", type=float, default=100, help="0-100")
    args = ap.parse_args()
    run(max(2.0, args.period), max(0.0, min(100.0, args.brightness)) / 100)
