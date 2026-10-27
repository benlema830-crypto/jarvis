"""What orbits Jarvis's hologram: the next calendar events and the song playing on Spotify.

Both are read-only and cached, so the Brain page can poll every few seconds without hitting the
calendar feed or Spotify's API on each request. Anything unavailable is simply left out."""
import datetime
import threading
import time

EVENTS_TTL = 300  # calendar feeds change rarely and are slow to fetch
TRACK_TTL = 4
_lock = threading.Lock()
_cache = {"events": (0.0, []), "track": (0.0, None)}


def _events():
    import context
    if not context.calendar_urls():
        return []
    now = datetime.datetime.now().astimezone()
    soon = [e for e in context.event_list(1) if e["start"] - now < datetime.timedelta(hours=24)]
    return [{"title": e["title"][:80], "location": e["location"][:80], "all_day": e["all_day"],
             "start": e["start"].isoformat()} for e in soon[:4]]


def _track():
    import music
    import spotify_mcp
    if not music.configured():
        return None
    data = spotify_mcp.api("GET", "/me/player/currently-playing")
    item = data.get("item") if isinstance(data, dict) else None
    if not isinstance(item, dict) or item.get("type") != "track":
        return None
    images = [i for i in item.get("album", {}).get("images", []) if isinstance(i, dict) and i.get("url")]
    art = min(images, key=lambda i: abs((i.get("width") or 300) - 300))["url"] if images else ""
    return {"name": str(item.get("name", ""))[:120], "artists": [str(a.get("name", ""))[:80] for a in item.get("artists", [])][:4],
            "album": str(item.get("album", {}).get("name", ""))[:120], "art": art if art.startswith("https://i.scdn.co/") else "",
            "uri": str(item.get("uri", "")), "playing": bool(data.get("is_playing")),
            "progress_ms": int(data.get("progress_ms") or 0), "duration_ms": int(item.get("duration_ms") or 0)}


def _cached(key, ttl, fetch):
    with _lock:
        fetched, value = _cache[key]
        if time.monotonic() - fetched < ttl:
            return value
    try:
        value = fetch()
    except Exception:
        value = None if key == "track" else []
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def snapshot():
    return {"events": _cached("events", EVENTS_TTL, _events), "track": _cached("track", TRACK_TTL, _track)}
