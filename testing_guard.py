"""One answer to "is this a test run?", so test activity never lands in the owner's real records.

Timing logs, task records and transcripts each skip their real file during tests. They used to recognise only
`python -m unittest`; any other runner (a debugger, a script that loads the suite itself) slipped through and
wrote fake turns into data/ (2026-11-10). A loaded test module is the giveaway whatever started the run.
"""
import os
import sys


def under_test() -> bool:
    if os.environ.get("JARVIS_UNDER_TEST"):
        return True
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    if (spec and spec.name.startswith("unittest")) or "pytest" in sys.modules:
        return True
    return any(name.startswith("test_") or name.startswith("tests.") for name in list(sys.modules))
