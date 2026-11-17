"""Log what the INZONE H5 headset mic sends, second by second, to learn what "headset off" looks like.

Run: .venv\\Scripts\\python.exe scripts\\headset_probe.py [minutes]   (default 20; writes data/headset-probe.log)

Why (2026-11-16): the dongle stays connected in Windows with the headset off, so the laptop-mic rule
(desk_bridge.headset_on) needs a sign of on/off from the signal. Measured with the headset ON and the owner
quiet: the raw WASAPI stream (48 kHz float) is exact digital zero for 90 s straight; the headset gates its mic,
so there is no hiss to see. The 0/+-1 values Jarvis's 16 kHz int16 MME stream shows are Windows conversion
dither, the same whether anything is there or not. The vendor HID channels sent nothing passively either.
This probe opens the raw stream (it runs alongside Jarvis's) and logs per second: how many frames arrived,
the share of exact zeros, rms and peak, so a switch off and on can be compared against the quiet-but-on rows.
"""
import os
import sys
import time

import numpy as np
import sounddevice as sd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(HERE, "data", "headset-probe.log")


def device() -> int | None:
    for i, d in enumerate(sd.query_devices()):
        if ("INZONE" in d["name"] and d["max_input_channels"] > 0
                and sd.query_hostapis(d["hostapi"])["name"] == "Windows WASAPI"):
            return i
    return None


def main(minutes: float) -> None:
    end = time.time() + minutes * 60
    with open(LOG, "a", encoding="utf-8", buffering=1) as log:
        log.write(f"--- probe start {time.strftime('%Y-%m-%d %H:%M:%S')} for {minutes:g} min\n")
        while time.time() < end:
            dev = device()
            if dev is None:
                log.write(f"{time.strftime('%H:%M:%S')} no INZONE WASAPI input\n")
                time.sleep(5)
                continue
            got = []
            try:
                with sd.InputStream(samplerate=48000, channels=1, dtype="float32", device=dev,
                                    callback=lambda data, *_: got.append(data[:, 0].copy())):
                    while time.time() < end:
                        time.sleep(1)
                        chunk, got[:] = list(got), []
                        a = np.concatenate(chunk).astype(np.float64) if chunk else np.zeros(0)
                        zero = np.mean(a == 0) * 100 if a.size else 100.0
                        rms = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
                        peak = float(np.abs(a).max()) if a.size else 0.0
                        log.write(f"{time.strftime('%H:%M:%S')} frames {a.size:6d} zero {zero:6.2f}% "
                                  f"rms {rms:.2e} peak {peak:.2e}\n")
            except Exception as exc:
                log.write(f"{time.strftime('%H:%M:%S')} stream error {type(exc).__name__}: {exc}\n")
                time.sleep(2)
        log.write(f"--- probe end {time.strftime('%Y-%m-%d %H:%M:%S')}\n")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 20)
