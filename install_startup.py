"""Make Jarvis (and his desktop app) start when you log in to Windows.

    .venv\\Scripts\\python.exe install_startup.py            add to startup
    .venv\\Scripts\\python.exe install_startup.py --remove   remove from startup

The app's tray menu has the same switch ("Start with Windows"). `jarvis_app.py --install` also adds the
Start menu entry and points the desktop shortcuts at the app.
"""
import sys

import jarvis_app

if "--remove" in sys.argv:
    jarvis_app.set_starts_with_windows(False)
    print("Jarvis removed from startup.")
else:
    jarvis_app.set_starts_with_windows(True)
    print(f"Jarvis will start when you log in. Shortcut: {jarvis_app.STARTUP_LINK}")
