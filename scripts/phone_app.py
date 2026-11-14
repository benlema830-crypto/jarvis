"""Put the Jarvis app on your iPhone: shows a QR code on this PC that opens the app already connected.

    .venv\\Scripts\\python.exe scripts\\phone_app.py

Scan it with the iPhone camera (Tailscale on), tap the link, then Share > Add to Home Screen. The phone key rides
after the # in the link, which the browser never sends anywhere; the QR picture is deleted after two minutes.
Uses the key you already have (scripts/setup_phone.py makes a new one), so the Siri Shortcut keeps working.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import phone_bridge  # noqa: E402

QR = ROOT / "data" / "phone-app-qr.png"


def address() -> str:
    """The PC's tailnet name, as `tailscale serve` publishes the phone page."""
    try:
        status = json.loads(subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True,
                                           timeout=15, creationflags=subprocess.CREATE_NO_WINDOW).stdout)
        name = status["Self"]["DNSName"].rstrip(".")
        if name:
            return "https://" + name
    except Exception:
        pass
    return "https://draco420.tailf4c37e.ts.net"


def main():
    import segno
    token = phone_bridge.load_token()
    if not token:
        sys.exit("No phone key yet: run scripts\\setup_phone.py first.")
    link = f"{address()}/#key={token}"
    QR.parent.mkdir(exist_ok=True)
    segno.make(link, error="m").save(str(QR), scale=12, border=3, dark="#04201b", light="#ffffff")
    os.startfile(QR)  # noqa: S606 - opens the picture in the Windows Photos app
    print("Scan the QR code on your screen with the iPhone camera, open the link, then Share > Add to Home Screen.")
    print("The picture is deleted in two minutes.")
    time.sleep(120)
    QR.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
