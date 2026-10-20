"""Chatterbox Turbo voice server. Runs in tts-venv; Jarvis starts it automatically.

Protocol (over stdin/stdout):
  startup -> server writes: uint32 sample_rate        (or exits with code 3 if the GPU is too busy)
  request -> one line of UTF-8 text
  reply   -> uint32 byte count, then float32 mono PCM  (count 0 = error)
"""

import os
import struct
import sys

os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")  # model is already downloaded; don't wait on the network at boot

# The protocol owns the real stdout; send every library print/log to stderr instead.
proto = os.fdopen(os.dup(1), "wb")
os.dup2(2, 1)
sys.stdout = sys.stderr

import subprocess  # noqa: E402
import time  # noqa: E402

import torch  # noqa: E402

MIN_FREE_VRAM_GB = float(os.getenv("JARVIS_TTS_MIN_VRAM_GB", "4.5"))  # model needs ~3.3 GB, plus headroom
MAX_GPU_BUSY_PERCENT = 40  # e.g. model training or a game is running


def gpu_busy_percent() -> float:
    samples = []
    for _ in range(4):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
            samples.append(float(out.split()[0]))
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            return 0.0
        time.sleep(0.25)
    return sum(samples) / len(samples)


def main():
    voice_sample = sys.argv[1]
    if not torch.cuda.is_available():
        print("No CUDA GPU available", file=sys.stderr)
        sys.exit(3)
    free, _ = torch.cuda.mem_get_info()
    if free / 1e9 < MIN_FREE_VRAM_GB:
        print(f"GPU busy: only {free / 1e9:.1f} GB free", file=sys.stderr)
        sys.exit(3)
    if (busy := gpu_busy_percent()) > MAX_GPU_BUSY_PERCENT:
        print(f"GPU busy: {busy:.0f}% utilization from another program", file=sys.stderr)
        sys.exit(3)

    from chatterbox.tts_turbo import ChatterboxTurboTTS

    model = ChatterboxTurboTTS.from_pretrained(device="cuda")
    model.prepare_conditionals(voice_sample)
    with torch.inference_mode():
        model.generate("Warming up.")

    proto.write(struct.pack("<I", model.sr))
    proto.flush()

    for line in sys.stdin.buffer:
        text = line.decode("utf-8").strip()
        try:
            with torch.inference_mode():
                wav = model.generate(text).squeeze(0).numpy().astype("float32")
            data = wav.tobytes()
        except Exception as e:
            print(f"generate failed: {e!r}", file=sys.stderr)
            data = b""
        proto.write(struct.pack("<I", len(data)))
        proto.write(data)
        proto.flush()


if __name__ == "__main__":
    main()
