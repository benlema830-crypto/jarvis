"""Memory watch: log how much RAM Jarvis's processes hold, to see whether any of them grows over time (a leak).

Started 2026-11-11 after the VoiceStudio speech worker was found holding 11 GB after nine days up.
A Windows scheduled task ("Jarvis memory watch") runs this every two hours; each run appends one line
to data/memory-watch.jsonl. It reads only and changes nothing.

    pythonw scripts/memory_watch.py            take one sample
    python  scripts/memory_watch.py --report   show growth per day for each watched process
"""
import argparse
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "memory-watch.jsonl"
GB = 1024 ** 3
VOICESTUDIO = (str(Path(os.getenv("APPDATA", "")) / "VoiceStudio").casefold(),
               str(Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "VoiceStudio").casefold())
TOP = 8


class _PerfInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("CommitTotal", ctypes.c_size_t), ("CommitLimit", ctypes.c_size_t),
                ("CommitPeak", ctypes.c_size_t), ("PhysicalTotal", ctypes.c_size_t),
                ("PhysicalAvailable", ctypes.c_size_t), ("SystemCache", ctypes.c_size_t),
                ("KernelTotal", ctypes.c_size_t), ("KernelPaged", ctypes.c_size_t),
                ("KernelNonpaged", ctypes.c_size_t), ("PageSize", ctypes.c_size_t),
                ("HandleCount", wintypes.DWORD), ("ProcessCount", wintypes.DWORD), ("ThreadCount", wintypes.DWORD)]


def commit_gb():
    """(used, limit) of the commit charge: memory programs have reserved, out of RAM + page file."""
    info = _PerfInfo()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        return None, None
    return info.CommitTotal * info.PageSize / GB, info.CommitLimit * info.PageSize / GB


def watched_name(exe, cmdline):
    """A short label for the processes worth tracking one by one, else ''."""
    exe = (exe or "").casefold()
    line = " ".join(cmdline or []).casefold()
    if exe.startswith(VOICESTUDIO):
        return "voicestudio-worker" if "python" in Path(exe).name else "voicestudio-app"
    if "python" in Path(exe).name:
        for script in ("jarvis.py", "brain.py", "spotify_mcp.py"):
            if script in line:
                return script
    if Path(exe).name == "ollama.exe":
        return "ollama"
    return ""


def sample():
    procs = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
        try:
            mem = proc.memory_info()
            procs.append({"pid": proc.pid, "name": proc.info["name"],
                          "watch": watched_name(proc.info["exe"], proc.info["cmdline"]),
                          "private_gb": round(mem.private / GB, 3), "working_gb": round(mem.rss / GB, 3),
                          "started": time.strftime("%Y-%m-%d %H:%M", time.localtime(proc.info["create_time"] or 0))})
        except (psutil.Error, OSError):
            pass
    vm = psutil.virtual_memory()
    used, limit = commit_gb()
    top = sorted(procs, key=lambda p: p["private_gb"], reverse=True)[:TOP]
    watched = [p for p in procs if p["watch"] and p["private_gb"] >= 0.05]
    keep = {p["pid"]: p for p in top + watched}
    return {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "boot": time.strftime("%Y-%m-%d %H:%M", time.localtime(psutil.boot_time())),
            "ram_total_gb": round(vm.total / GB, 1), "ram_available_gb": round(vm.available / GB, 2),
            "commit_used_gb": round(used, 2) if used else None, "commit_limit_gb": round(limit, 2) if limit else None,
            "processes": sorted(keep.values(), key=lambda p: p["private_gb"], reverse=True)}


def report(lines):
    if not lines:
        return "No samples yet."
    out = [f"{len(lines)} samples, {lines[0]['time']} to {lines[-1]['time']}.",
           f"Latest: {lines[-1]['ram_available_gb']} GB RAM available of {lines[-1]['ram_total_gb']}, "
           f"commit {lines[-1]['commit_used_gb']} of {lines[-1]['commit_limit_gb']} GB.", ""]
    runs = {}  # (label, pid) -> [(epoch, private_gb)]
    for line in lines:
        when = time.mktime(time.strptime(line["time"], "%Y-%m-%d %H:%M:%S"))
        for p in line["processes"]:
            if p["watch"]:
                runs.setdefault((p["watch"], p["pid"]), []).append((when, p["private_gb"], p["started"]))
    for (label, pid), points in sorted(runs.items()):
        first, last = points[0], points[-1]
        days = (last[0] - first[0]) / 86400
        rate = f"{(last[1] - first[1]) / days:+.2f} GB/day" if days >= 0.25 else "too soon to tell"
        out.append(f"{label:20} pid {pid:<6} started {first[2]}  {first[1]:6.2f} -> {last[1]:6.2f} GB  "
                   f"over {days:4.1f} days  ({rate})")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true", help="summarize the log instead of sampling")
    args = parser.parse_args()
    if args.report:
        lines = []
        if LOG.exists():
            for raw in LOG.read_text(encoding="utf-8").splitlines():
                try:
                    lines.append(json.loads(raw))
                except ValueError:
                    pass
        print(report(lines))
        return
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sample()) + "\n")


if __name__ == "__main__":
    sys.exit(main())
