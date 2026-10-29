"""Importing this makes webbrowser.open() use Chrome instead of the Windows default (Edge)."""
import os
import shutil
import webbrowser

CHROME = shutil.which("chrome") or next((path for path in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
) if os.path.isfile(path)), None)

if CHROME:
    webbrowser.register("chrome", None, webbrowser.BackgroundBrowser(CHROME), preferred=True)
