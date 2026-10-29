"""Connect Jarvis to Gmail, read-only. Run: .venv\\Scripts\\python.exe scripts\\setup_gmail.py <client_secret.json>
Sign in again later (Google expires Testing-mode sign-ins weekly): setup_gmail.py --renew

The JSON is the "Desktop app" OAuth client downloaded from your own Google Cloud project with the
Gmail API enabled (see docs/GMAIL.md). Your browser opens Google's sign-in; you approve read-only
access there. Tokens are encrypted with Windows DPAPI in data/gmail.enc. Nothing secret is printed.
"""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gmail
import mcp_oauth


def client(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        info = data.get("installed") or {}
        client_id, client_secret = info["client_id"], info["client_secret"]
    except (OSError, ValueError, KeyError, AttributeError):
        raise gmail.GmailError("That isn't a Desktop-app OAuth client file. In Google Cloud, create an OAuth "
                               "client of type Desktop app and download its JSON.") from None
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise gmail.GmailError("That client file doesn't hold a Google OAuth client id.")
    return client_id, client_secret


def authorize(client_id, client_secret):
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    done, result = threading.Event(), {}
    deadline = time.monotonic() + 300

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            valid = (parsed.path == "/" and not done.is_set() and time.monotonic() < deadline
                     and len(query.get("state", [])) == 1 and secrets.compare_digest(query["state"][0], state))
            if valid:
                if len(query.get("code", [])) == 1 and "error" not in query:
                    result["code"] = query["code"][0]
                    result["scope"] = query.get("scope", [""])[0]
                done.set()
            body = b"Jarvis got the answer. You can close this tab." if valid else b"Not a Jarvis sign-in."
            self.send_response(200 if valid else 400)
            for key, value in (("Content-Type", "text/plain"), ("Cache-Control", "no-store"),
                               ("Referrer-Policy", "no-referrer"), ("Content-Length", str(len(body)))):
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Callback)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = gmail.AUTH_URL + "?" + urlencode({
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect, "scope": gmail.SCOPE,
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            "access_type": "offline", "prompt": "consent"})
        print("Opening Google sign-in in your browser. Approve read-only Gmail access there (up to 5 minutes).")
        webbrowser.open(url)
        done.wait(300)
        if "code" not in result:
            raise gmail.GmailError("Sign-in was cancelled, denied or timed out. Nothing was saved.")
        if gmail.SCOPE not in result.get("scope", "").split():
            raise gmail.GmailError("Google didn't grant Gmail read access (the box may have been unticked). Nothing was saved.")
        tokens = mcp_oauth.request("POST", gmail.TOKEN_URL, data={
            "grant_type": "authorization_code", "code": result.pop("code"), "redirect_uri": redirect,
            "client_id": client_id, "client_secret": client_secret, "code_verifier": verifier})
        value = mcp_oauth.token_result(tokens)
        if not value["refresh_token"]:
            raise gmail.GmailError("Google didn't return a refresh token. Nothing was saved.")
        return dict(value, client_id=client_id, client_secret=client_secret)
    finally:
        server.shutdown()
        worker.join(timeout=2)


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        if argv[0] == "--renew":  # weekly re-sign-in: reuse the client saved (encrypted) at setup
            saved = gmail.load_credentials()
            value = authorize(saved["client_id"], saved["client_secret"])
        else:
            value = authorize(*client(argv[0]))
        gmail.save_credentials(value)
        profile = gmail.api("/profile")
        print(f"Connected read-only to {profile.get('emailAddress', 'your Gmail')} "
              f"({profile.get('messagesTotal', '?')} messages). You can delete the client JSON file now.")
        return 0
    except (gmail.GmailError, mcp_oauth.OAuthError) as error:
        print(f"Gmail setup failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
