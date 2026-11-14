"""The Jarvis desktop app: an orb in the corner of the screen, his own window, an icon by the clock and a hotkey.

    pythonw jarvis_app.py             the orb (or bring the running app forward)
    pythonw jarvis_app.py --window    open his full window
    pythonw jarvis_app.py --startup   what Windows runs at log-in: start Jarvis quietly, then the orb

The orb is his main face: it sits above the taskbar, grows while you talk to each other and shrinks when it's quiet.
His full window (the 3D model, the Console, the menus) opens from the orb, the tray icon or the "Jarvis CEO" shortcut,
and closing it puts him back in the corner. Ctrl+Alt+Space from anywhere opens the orb's ask box.

This is only the face. Jarvis himself (voice, wake word, tools) is jarvis.py and keeps running when the app is
closed; open_brain.py starts him if he isn't running. Both windows show the same local page as the browser
(brain.py, port 7781), in Edge WebView2. One app at a time: a second launch asks the first to show a window.
"""
import ctypes
import ctypes.wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
PYTHONW = ROOT / '.venv' / 'Scripts' / 'pythonw.exe'
PAGE = 'http://127.0.0.1:7781/'
STATE = ROOT / 'data' / 'app-state.json'
APP_ID = 'Jarvis.DesktopApp'
HOTKEY = 'Ctrl+Alt+Space'
SIZES = {'small': (250, 290), 'big': (380, 450)}
STARTUP_LINK = Path(os.environ.get('APPDATA', '')) / 'Microsoft/Windows/Start Menu/Programs/Startup/Jarvis.lnk'
START_MENU_LINK = Path(os.environ.get('APPDATA', '')) / 'Microsoft/Windows/Start Menu/Programs/Jarvis.lnk'


def launch(window=False):
    """Start the app (or poke the running one). Used by the page's "Desktop orb" menu item."""
    subprocess.Popen([str(PYTHONW), str(ROOT / 'jarvis_app.py')] + (['--window'] if window else []), cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    return {'status': 'launched'}


def _hud_port():
    from instance_config import HUD_PORT
    return HUD_PORT


def jarvis_settings(change=None):
    """Read (or change) Jarvis's settings straight from the assistant, the way the page does."""
    port = _hud_port()
    data = None if change is None else json.dumps(change).encode()
    request = urllib.request.Request(f'http://127.0.0.1:{port}/settings', data=data, method='POST' if data else 'GET',
                                     headers={'Content-Type': 'application/json', 'Host': f'127.0.0.1:{port}'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # this PC has a proxy set; never use it here
    with opener.open(request, timeout=5) as response:
        return json.loads(response.read())


def _read_state():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _write_state(**changes):
    state = {**_read_state(), **changes}
    try:
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    except OSError:
        pass


# ---------- Shortcuts: Start menu, log-in, the desktop ----------

def make_shortcut(path, args, description):
    import win32com.client
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    link = win32com.client.Dispatch('WScript.Shell').CreateShortcut(str(path))
    link.TargetPath = str(PYTHONW)
    link.Arguments = ' '.join([f'"{ROOT / "jarvis_app.py"}"', *args])
    link.WorkingDirectory = str(ROOT)
    link.IconLocation = str(ROOT / 'jarvis.ico') + ',0'
    link.Description = description
    link.Save()
    try:  # the same app id as the running windows, so a pinned taskbar icon and the open app are one button
        import pythoncom
        from win32com.propsys import propsys, pscon
        from win32com.shell import shellcon
        store = propsys.SHGetPropertyStoreFromParsingName(str(path), None, shellcon.GPS_READWRITE,
                                                          propsys.IID_IPropertyStore)
        store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
        store.Commit()
    except Exception:
        pass


def starts_with_windows():
    if not STARTUP_LINK.exists():
        return False
    try:
        import win32com.client
        return 'jarvis_app.py' in win32com.client.Dispatch('WScript.Shell').CreateShortcut(str(STARTUP_LINK)).Arguments
    except Exception:
        return False


def set_starts_with_windows(enabled):
    if enabled:
        make_shortcut(STARTUP_LINK, ['--startup'], 'Start Jarvis and his orb when you log in')
    elif STARTUP_LINK.exists():
        STARTUP_LINK.unlink()


def install_shortcuts():
    """Start menu entry, log-in entry, and the desktop's Jarvis CEO / Jarvis Orb shortcuts all open the app."""
    make_shortcut(START_MENU_LINK, ['--window'], 'Jarvis')
    set_starts_with_windows(True)
    import win32com.client
    shell = win32com.client.Dispatch('WScript.Shell')
    desktop = Path(shell.SpecialFolders('Desktop'))
    made = [str(START_MENU_LINK), str(STARTUP_LINK)]
    for name, args in (('Jarvis CEO.lnk', ['--window']), ('Jarvis Orb.lnk', [])):
        make_shortcut(desktop / name, args, 'Jarvis')
        made.append(str(desktop / name))
    return made


# ---------- The app ----------

class PageAPI:
    """What the orb page may call (window.pywebview.api.*). Kept apart from App: pywebview walks every public
    attribute of this object to expose it, and App's windows lead into .NET objects without end."""
    def __init__(self, app):
        self._app = app

    def open_window(self):
        return self._app.open_window()

    def hide_orb(self):
        return self._app.hide_orb()

    def set_size(self, size):
        return self._app.set_size(size)

    def save_position(self):
        return self._app.save_position()


class App:
    def __init__(self, webview):
        self.webview = webview
        self.orb = None
        self.main = None
        self.tray = None
        self.size = 'small'
        self.lock = threading.Lock()
        self.quitting = False
        self.placed = False

    # Called from the orb page (window.pywebview.api.*)
    def open_window(self):
        threading.Thread(target=self.show_main, daemon=True).start()
        return True

    def hide_orb(self):
        self._hide(self.orb)
        return True

    def set_size(self, size):
        if size not in SIZES or not self.orb:
            return False
        with self.lock:
            if size != self.size:
                from webview.window import FixPoint
                try:
                    self.orb.resize(*SIZES[size], fix_point=FixPoint.SOUTH | FixPoint.EAST)
                    self.size = size
                except Exception as exc:
                    print(f'(could not resize the orb: {exc!r})', flush=True)
        return True

    def save_position(self):
        try:
            import win32gui
            left, top, right, bottom = win32gui.GetWindowRect(self.orb.native.Handle.ToInt32())
            _write_state(orb_corner=[right, bottom])
        except Exception:
            pass
        return True

    def toggle_mute(self):
        try:
            return jarvis_settings({'mic_muted': not jarvis_settings().get('mic_muted', False)}).get('mic_muted')
        except Exception:
            return None

    # Windows
    def _hide(self, window):
        if window:
            try:
                window.evaluate_js('window.J && (J.paused = true)')
            except Exception:
                pass
            window.hide()

    def _show(self, window):
        window.show()
        try:
            window.evaluate_js('window.J && (J.paused = false)')
        except Exception:
            pass
        try:
            import win32gui
            win32gui.SetForegroundWindow(window.native.Handle.ToInt32())
        except Exception:
            pass

    def show_orb(self, ask=False):
        if self.main and self.main_visible():
            self._show(self.main)
            if ask:
                self.main.evaluate_js("document.getElementById('prompt')?.focus()")
            return
        self._show(self.orb)
        if not self.placed:  # it started hidden behind his window: Windows positions it on first show, then us
            self.orb.events.shown.wait(5)
            time.sleep(.2)
            self.place_orb()
        if ask:
            self.set_size('big')
            self.orb.evaluate_js('J.focusAsk && J.focusAsk()')

    def main_visible(self):
        try:
            import win32gui
            return bool(win32gui.IsWindowVisible(self.main.native.Handle.ToInt32()))
        except Exception:
            return False

    def show_main(self):
        with self.lock:
            if self.main is None:
                state = _read_state()
                width, height = state.get('window_size') or (1400, 880)
                self.main = self.webview.create_window('Jarvis', PAGE, width=width, height=height,
                                                       min_size=(900, 600), background_color='#050610',
                                                       maximized=bool(state.get('window_maximized')),
                                                       text_select=True)
                self.main.events.closing += self._main_closing
                created = True
            else:
                created = False
        if created:
            self.main.events.shown.wait(20)  # it shows itself; a handler on `shown` could be attached too late
        else:
            self._show(self.main)
        self._hide(self.orb)

    def _main_closing(self):
        if self.quitting:
            return True
        try:
            import win32gui
            hwnd = self.main.native.Handle.ToInt32()
            maximized = bool(win32gui.GetWindowPlacement(hwnd)[1] == 3)
            _write_state(window_maximized=maximized,
                         **({} if maximized else {'window_size': [self.main.width, self.main.height]}))
        except Exception:
            pass
        # Closing his window puts him back in the corner; the page stays loaded and paused. Done on another thread:
        # the window waits for this handler, so hiding it from here would deadlock.
        def back_to_corner():
            self._hide(self.main)
            self.show_orb()
        threading.Thread(target=back_to_corner, daemon=True).start()
        return False

    def place_orb(self):
        """Bottom-right, just above the taskbar, unless you dragged him somewhere else last time."""
        import win32api
        import win32con
        import win32gui
        hwnd = self.orb.native.Handle.ToInt32()
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)  # no taskbar button for the orb: that's his window's
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,
                               (style | win32con.WS_EX_TOOLWINDOW) & ~win32con.WS_EX_APPWINDOW)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        corner = _read_state().get('orb_corner')
        work = win32api.GetMonitorInfo(win32api.MonitorFromPoint(tuple(corner) if corner else (0, 0), 2))['Work']
        if corner and work[0] + width <= corner[0] <= work[2] and work[1] + height <= corner[1] <= work[3]:
            x, y = corner[0] - width, corner[1] - height
        else:
            x, y = work[2] - width - 16, work[3] - height - 16
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        self.placed = True

    def quit(self):
        self.quitting = True
        if self.tray:
            self.tray.stop()
        for window in list(self.webview.windows):
            window.destroy()

    # Tray icon
    def start_tray(self):
        import pystray
        from PIL import Image, ImageDraw

        base = Image.open(ROOT / 'jarvis.ico').convert('RGBA').resize((64, 64))
        muted_image = base.copy()
        draw = ImageDraw.Draw(muted_image)
        draw.ellipse((34, 34, 62, 62), fill=(220, 38, 38, 255))
        draw.line((40, 48, 56, 48), fill=(255, 255, 255, 255), width=5)
        state = {'muted': False, 'mode': 'wake'}

        def refresh():
            while not self.quitting:
                try:
                    current = jarvis_settings()
                    state.update(muted=bool(current.get('mic_muted')), mode=current.get('listening_mode', 'wake'))
                except Exception:
                    pass
                shown = state['muted']
                if self.tray and shown != state.get('shown'):
                    state['shown'] = shown
                    self.tray.icon = muted_image if shown else base
                    self.tray.title = 'Jarvis (microphone muted)' if shown else 'Jarvis'
                time.sleep(3)

        def mute(_icon, _item):
            result = self.toggle_mute()
            if result is not None:
                state.update(muted=result, shown=result)
                self.tray.icon = muted_image if result else base
                self.tray.title = 'Jarvis (microphone muted)' if result else 'Jarvis'

        def mode(value):
            def choose(_icon, _item):
                try:
                    state['mode'] = jarvis_settings({'listening_mode': value}).get('listening_mode', value)
                except Exception:
                    pass
            return choose

        def startup(_icon, _item):
            set_starts_with_windows(not starts_with_windows())

        def restart(_icon, _item):
            subprocess.Popen([str(PYTHONW), str(ROOT / 'scripts' / 'restart_jarvis.py')], cwd=ROOT,
                             creationflags=subprocess.CREATE_NO_WINDOW)

        item, Menu = pystray.MenuItem, pystray.Menu
        self.tray = pystray.Icon('Jarvis', base, 'Jarvis', menu=Menu(
            item('Open Jarvis', lambda *_: self.show_main(), default=True),
            item(f'Ask Jarvis  ({HOTKEY})', lambda *_: self.show_orb(ask=True)),
            item('Show the orb', lambda *_: self.show_orb()),
            Menu.SEPARATOR,
            item('Mute microphone', mute, checked=lambda _: state['muted']),
            item('Always listening', mode('continuous'), radio=True, checked=lambda _: state['mode'] == 'continuous'),
            item('Only when I say "Jarvis"', mode('wake'), radio=True, checked=lambda _: state['mode'] == 'wake'),
            Menu.SEPARATOR,
            item('Start with Windows', startup, checked=lambda _: starts_with_windows()),
            item('Restart Jarvis', restart),
            item('Close the app (Jarvis keeps running)', lambda *_: self.quit()),
        ))
        self.tray.run_detached()
        threading.Thread(target=refresh, daemon=True).start()

    # Ctrl+Alt+Space, and the second-launch signals
    def watch_hotkey(self):
        user32 = ctypes.windll.user32
        MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, WM_HOTKEY, VK_SPACE = 0x1, 0x2, 0x4000, 0x0312, 0x20
        if not user32.RegisterHotKey(None, 7, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, VK_SPACE):
            print(f'({HOTKEY} is taken by another app; use the tray icon instead)', flush=True)
            return
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and msg.wParam == 7:
                try:
                    self.show_orb(ask=True)
                except Exception as exc:
                    print(f'(hotkey failed: {exc!r})', flush=True)

    def watch_signals(self, events):
        import win32event
        handles = [events['orb'], events['window']]
        while not self.quitting:
            result = win32event.WaitForMultipleObjects(handles, False, 1000)
            if result == win32event.WAIT_OBJECT_0:
                self.show_orb()
            elif result == win32event.WAIT_OBJECT_0 + 1:
                self.show_main()


def signals(create):
    import win32event
    from instance_config import MUTEX_NAME
    make = (lambda name: win32event.CreateEvent(None, False, False, name)) if create else \
        (lambda name: win32event.OpenEvent(win32event.EVENT_MODIFY_STATE, False, name))
    return {kind: make(f'{MUTEX_NAME}_App_{kind}') for kind in ('orb', 'window')}


def main():
    import win32api
    import win32event
    import winerror
    from instance_config import MUTEX_NAME

    if '--install' in sys.argv:
        print('\n'.join(install_shortcuts()))
        return
    want_window = '--window' in sys.argv
    if sys.stdout is None:  # pythonw: keep what the app prints (a taken hotkey, a failed placement) in a log
        (ROOT / 'data').mkdir(exist_ok=True)
        sys.stdout = sys.stderr = open(ROOT / 'data' / 'app.log', 'a', encoding='utf-8', buffering=1)  # noqa: SIM115 - open for the app's life
        print(f'===== app started {time.strftime("%Y-%m-%d %H:%M:%S")} =====', flush=True)
    mutex = win32event.CreateMutex(None, False, MUTEX_NAME + '_App')  # noqa: F841 - held for the app's life
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        try:
            win32event.SetEvent(signals(create=False)['window' if want_window else 'orb'])
        except Exception:
            pass
        return
    events = signals(create=True)
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)  # his own taskbar button, not Python's

    # Jarvis himself and the page server; open_brain starts whichever isn't running and returns quickly
    subprocess.run([str(ROOT / '.venv/Scripts/python.exe'), str(ROOT / 'open_brain.py'), '--no-browser'],
                   cwd=ROOT, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW, check=False)

    import webview
    app = App(webview)
    app.orb = webview.create_window('Jarvis Orb', PAGE + '?compact=1', js_api=PageAPI(app), width=SIZES['small'][0],
                                    height=SIZES['small'][1], frameless=True, easy_drag=False, on_top=True,
                                    resizable=False, background_color='#050610', text_select=True,
                                    hidden=want_window)

    def started():
        if not want_window and app.orb.events.shown.wait(15):
            try:
                app.place_orb()
            except Exception as exc:
                print(f'(could not place the orb: {exc!r})', flush=True)
        app.start_tray()
        threading.Thread(target=app.watch_hotkey, daemon=True).start()
        threading.Thread(target=app.watch_signals, args=(events,), daemon=True).start()
        if want_window:
            app.show_main()

    webview.start(started, gui='edgechromium', private_mode=False, storage_path=str(ROOT / 'data/orb-webview'),
                  icon=str(ROOT / 'jarvis.ico'))
    app.quitting = True
    if app.tray:
        app.tray.stop()


if __name__ == '__main__':
    main()
