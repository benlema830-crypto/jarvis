"""Make, or repair, the Linux sandbox that Claude agents use for away jobs (see wsl_sandbox.py).

Run (again any time; every step is safe to repeat):
    .venv\\Scripts\\python.exe scripts\\setup_wsl_sandbox.py

Two steps are the owner's, because they need an administrator or a sign-in:
  - Installing WSL itself, once, in an administrator terminal, then a restart:
        wsl --install --no-distribution
  - Signing Claude Code inside the sandbox in to the Claude plan, once, in an ordinary terminal:
        wsl -d JarvisSandbox -e /home/agent/.local/bin/claude auth login --claudeai
    It prints a link (the sandbox can't open a browser); sign in there and paste the code back.

To remove the sandbox entirely: wsl --unregister JarvisSandbox
"""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import wsl_sandbox  # noqa: E402

IMAGE = "Ubuntu-24.04"
WSLCONFIG = Path.home() / ".wslconfig"
# The whole VM, not just this distro: small enough to sit beside the voice models, and nothing drawn on screen.
LIMITS = ("# Written by Jarvis (scripts/setup_wsl_sandbox.py): keep the agent sandbox small.\n"
          "[wsl2]\nmemory=4GB\nswap=2GB\nguiApplications=false\n")
INSTALL_CLAUDE = "set -e\ncd ~\ncurl -fsSL https://claude.ai/install.sh | bash\n"


def wsl(*args, timeout=900, quiet=False):
    return subprocess.run([shutil.which("wsl.exe"), *args], env=wsl_sandbox._env(), timeout=timeout,
                          capture_output=quiet).returncode


def main():
    if not shutil.which("wsl.exe") or wsl("--status", quiet=True) != 0:
        print("WSL isn't installed. In an administrator terminal run:  wsl --install --no-distribution\n"
              "then restart the PC and run this again.")
        return 1
    if wsl_sandbox.DISTRO not in wsl_sandbox.distros():
        print(f"Creating {wsl_sandbox.DISTRO} from {IMAGE}...")
        if wsl("--install", IMAGE, "--name", wsl_sandbox.DISTRO, "--no-launch") != 0:
            print("Couldn't create it.")
            return 1
    print("Locking it down and installing what the sandbox needs...")
    code, output = wsl_sandbox.run("/bin/bash", "-s", root=True, timeout=900,
                                   text_in=(wsl_sandbox.FILES / "provision.sh").read_text(encoding="utf-8"))
    if code != 0:
        print(f"Provisioning failed:\n{output[-1500:]}")
        return 1
    failed = wsl_sandbox.sync()
    if failed:
        print(failed)
        return 1
    if WSLCONFIG.exists():
        print(f"{WSLCONFIG} already exists; left as it is. The sandbox is meant to run with about 4 GB of memory.")
    else:
        WSLCONFIG.write_text(LIMITS, encoding="utf-8")
        wsl("--shutdown", quiet=True)  # the limits apply to the VM's next start
    wsl_sandbox.stop()  # its lockdown (no drives, no Windows programs) applies from the distro's next start
    code, _ = wsl_sandbox.run("/usr/bin/test", "-x", wsl_sandbox.CLAUDE)
    if code != 0:
        print("Installing Claude Code inside it...")
        code, output = wsl_sandbox.run("/bin/bash", "-s", text_in=INSTALL_CLAUDE, timeout=900)
        if code != 0:
            print(f"Couldn't install Claude Code:\n{output[-1500:]}")
            return 1
    problem = wsl_sandbox.problem()
    wsl_sandbox.stop()
    if problem:
        print(f"Not ready yet: {problem}")
        return 1
    print("The sandbox is ready: Fable away jobs will run inside it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
