"""Phone app notifications: Web Push to the Jarvis app on the owner's iPhone home screen.

The phone app (hud/phone.html installed with "Add to Home Screen", iOS 16.4 or later) subscribes once, after the
owner taps "Turn on alerts". Jarvis then sends:
  * a yes/no question while the owner is out of the room (instead of the Telegram text, when the app is set up);
  * a phone request's answer that came after the phone had stopped waiting.

How it travels: the message is encrypted on this PC for that phone alone (RFC 8291) and handed to Apple's push
service, which can't read it; the phone shows it. The signing key (VAPID) is made here once and kept with DPAPI,
so only this Windows account can use it. Subscriptions are in data/phone-push.json; one the phone has dropped
(404/410) is removed the first time a send finds it gone.
"""
import base64
import json
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY_STORE = ROOT / "data" / "phone-vapid.dpapi"
SUBSCRIPTIONS = DEFAULT_SUBSCRIPTIONS = ROOT / "data" / "phone-push.json"
SUBJECT = "https://draco420.tailf4c37e.ts.net"  # the app's own address: Apple needs a contact, and no email is shared
MAX_SUBSCRIPTIONS = 5
_lock = threading.Lock()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _vapid():
    import win32crypt
    from py_vapid import Vapid02
    with _lock:
        if KEY_STORE.is_file():
            pem = win32crypt.CryptUnprotectData(KEY_STORE.read_bytes(), None, None, None, 0)[1]
            return Vapid02.from_pem(pem)
        vapid = Vapid02()
        vapid.generate_keys()
        KEY_STORE.parent.mkdir(exist_ok=True)
        KEY_STORE.write_bytes(win32crypt.CryptProtectData(vapid.private_pem(), "JARVIS phone alerts", None, None, None, 0))
        return vapid


def public_key() -> str:
    """The key the phone needs to subscribe (applicationServerKey), base64url."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return _b64url(_vapid().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))


def _real_list_under_test() -> bool:
    """A test run never reads or changes the real list, so it can't buzz the owner's phone."""
    import testing_guard
    return SUBSCRIPTIONS == DEFAULT_SUBSCRIPTIONS and testing_guard.under_test()


def _load() -> list[dict]:
    if _real_list_under_test():
        return []
    try:
        value = json.loads(SUBSCRIPTIONS.read_text(encoding="utf-8"))
        return [s for s in value if isinstance(s, dict)] if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def _save(subs):
    if _real_list_under_test():
        return
    SUBSCRIPTIONS.parent.mkdir(exist_ok=True)
    temp = SUBSCRIPTIONS.with_suffix(".tmp")
    temp.write_text(json.dumps(subs, indent=2), encoding="utf-8")
    temp.replace(SUBSCRIPTIONS)


def valid(sub) -> bool:
    keys = sub.get("keys") if isinstance(sub, dict) else None
    endpoint = sub.get("endpoint") if isinstance(sub, dict) else None
    return (isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) < 1000
            and isinstance(keys, dict) and all(isinstance(keys.get(k), str) and 0 < len(keys[k]) < 200
                                                for k in ("p256dh", "auth")))


def subscribe(sub) -> bool:
    if not valid(sub):
        return False
    entry = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]},
             "added": time.time()}
    with _lock:
        subs = [s for s in _load() if s.get("endpoint") != entry["endpoint"]]
        _save((subs + [entry])[-MAX_SUBSCRIPTIONS:])
    return True


def unsubscribe(endpoint) -> bool:
    with _lock:
        subs = _load()
        kept = [s for s in subs if s.get("endpoint") != endpoint]
        if len(kept) != len(subs):
            _save(kept)
    return len(kept) != len(subs)


def ready() -> bool:
    """True when at least one phone has alerts turned on."""
    return bool(_load())


def send(title: str, body: str, *, tag: str = "jarvis", kind: str = "message") -> int:
    """Notify every subscribed phone. Returns how many took it; never raises."""
    import privacy
    from pywebpush import WebPushException, webpush
    subs = _load()
    if not subs:
        return 0
    payload = json.dumps({"title": title[:80], "body": privacy.redact(body)[:900], "tag": tag, "kind": kind})
    try:
        vapid = _vapid()
    except Exception as exc:
        print(f"(phone alerts: no signing key: {exc!r})", flush=True)
        return 0
    sent, gone = 0, []
    for sub in subs:
        try:
            webpush({"endpoint": sub["endpoint"], "keys": sub["keys"]}, payload, vapid_private_key=vapid,
                    vapid_claims={"sub": SUBJECT}, ttl=600, timeout=10, headers={"Urgency": "high"})
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                gone.append(sub["endpoint"])
            print(f"(phone alert not delivered: {status or exc!r})", flush=True)
        except Exception as exc:
            print(f"(phone alert not delivered: {exc!r})", flush=True)
    for endpoint in gone:
        unsubscribe(endpoint)
    return sent
