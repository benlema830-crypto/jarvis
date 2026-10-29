"""Find the last video in the user's YouTube watch history (includes phone/TV views).

Uses a dedicated Chrome profile signed into YouTube once via `python youtube_history.py login`,
read headlessly with Playwright so it never touches the user's main Chrome profile."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
import sys

import chrome_browser

PROFILE = Path(__file__).resolve().parent / "data" / "youtube-browser"
HISTORY = "https://www.youtube.com/feed/history"
SIGN_IN = "https://accounts.google.com/ServiceLogin?service=youtube&continue=" + HISTORY

# First regular video on the page (Shorts use /shorts/ links, so they're skipped).
_FIRST_VIDEO = """() => {
  for (const a of document.querySelectorAll('a[href*="/watch?v="]')) {
    const id = new URL(a.href).searchParams.get('v');
    const named = [...document.querySelectorAll(`a[href*="v=${id}"]`)]
      .map(x => (x.getAttribute('title') || x.textContent || '').trim()).find(Boolean);
    if (id) return {id, title: named || ''};
  }
  return null;
}"""


def login():
    """Open the dedicated profile (not automated) so the user can sign into YouTube once."""
    PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([chrome_browser.CHROME, f"--user-data-dir={PROFILE}", "--no-first-run",
                      "--no-default-browser-check", SIGN_IN])


def _fetch():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="chrome", headless=True)
        try:
            page = ctx.new_page()
            page.goto(HISTORY, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector('a[href*="/watch?v="]', timeout=15000)
            except Exception:
                if "accounts.google.com" in page.url or page.locator('a[href*="ServiceLogin"]').count():
                    raise PermissionError("not signed in")
                raise
            return page.evaluate(_FIRST_VIDEO)
        finally:
            ctx.close()


def last_video():
    """Return {'id', 'title', 'url'} for the most recent watched video."""
    if not PROFILE.exists():
        raise PermissionError("not signed in")
    # Playwright's sync API can't run on a thread that already has an asyncio loop.
    with ThreadPoolExecutor(1) as pool:
        video = pool.submit(_fetch).result(timeout=60)
    if not video:
        raise LookupError("watch history is empty")
    video["title"] = re.sub(r"^\(\d+\)\s*|\s*- YouTube$", "", video["title"])
    video["url"] = f"https://www.youtube.com/watch?v={video['id']}"
    return video


if __name__ == "__main__":
    if sys.argv[1:] == ["login"]:
        login()
    else:
        print(last_video())
