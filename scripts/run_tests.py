"""Run the unit tests and prove they left the owner's real data alone.

    .venv\\Scripts\\python.exe scripts\\run_tests.py [unittest arguments]

Hashes the state and credential files in data/ before and after. A changed file fails the run, even when
every test passed: a test that writes to data/ can overwrite saved sessions or sign-ins (it happened on
2026-11-04). Files the running Jarvis writes all day (logs, metrics, activity) are not counted.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WATCHED = ("*.json", "*.enc", "*.dpapi", "*.epoch", "*.npz", "*.sqlite3")
# Written by the live assistant whether or not tests run.
LIVE = {"presence-greetings.json", "morning-wakeup.json", "vault-vectors.sqlite3", "cc_pending.json"}


def snapshot():
    found = {}
    for pattern in WATCHED:
        for path in DATA.glob(pattern):
            if path.name not in LIVE:
                try:
                    found[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    found[path.name] = "unreadable"
    return found


def main():
    before = snapshot()
    arguments = sys.argv[1:] or ["discover", "-s", "tests"]
    code = subprocess.call([sys.executable, "-m", "unittest", *arguments], cwd=ROOT)
    after = snapshot()
    changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    if changed:
        print("\nDATA CHANGED DURING THE TEST RUN: " + ", ".join(changed), file=sys.stderr)
        print("If Jarvis was in use at that moment it may be his doing; otherwise a test wrote to real data.",
              file=sys.stderr)
        return code or 2
    print(f"\ndata/ untouched ({len(before)} files checked).")
    return code


if __name__ == "__main__":
    sys.exit(main())
