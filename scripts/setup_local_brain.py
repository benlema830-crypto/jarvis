"""Install an isolated, pinned Ollama runtime and local model; no account needed.

Default: download, verify, install, run a synthetic inference check, stop server.
--serve: start the installed runtime on 127.0.0.1:11435 with cloud disabled.
Does not change Jarvis preferences, .env, PATH, startup tasks, or Python packages.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import zipfile

import requests

ROOT = Path(__file__).resolve().parents[1]
HOME_DIR = ROOT / 'data' / 'local-brain'
VERSION = 'v0.40.7'
ARCHIVE_SHA256 = 'e6527768c53e85ec4596495fb0f035ef07f437b4b591ebc3581684699a4668f4'
URL = f'https://github.com/ollama/ollama/releases/download/{VERSION}/ollama-windows-amd64.zip'
MODEL = 'qwen3:4b'
PORT = 11435
BASE = f'http://127.0.0.1:{PORT}'


def port_open():
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(('127.0.0.1', PORT)) == 0


def start():
    binary = HOME_DIR / 'runtime' / 'ollama.exe'
    if not binary.is_file():
        raise RuntimeError('Run setup_local_brain.py first.')
    if port_open():
        raise RuntimeError('Port 11435 is already in use. Existing service was left alone.')
    env = dict(os.environ, OLLAMA_HOST=f'127.0.0.1:{PORT}', OLLAMA_MODELS=str(HOME_DIR / 'models'),
               OLLAMA_NO_CLOUD='1', OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1',
               OLLAMA_KEEP_ALIVE='2m', OLLAMA_CONTEXT_LENGTH='8192')
    with (HOME_DIR / 'server.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen([str(binary), 'serve'], cwd=HOME_DIR, env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Ollama exited during startup; see data/local-brain/server.log.')
        if port_open():
            return process
        time.sleep(.1)
    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError('Local model server did not start.')


def install():
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    archive = HOME_DIR / f'ollama-{VERSION}.zip'
    if not archive.is_file():
        print('Downloading pinned Ollama runtime (about 1.6 GB)...', flush=True)
        partial = archive.with_suffix('.partial')
        with requests.get(URL, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            size, progress = 0, -1
            with partial.open('wb') as output:
                for chunk in response.iter_content(1024 * 1024):
                    output.write(chunk)
                    size += len(chunk)
                    step = size // (250 * 1024 * 1024)
                    if step != progress:
                        print(f'Downloaded {size // (1024 * 1024)} MiB', flush=True)
                        progress = step
        partial.replace(archive)
    with archive.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    if digest != ARCHIVE_SHA256:
        raise RuntimeError('Ollama archive checksum mismatch. Installation stopped.')
    runtime = HOME_DIR / 'runtime'
    marker = runtime / '.verified-version'
    if not marker.is_file() or marker.read_text() != VERSION:
        print('Checksum verified. Extracting runtime...', flush=True)
        runtime.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                if not (runtime / entry.filename).resolve().is_relative_to(runtime.resolve()):
                    raise RuntimeError('Archive path escapes the runtime directory.')
            bundle.extractall(runtime)
        marker.write_text(VERSION)
    process = start()
    try:
        print('Downloading local qwen3:4b weights (about 2.5 GB)...', flush=True)
        with requests.Session() as session:
            session.trust_env = False
            with session.post(BASE + '/api/pull', json={'model': MODEL}, stream=True, timeout=(5, 120)) as response:
                response.raise_for_status()
                previous = None
                for line in response.iter_lines():
                    if not line:
                        continue
                    item = json.loads(line)
                    if item.get('error'):
                        raise RuntimeError('Local model download failed; rerun setup to resume.')
                    step = int(item.get('completed', 0) * 10 / max(item.get('total', 1), 1))
                    status = (item.get('status'), step)
                    if status != previous:
                        print(f'{status[0]} {step * 10}%', flush=True)
                        previous = status
        print('Checking local inference with a synthetic prompt...', flush=True)
        os.environ['JARVIS_OLLAMA_ENABLED'] = '1'
        os.environ['JARVIS_OLLAMA_URL'] = BASE
        sys.path.insert(0, str(ROOT))
        import ollama_brain
        began = time.monotonic()
        ollama_brain.validate(MODEL)
        report = {'runtime_version': VERSION, 'archive_sha256': digest, 'model': MODEL,
                  'validation': 'passed', 'validation_seconds': round(time.monotonic() - began, 2),
                  'cloud_disabled': True, 'selected_in_jarvis': False}
        (HOME_DIR / 'setup-result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    finally:
        # Stop only the child created here. Unload the test model first.
        try:
            requests.post(BASE + '/api/generate', json={'model': MODEL, 'keep_alive': 0}, timeout=10)
        except requests.RequestException:
            pass
        process.terminate()
        process.wait(timeout=15)


if __name__ == '__main__':
    if '--serve' in sys.argv:
        if port_open():
            print('A service already uses port 11435; no duplicate started.')
        else:
            child = start()
            print(f'Local model server started (PID {child.pid}); cloud disabled. No model loaded until requested.')
    else:
        install()
