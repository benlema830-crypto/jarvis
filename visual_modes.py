"""Explicit, local-only Watch/Focus sessions. Importing this module observes nothing."""
import base64
import io
import math
import re
import threading
import time
import uuid

CADENCE = 5.0
LEASE = 15.0


def screen_preview():
    # The existing work-app mask is the only capture path. Never save frames.
    import worksafe
    image = worksafe.grab()
    try:
        image.thumbnail((960, 540))
        with io.BytesIO() as output:
            image.save(output, format="JPEG", quality=65)
            return base64.b64encode(output.getvalue()).decode("ascii")
    finally:
        image.close()


def foreground_app():
    import worksafe
    hwnd = worksafe.win32gui.GetForegroundWindow()
    if not hwnd:
        return {"kind": "unknown"}
    if worksafe.is_blocked(hwnd):
        return {"kind": "protected"}
    process = worksafe._process_name(hwnd)
    # Titles and URLs are intentionally neither read here nor returned.
    return {"kind": "app", "process": process} if process else {"kind": "unknown"}


def running_apps():
    """Distinct executables with a visible, titled window, for the Focus picker. Work apps excluded."""
    import worksafe
    found = set()

    def visit(hwnd, _):
        if (worksafe.win32gui.IsWindowVisible(hwnd) and worksafe.win32gui.GetWindowText(hwnd).strip()
                and not worksafe.is_blocked(hwnd)):
            name = worksafe._process_name(hwnd)
            if name.endswith(".exe") and name not in ("explorer.exe", "textinputhost.exe", "applicationframehost.exe"):
                found.add(name)
        return True
    worksafe.win32gui.EnumWindows(visit, None)
    return sorted(found)


class VisualModes:
    def __init__(self, capture=screen_preview, observe=foreground_app, clock=time.monotonic):
        self.capture, self.observe, self.clock = capture, observe, clock
        self.on_event = None  # set by the Brain server: focus drift / completion -> spoken callout
        self.callouts = True
        self.lease_free = False
        self.lock = threading.RLock()
        self.worker = None
        self.cancel = threading.Event()
        self.state = "off"
        self.mode = None
        self.session = ""
        self.error = ""
        self.reason = "Not started."
        self.preview = None
        self.started = self.deadline = self.lease = self.next_sample = 0
        self.last_sample = None
        self.samples = self.drifts = 0
        self.target = ""
        self.evidence = []
        self.away_since = None
        self.away_counted = False
        self.target_seen = False
        self.observation = "Not observed."

    def _finish(self, reason, error=""):
        if self.mode == "focus" and self.state in ("starting", "running") and reason == "Duration completed.":
            self._emit("focus_done", count=self.drifts, target=self.target)
        self.cancel.set()
        self.state = "error" if error else "off"
        self.reason, self.error = reason, error
        self.preview = None

    def snapshot(self):
        with self.lock:
            now = self.clock()
            return dict(state=self.state, mode=self.mode, session=self.session,
                        reason=self.reason, error=self.error, target=self.target,
                        remaining_seconds=max(0, math.ceil(self.deadline - now)) if self.state in ("running", "starting") else 0,
                        cadence_seconds=CADENCE, lease_seconds=LEASE,
                        samples=self.samples, drift_count=self.drifts,
                        last_sample_age=None if self.last_sample is None else max(0, round(now - self.last_sample, 1)),
                        observation=self.observation, evidence=[dict(item) for item in self.evidence],
                        target_seen=self.target_seen, callouts=self.callouts,
                        needs_heartbeat=not self.lease_free,
                        preview=self.preview)

    def _emit(self, kind, **data):
        if self.on_event and self.callouts:
            threading.Thread(target=self.on_event, args=(dict(data, event=kind),), daemon=True).start()

    def start(self, mode, minutes, target="", *, threaded=True, callouts=True):
        if mode not in ("watch", "focus"):
            raise ValueError("Choose Watch or Focus. Camera Eyes is not implemented.")
        if type(minutes) is not int or not 1 <= minutes <= (30 if mode == "watch" else 120):
            raise ValueError("Duration must be 1-30 minutes for Watch or 1-120 for Focus.")
        if mode == "focus" and (not isinstance(target, str) or not re.fullmatch(r"[\w .()-]{1,80}\.exe", target, re.ASCII | re.IGNORECASE)):
            raise ValueError("Enter the exact app executable, for example Code.exe. Browser tabs cannot be distinguished.")
        with self.lock:
            if self.state in ("starting", "running", "stopping") or (self.worker and self.worker.is_alive()):
                raise ValueError("Stop the current visual session and wait for cleanup first.")
            now = self.clock()
            self.cancel = threading.Event()
            self.session = uuid.uuid4().hex
            self.mode, self.target = mode, target.lower() if mode == "focus" else ""
            self.state, self.reason, self.error = "starting", "Waiting for first observation.", ""
            self.started, self.deadline, self.lease, self.next_sample = now, now + minutes * 60, now + LEASE, now
            self.last_sample = self.preview = self.away_since = None
            self.samples = self.drifts = 0
            self.evidence = []
            self.away_counted = False
            self.target_seen = False
            self.observation = "Not observed."
            self.callouts = bool(callouts)
            # Focus reads only process names for a fixed duration, so it keeps running while
            # the owner works in another window. Watch (pixels) still needs the page's heartbeat.
            self.lease_free = mode == "focus"
            if threaded:
                self.worker = threading.Thread(target=self._run, daemon=True, name="local-visual-mode")
                self.worker.start()
            return self.snapshot()

    def heartbeat(self, session):
        with self.lock:
            if session != self.session or self.state not in ("starting", "running"):
                raise ValueError("This visual session is no longer active.")
            if self.clock() >= (self.deadline if self.lease_free else min(self.deadline, self.lease)):
                self._finish("Session expired. Start explicitly to resume.")
            else:
                self.lease = self.clock() + LEASE
            return self.snapshot()

    def stop(self):
        with self.lock:
            self.cancel.set()
            self.preview = None
            if self.worker and self.worker.is_alive():
                self.state, self.reason = "stopping", "Waiting for an in-flight observation to finish; its result will be discarded."
            else:
                self._finish("Stopped.")
            return self.snapshot()

    def _run(self):
        try:
            while not self.cancel.is_set():
                self.step()
                self.cancel.wait(0.25)
        except Exception:
            with self.lock:
                self._finish("Session stopped.", "Local observation failed. Start again after checking desktop access.")
        finally:
            with self.lock:
                if self.state == "stopping":
                    self._finish("Stopped; cleanup complete.")

    def step(self):
        """One scheduler tick; injected effects/clock keep tests entirely inert."""
        with self.lock:
            if self.cancel.is_set() or self.state not in ("starting", "running"):
                return
            now = self.clock()
            if now >= self.deadline:
                self._finish("Duration completed.")
                return
            if now >= self.lease and not self.lease_free:
                self._finish("Panel heartbeat expired; observations stopped.")
                return
            if now < self.next_sample:
                return
            # Reserve this tick so concurrent requests cannot cause extra sampling.
            self.next_sample = float("inf")
            mode = self.mode
        try:
            value = self.capture() if mode == "watch" else self.observe()
        except Exception:
            with self.lock:
                if not self.cancel.is_set():
                    message = ("Screen capture unavailable. Check Windows desktop access and display availability, then start again."
                               if mode == "watch" else "Foreground app unavailable. Check Windows desktop access, then start again.")
                    self._finish("Observation failed; session stopped.", message)
            return
        with self.lock:
            now = self.clock()
            # A native capture already in progress cannot be cancelled. Discard it.
            if self.cancel.is_set():
                return
            if now >= (self.deadline if self.lease_free else min(self.deadline, self.lease)):
                self._finish("Session expired during observation; result discarded.")
                return
            self.next_sample = now + CADENCE
            self.last_sample = now
            self.samples += 1
            self.state, self.reason = "running", "Observing locally."
            if mode == "watch":
                self.preview = value
                self.observation = "Masked desktop preview; no AI analysis."
            else:
                self._focus(value, now)

    def _focus(self, value, now):
        kind = value.get("kind")
        process = str(value.get("process", "")).lower()[:84]
        if kind != "app" or not process:
            self.observation = "Work app hidden." if kind == "protected" else "Foreground unknown."
            self.away_since = None
            # Unknown/protected samples are not evidence of returning to the target.
            return
        self.observation = process
        if process == self.target:
            self.target_seen = True
            self.away_since, self.away_counted = None, False
        elif not self.target_seen:
            self.observation = "Waiting to see " + self.target + "; currently " + process
        elif not self.away_counted:
            if self.away_since is None:
                self.away_since = now
            elif now - self.away_since >= CADENCE:
                self.drifts += 1
                self.away_counted = True
                self.evidence.append(dict(elapsed_seconds=int(now - self.started), process=process,
                                          basis="Two consecutive off-target samples at least 5 seconds apart."))
                self.evidence = self.evidence[-20:]
                self._emit("focus_drift", count=self.drifts, app=process, target=self.target,
                           minutes_left=max(0, int((self.deadline - now) // 60)))

    def request(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
        action = payload.get("action")
        if action == "start":
            return self.start(payload.get("mode"), payload.get("minutes"), payload.get("target", ""),
                              callouts=payload.get("callouts", True) is not False)
        if action == "stop":
            return self.stop()
        if action == "heartbeat":
            return self.heartbeat(payload.get("session"))
        raise ValueError("Unknown visual-mode action.")


controller = VisualModes()
