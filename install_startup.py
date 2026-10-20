"""Make Jarvis start when you log in to Windows.

    .venv\\Scripts\\python.exe install_startup.py            add to startup
    .venv\\Scripts\\python.exe install_startup.py --remove   remove from startup
"""

import os
import sys

import win32com.client

HERE = os.path.dirname(os.path.abspath(__file__))
STARTUP = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
SHORTCUT = os.path.join(STARTUP, "Jarvis.lnk")

if "--remove" in sys.argv:
    if os.path.exists(SHORTCUT):
        os.remove(SHORTCUT)
    print("Jarvis removed from startup.")
else:
    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(SHORTCUT)
    link.TargetPath = os.path.join(HERE, "run.bat")
    link.WorkingDirectory = HERE
    link.WindowStyle = 7  # start minimized
    link.IconLocation = os.path.join(HERE, "jarvis.ico") + ",0"
    link.Description = "JARVIS assistant"
    link.Save()
    print(f"Jarvis will start when you log in. Shortcut: {SHORTCUT}")
