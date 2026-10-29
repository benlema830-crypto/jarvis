"""Native always-on-top orb hosting the same local Jarvis UI in Edge WebView2."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent


def launch():
    python = ROOT / '.venv' / 'Scripts' / 'pythonw.exe'
    subprocess.Popen([str(python), str(ROOT / 'desktop_orb.py')], cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    return {'status':'launched'}


class OrbAPI:
    def __init__(self):
        self._window = None
        self._compact = True
        self._position = None
        self._lock = threading.Lock()

    def set_compact(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Choose compact or expanded.')
        with self._lock:
            window = self._window
            if enabled != self._compact:
                if not enabled:
                    self._position = (window.x, window.y)
                    window.resize(1280, 820)
                    window.move(60, 60)
                else:
                    window.resize(360, 420)
                    if self._position:
                        window.move(*self._position)
                self._compact = enabled
            window.on_top = enabled
            window.evaluate_js('J.setCompact(' + ('true' if enabled else 'false') + ')')
            return {'compact': enabled, 'on_top': window.on_top}

    def close(self):
        self._window.destroy()


def main():
    import webview
    smoke = next((arg.split('=',1)[1] for arg in sys.argv if arg.startswith('--smoke-url=')), None)
    if smoke:
        parsed=urlparse(smoke)
        if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost'}:
            raise ValueError('Smoke tests only use a local fixture.')
        url=smoke
    else:
        import win32event, win32api, winerror, win32gui, win32con
        from instance_config import MUTEX_NAME
        mutex=win32event.CreateMutex(None,False,MUTEX_NAME+'_Orb')
        if win32api.GetLastError()==winerror.ERROR_ALREADY_EXISTS:
            handle=win32gui.FindWindow(None,'Jarvis Orb')
            if handle:
                win32gui.ShowWindow(handle,win32con.SW_RESTORE)
                try: win32gui.SetForegroundWindow(handle)
                except Exception: pass
            return
        subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'open_brain.py'),'--no-browser'],
                       cwd=ROOT,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
        url='http://127.0.0.1:7781/'
    api=OrbAPI()
    window=webview.create_window('Jarvis Orb',url+'?compact=1',js_api=api,width=360,height=420,
        frameless=True,easy_drag=False,on_top=True,resizable=True,min_size=(300,350),
        background_color='#050610',hidden=bool(smoke),text_select=True)
    api._window=window
    result={}
    def check():
        try:
            for _ in range(80):
                if window.evaluate_js('!!window.J?.holo && !!window.J?.setCompact'): break
                time.sleep(.1)
            api.set_compact(True)
            import win32gui, win32con
            hwnd=window.native.Handle.ToInt32()
            pinned=bool(win32gui.GetWindowLong(hwnd,win32con.GWL_EXSTYLE)&win32con.WS_EX_TOPMOST)
            compact=window.evaluate_js("document.body.classList.contains('compact-orb') && J.view.sphere.size > 0")
            api.set_compact(False)
            expanded=window.width>=1200 and not window.on_top
            api.set_compact(True)
            result.update(ok=bool(pinned and compact and expanded),native_topmost=pinned,compact=compact,expanded=expanded,
                          renderer=window.evaluate_js('J.holo.renderer'))
        except Exception as exc:
            result.update(ok=False,error=repr(exc))
        finally:
            (ROOT/'data/orb-native-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            window.destroy()
    if smoke:
        window.events.loaded += lambda: threading.Thread(target=check,daemon=True).start()
    webview.start(gui='edgechromium',private_mode=False,storage_path=str(ROOT/'data/orb-webview'),
                  icon=str(ROOT/'jarvis.ico'))
    if smoke and not result.get('ok'):
        raise SystemExit(1)


if __name__=='__main__':
    main()
