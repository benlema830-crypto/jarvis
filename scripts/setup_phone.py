"""One-time iPhone setup: make the phone key (DPAPI-encrypted) and lock it to your Tailscale login.

Run (again any time to replace the key; the old one stops working after a JARVIS restart):
    .venv\\Scripts\\python.exe scripts\\setup_phone.py [your-tailscale-login@example.com]
Then publish the page to your tailnet only (never `tailscale funnel`):
    tailscale serve --bg 7782
Restart JARVIS so he starts the phone bridge.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import phone_bridge  # noqa: E402
import preferences  # noqa: E402


def main():
    login = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""
    if login:
        preferences.update(phone_tailscale_login=login)
    token = phone_bridge.new_token()
    print("Phone key (paste it into the JARVIS page and the Siri Shortcut; it isn't shown again):\n")
    print("    " + token + "\n")
    print(f"Only Tailscale login {login} may use it." if login else
          "Tip: rerun with your Tailscale login email to refuse everyone else on the tailnet.")


if __name__ == "__main__":
    main()
