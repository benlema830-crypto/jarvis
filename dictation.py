"""Dictation: Ctrl+Alt+D, speak, and your words are typed into whatever app has focus.

The phrase is recognised by the same local Whisper model and voice lock as commands;
it never goes to the AI. Typing uses a clipboard paste (fast, handles any characters),
then puts your previous clipboard text back. Work apps stay off-limits.
"""
import time

import pyperclip
import win32api
import win32con

import worksafe


def type_into_focus(text: str) -> str:
    text = text.strip()
    if not text:
        return "Nothing to type."
    if worksafe.foreground_blocked():
        return f"{worksafe.blocked_apps()} is in front; I don't type into work apps."
    try:
        previous = pyperclip.paste()
    except pyperclip.PyperclipException:
        previous = None
    pyperclip.copy(text + " ")
    for key, flags in ((win32con.VK_CONTROL, 0), (ord("V"), 0), (ord("V"), win32con.KEYEVENTF_KEYUP),
                       (win32con.VK_CONTROL, win32con.KEYEVENTF_KEYUP)):
        win32api.keybd_event(key, 0, flags, 0)
    time.sleep(0.35)  # let the target app read the clipboard before restoring it
    if previous is not None:
        pyperclip.copy(previous)
    return "Typed."
