"""Real Tk button integration check; synthetic ID, no real browser or credentials."""
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import setup_spotify as setup


def main():
    root = tk.Tk()
    root.withdraw()
    failures = []

    def exercise():
        try:
            dialog = next(w for w in root.winfo_children() if isinstance(w, setup.ClientIdDialog))
            def descendants(parent):
                for child in parent.winfo_children():
                    yield child
                    yield from descendants(child)
            buttons = {w.cget('text'): w for w in descendants(dialog) if isinstance(w, tk.Button)}
            assert {'Open developer dashboard', 'Open Spotify sign-in', 'Cancel'} <= buttons.keys()
            buttons['Open developer dashboard'].invoke()
            launch.assert_called_once_with(setup.DASHBOARD)
            assert dialog.winfo_exists()
            buttons['Open Spotify sign-in'].invoke()  # empty ID must keep dialog open
            assert dialog.winfo_exists()
            assert errors.call_count == 1
            dialog.entry.insert(0, 'a' * 32)
            buttons['Open Spotify sign-in'].invoke()  # callback not confirmed
            assert dialog.winfo_exists()
            assert errors.call_count == 2
            dialog.ready.set(True)
            buttons['Open Spotify sign-in'].invoke()
        except Exception as error:
            failures.append(type(error).__name__)
            for window in root.winfo_children():
                window.destroy()

    try:
        with patch.object(setup.webbrowser, 'open', return_value=True) as launch, \
                patch.object(setup.messagebox, 'showerror') as errors:
            root.after(250, exercise)
            root.after(5000, lambda: [w.destroy() for w in root.winfo_children()])
            dialog = setup.ClientIdDialog(root, 'JARVIS Spotify - synthetic UI check')
            assert not failures, 'UI handler check failed.'
            assert dialog.result == 'a' * 32, 'Sign-in button did not return the validated local ID.'
            launch.assert_called_once_with(setup.DASHBOARD)
        print('PASS: real Tk dashboard and sign-in buttons, missing ID, callback confirmation, and valid submission. No real browser or account used.')
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
