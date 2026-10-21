"""Camera Eyes: the latest camera frame from the Brain page, held in memory only.

The browser only sends frames while the owner has EYES switched on. Nothing is written
to disk. JARVIS reads the newest frame on request (look_through_camera); a frame older
than FRESH seconds counts as "Eyes off", so a closed tab can't leave a stale view behind.
"""
import base64
import binascii
import threading
import time

FRESH = 12.0
MAX_BYTES = 600_000


class Eyes:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.jpeg = None
        self.at = 0.0

    def request(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
        action = payload.get("action")
        if action == "stop":
            with self.lock:
                self.jpeg, self.at = None, 0.0
            return self.snapshot()
        if action != "frame" or not isinstance(payload.get("jpeg"), str):
            raise ValueError("Send action 'frame' with a base64 JPEG, or 'stop'.")
        try:
            data = base64.b64decode(payload["jpeg"], validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Frame is not valid base64.") from None
        if not data.startswith(b"\xff\xd8") or len(data) > MAX_BYTES:
            raise ValueError("Frame must be a JPEG under 600 KB.")
        with self.lock:
            self.jpeg, self.at = data, self.clock()
        return self.snapshot()

    def snapshot(self):
        with self.lock:
            age = self.clock() - self.at if self.jpeg else None
            return {"on": age is not None and age <= FRESH,
                    "age": None if age is None else round(age, 1)}

    def latest(self):
        """(jpeg bytes, age seconds) of a fresh frame; LookupError when Eyes are off."""
        with self.lock:
            if self.jpeg is None or self.clock() - self.at > FRESH:
                raise LookupError("Camera Eyes are off. Switch on EYES in the Brain to let me see.")
            return self.jpeg, round(self.clock() - self.at, 1)


controller = Eyes()
