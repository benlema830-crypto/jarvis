"""The owner's Qwen voice clone, models and isolated environment, kept in models/qwen-voice."""
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import threading


def create():
    root = Path(__file__).resolve().parent / 'models' / 'qwen-voice'
    for relative in ('local_tts.py', 'tts_worker.py', '.tts-qwen/Scripts/python.exe',
                     'reference/voice.wav', 'reference/transcript.txt'):
        if not (root / relative).is_file():
            raise RuntimeError('The installed Qwen voice is missing: ' + relative)
    spec = importlib.util.spec_from_file_location('jarvis_installed_local_tts', root / 'local_tts.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class FastQwen(module.LocalTTS):
        def _start(self):
            env = os.environ.copy()
            for key in list(env):
                if any(part in key.upper() for part in ('API_KEY', 'TOKEN', 'SECRET')):
                    env.pop(key)
            worker = Path(__file__).with_name('qwen_fast_worker.py')
            with open(root / 'data/qwen-fast-worker.log', 'a', encoding='utf-8') as log:
                proc = subprocess.Popen(
                    [str(root / '.tts-qwen/Scripts/python.exe'), '-u', str(worker)],
                    cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=log, text=True, encoding='utf-8',
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            messages = queue.Queue()
            def read():
                try:
                    for line in proc.stdout:
                        try:
                            messages.put(json.loads(line))
                        except ValueError:
                            pass
                finally:
                    messages.put({'error': 'Qwen worker exited; see qwen-fast-worker.log.'})
            threading.Thread(target=read, daemon=True).start()
            self._process, self._messages = proc, messages
            return proc, messages
    return FastQwen('qwen')
