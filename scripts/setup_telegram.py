"""One-time Telegram setup: save your bot token (masked, DPAPI-encrypted) and pair your chat.

Before running: in Telegram, message @BotFather, send /newbot, pick a name, and copy the
token it gives you. Then run (with JARVIS running or not):
    .venv\\Scripts\\python.exe scripts\\setup_telegram.py
Restart JARVIS afterwards so he starts listening to the bot.
"""
from pathlib import Path
import secrets
import sys
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import preferences  # noqa: E402
import telegram_bridge as tb  # noqa: E402

PAIR_SECONDS = 300


def main():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    token = simpledialog.askstring(
        "JARVIS - Telegram bot token",
        "Paste the bot token from @BotFather.\n\nIt is encrypted for your Windows account and never shown again.",
        show="*", parent=root)
    if not token:
        return
    try:
        bot = tb.call(token.strip(), "getMe", timeout=20)
    except (requests.RequestException, RuntimeError, ValueError):
        messagebox.showerror("JARVIS", "Telegram didn't accept that token. Nothing was saved.", parent=root)
        return
    tb.save_token(token)
    code = f"{secrets.randbelow(900000) + 100000}"
    messagebox.showinfo(
        "JARVIS - pair your chat",
        f"Token saved for @{bot.get('username')}.\n\nNow open Telegram, find @{bot.get('username')}, "
        f"and send it this message within 5 minutes:\n\n/pair {code}\n\nClick OK, then send it.", parent=root)
    print(f"Waiting for '/pair {code}' sent to @{bot.get('username')} ...", flush=True)
    offset, deadline = None, time.time() + PAIR_SECONDS
    while time.time() < deadline:
        try:
            params = {"timeout": 20, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            updates = tb.call(token.strip(), "getUpdates", timeout=30, **params)
        except (requests.RequestException, RuntimeError):
            time.sleep(3)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            if (message.get("text") or "").strip() in (f"/pair {code}", code):
                chat = message["chat"]["id"]
                preferences.update(telegram_chat_id=chat)
                # Acknowledge everything so JARVIS doesn't replay the pairing message later.
                tb.call(token.strip(), "getUpdates", timeout=10, offset=offset, limit=1)
                tb.call(token.strip(), "sendMessage", chat_id=chat,
                        text="Paired. Restart JARVIS and you can message me here, by text or voice note.")
                messagebox.showinfo("JARVIS", "Paired! Restart JARVIS to start using Telegram.", parent=root)
                return
    messagebox.showwarning("JARVIS", "No pairing message arrived. Run this again to retry; the token stays saved.",
                           parent=root)


if __name__ == "__main__":
    main()
