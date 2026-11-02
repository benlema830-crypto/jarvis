"""Loopback-only Clip Studio. Uses the existing CLI in an isolated worker."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
import uuid
import webbrowser

from vod_download import validate_url

ROOT = Path(__file__).resolve().parent
VIDEO_EXTS = {'.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v'}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def contained(root, path):
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('File is outside the studio workspace.')
    return resolved


def cached_models():
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        cache = Path(HF_HUB_CACHE)
    except ImportError:
        cache = Path.home() / '.cache/huggingface/hub'
    result = [{'name': p.parts[-4].replace('models--', '').replace('--', '/'), 'path': str(p.parent)}
              for p in cache.glob('models--*whisper*/snapshots/*/model.bin')]
    return sorted(result, key=lambda m: ('small.en' not in m['name'], m['name']))


class Studio:
    def __init__(self, output, state, opener=None):
        self.output, self.state = Path(output).resolve(), Path(state).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        for name in ('uploads', 'jobs'):
            (self.state / name).mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.active = None
        self.opener = opener or os.startfile
        self.token = secrets.token_urlsafe(32)
    def recover(self):
        # Called only after binding the port, so a duplicate launch cannot mark
        # the first server's active job as interrupted.
        for path in (self.state / 'jobs').glob('*.json'):
            job = read_json(path)
            if job['status'] == 'running':
                job.update(status='interrupted', phase='Server stopped before completion. Start a new run.')
                atomic_json(path, job)

    def save(self, job):
        atomic_json(self.state / 'jobs' / (job['id'] + '.json'), job)

    def get(self, job_id):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', job_id):
            raise ValueError('Invalid run.')
        return read_json(self.state / 'jobs' / (job_id + '.json'))

    def history(self):
        with self.lock:
            jobs = [read_json(p) for p in (self.state / 'jobs').glob('*.json')]
            known = {j.get('folder') for j in jobs}
            # Existing CLI runs under the selected output root are reviewable too.
            for manifest in ([] if self.active else sorted(self.output.glob('run-*/manifest.json'), reverse=True)[:200]):
                folder = contained(self.output, manifest.parent)
                if str(folder) not in known:
                    try:
                        data = read_json(manifest)
                        if not isinstance(data.get('clips'), list):
                            continue
                    except (ValueError, OSError):
                        continue
                    job = dict(id=folder.name, name='Imported CLI run', status='complete', phase='Ready for review',
                               created=datetime.fromtimestamp(manifest.stat().st_mtime, timezone.utc).isoformat(),
                               folder=str(folder), logs=[], reviews={}, options={})
                    self.save(job)
                    jobs.append(job)
            return [{k: j.get(k) for k in ('id', 'name', 'status', 'phase', 'created', 'options')}
                    for j in sorted(jobs, key=lambda j: j['created'], reverse=True)[:100]]

    def upload(self, upload_id, kind):
        if not re.fullmatch(r'[a-f0-9]{32}', str(upload_id)):
            raise ValueError('Choose a file first.')
        meta = read_json(self.state / 'uploads' / (upload_id + '.json'))
        if meta['kind'] != kind:
            raise ValueError('Wrong upload type.')
        path = contained(self.state / 'uploads', self.state / 'uploads' / meta['file'])
        if not path.is_file():
            raise ValueError('Uploaded file is missing. Please upload again.')
        return path, meta

    def start(self, body):
        url = validate_url(body['url']) if body.get('url') else None
        if url and body.get('video'):
            raise ValueError('Choose either a local file or a URL.')
        source, meta = (url, {'name': urlsplit(url).hostname + ' VOD'}) if url else self.upload(body.get('video'), 'video')
        top, duration = body.get('top', 5), body.get('duration', 30)
        if type(top) is not int or not 1 <= top <= 100 or type(duration) is not int or not 15 <= duration <= 60:
            raise ValueError('Choose 1–100 clips and a duration of 15–60 seconds.')
        layout, captions = body.get('layout', 'blur'), body.get('captions', True)
        if layout not in ('blur', 'crop') or type(captions) is not bool:
            raise ValueError('Choose a valid layout and captions setting.')
        model = body.get('model', 'tiny.en')
        if not isinstance(model, str) or not model.strip() or len(model) > 600:
            raise ValueError('Select an existing local Whisper model.')
        chat = self.upload(body['chat'], 'chat')[0] if body.get('chat') else None
        if not all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')):
            raise ValueError('FFmpeg and ffprobe must be available on PATH. Nothing is installed automatically.')
        args = [str(source), '--top', str(top), '--duration', str(duration), '--layout', layout,
                '--width', '720', '--out', str(self.output)]
        if url:
            args += ['--allow-download']
        args += ['--model', model.strip()] if captions else ['--no-captions']
        if chat:
            args += ['--chat', str(chat)]
        with self.lock:
            if self.active:
                raise RuntimeError('A run is already processing. Wait for it to finish.')
            job = dict(id=uuid.uuid4().hex, name=meta['name'], status='running', phase='Preparing pipeline',
                       created=datetime.now(timezone.utc).isoformat(), logs=[], reviews={}, folder=None,
                       options=dict(top=top, duration=duration, layout=layout, captions=captions))
            self.save(job)
            self.active = job['id']
            threading.Thread(target=self.worker, args=(job, args), daemon=False).start()
            return job['id']

    def worker(self, job, args):
        logs = deque(maxlen=180)
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            with subprocess.Popen([sys.executable, '-u', str(ROOT / 'ui_worker.py'), *args], cwd=ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  encoding='utf-8', errors='replace', creationflags=flags,
                                  env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}) as process:
                for line in process.stdout:
                    line = line.strip()[:3000]
                    with self.lock:
                        if line.startswith('STUDIO_RESULT '):
                            folder = contained(self.output, Path(json.loads(line[14:])['folder']))
                            if not (folder / 'manifest.json').is_file():
                                raise ValueError('Pipeline did not produce a manifest.')
                            job['folder'] = str(folder)
                        else:
                            logs.append(line)
                            job['logs'] = list(logs)
                            if line.startswith(('Analyzing', 'Rendering', 'Preparing', 'Downloading')):
                                job['phase'] = line
                        self.save(job)
                code = process.wait()
            with self.lock:
                job['status'] = 'complete' if code == 0 and job['folder'] else 'failed'
                job['phase'] = 'Ready for review' if job['status'] == 'complete' else 'Run failed. See the log for details.'
        except Exception as exc:
            with self.lock:
                job.update(status='failed', phase='Run failed', logs=list(logs) + [str(exc)[:1500]])
        finally:
            with self.lock:
                self.save(job)
                self.active = None

    def details(self, job_id):
        with self.lock:
            job = self.get(job_id)
            job['clips'] = []
            if job['folder'] and job['status'] == 'complete':
                folder = contained(self.output, Path(job['folder']))
                manifest = read_json(folder / 'manifest.json')
                for index, clip in enumerate(manifest['clips']):
                    entry = dict(clip, index=index, review=job['reviews'].get(str(index), 'pending'))
                    file = contained(folder, folder / clip['file'])
                    srt = contained(folder, file.with_suffix('.srt'))
                    entry['caption_text'] = srt.read_text(encoding='utf-8')[:50000] if srt.is_file() else ''
                    entry['url'] = f'/media/{job_id}/{index}'
                    job['clips'].append(entry)
                job['requested_top'] = manifest.get('requested_top', len(job['clips']))
            return job

    def media(self, job_id, index):
        job = self.get(job_id)
        if job['status'] != 'complete':
            raise ValueError('Run is not complete.')
        folder = contained(self.output, Path(job['folder']))
        clips = read_json(folder / 'manifest.json')['clips']
        if not 0 <= index < len(clips):
            raise ValueError('Unknown clip.')
        return contained(folder, folder / clips[index]['file'])

    def review(self, job_id, index, decision):
        if decision not in ('approved', 'rejected', 'pending'):
            raise ValueError('Unknown review decision.')
        with self.lock:
            source = self.media(job_id, index)
            job = self.get(job_id)
            approved = contained(self.output, self.output / 'approved' / job_id)
            if decision == 'approved':
                approved.mkdir(parents=True, exist_ok=True)
                for path in (source, contained(source.parent, source.with_suffix('.srt'))):
                    if path.is_file():
                        dest = contained(approved, approved / path.name)
                        temp = dest.with_suffix(dest.suffix + '.tmp')
                        shutil.copy2(path, temp)
                        temp.replace(dest)
            else:
                # Only these generated review copies; original clips always remain.
                for path in (source, source.with_suffix('.srt')):
                    contained(approved, approved / path.name).unlink(missing_ok=True)
            job['reviews'][str(index)] = decision
            self.save(job)
            return {'review': decision}


def make_server(studio, port=7792):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def guard(self, mutate=False):
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in hosts:
                raise PermissionError('Local access only.')
            if mutate:
                origin = self.headers.get('Origin')
                if origin and origin not in {'http://' + host for host in hosts}:
                    raise PermissionError('Origin not allowed.')
                if not secrets.compare_digest(self.headers.get('X-Studio-Token', ''), studio.token):
                    raise PermissionError('Refresh this page before continuing.')

        def send_json(self, value, status=200):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def file(self, path, ranges=False):
            size = path.stat().st_size
            start, end, partial = 0, size - 1, False
            requested = self.headers.get('Range') if ranges else None
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not match or not any(match.groups()):
                    return self.range_error(size)
                left, right = match.groups()
                if not left:
                    start = max(0, size - int(right))
                else:
                    start = int(left)
                    end = min(end, int(right)) if right else end
                if start > end or start >= size:
                    return self.range_error(size)
                partial = True
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if ranges:
                self.send_header('Accept-Ranges', 'bytes')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            with path.open('rb') as handle:
                handle.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def range_error(self, size):
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def dispatch(self):
            try:
                self.guard(self.command != 'GET')
                path = urlsplit(self.path).path
                if self.command == 'GET':
                    assets = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
                    if path in assets:
                        return self.file(ROOT / 'web' / assets[path])
                    if path == '/api/config':
                        return self.send_json(dict(token=studio.token, models=cached_models(), output=str(studio.output),
                                                   ffmpeg=bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))))
                    if path == '/api/runs':
                        return self.send_json(studio.history())
                    if match := re.fullmatch(r'/api/runs/([\w-]+)', path):
                        return self.send_json(studio.details(match[1]))
                    if match := re.fullmatch(r'/media/([\w-]+)/(\d+)', path):
                        return self.file(studio.media(match[1], int(match[2])), ranges=True)
                if self.command == 'PUT' and path in ('/api/upload/video', '/api/upload/chat'):
                    kind = path.rsplit('/', 1)[-1]
                    name = re.split(r'[/\\]', unquote(self.headers.get('X-File-Name', '')))[-1][:240]
                    ext = Path(name).suffix.lower()
                    if ext not in (VIDEO_EXTS if kind == 'video' else {'.csv'}):
                        raise ValueError('Choose a video file.' if kind == 'video' else 'Chat must be a CSV file.')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= (8 * 1024**3 if kind == 'video' else 20 * 1024**2):
                        raise ValueError('Upload limit: 8 GB video / 20 MB chat. File must not be empty.')
                    upload_id = uuid.uuid4().hex
                    dest = studio.state / 'uploads' / (upload_id + ext)
                    temp = dest.with_suffix('.part')
                    try:
                        self.connection.settimeout(90)
                        with temp.open('xb') as handle:
                            remaining = length
                            while remaining:
                                chunk = self.rfile.read(min(1024 * 1024, remaining))
                                if not chunk:
                                    raise ValueError('Upload interrupted. Please try again.')
                                handle.write(chunk)
                                remaining -= len(chunk)
                        temp.replace(dest)
                    finally:
                        temp.unlink(missing_ok=True)
                    atomic_json(dest.with_suffix('.json'), dict(file=dest.name, name=name, kind=kind))
                    return self.send_json(dict(id=upload_id, name=name, size=length))
                if self.command == 'POST':
                    if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                        raise ValueError('Expected JSON.')
                    size = int(self.headers.get('Content-Length', 0))
                    if not 0 < size <= 64000:
                        raise ValueError('Invalid request size.')
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError('Expected an object.')
                    if path == '/api/runs':
                        return self.send_json({'id': studio.start(body)}, 202)
                    if match := re.fullmatch(r'/api/runs/([\w-]+)/(\d+)/review', path):
                        return self.send_json(studio.review(match[1], int(match[2]), body.get('decision')))
                    if match := re.fullmatch(r'/api/runs/([\w-]+)/open', path):
                        job = studio.get(match[1])
                        folder = contained(studio.output, Path(job['folder'])) if job.get('folder') else studio.output
                        studio.opener(str(folder))
                        return self.send_json({'ok': True})
                self.send_json({'error': 'Not found.'}, 404)
            except PermissionError as exc:
                self.send_json({'error': str(exc)}, 403)
            except FileNotFoundError:
                self.send_json({'error': 'File or run not found.'}, 404)
            except (ValueError, KeyError, TypeError) as exc:
                self.send_json({'error': str(exc)}, 400)
            except RuntimeError as exc:
                self.send_json({'error': str(exc)}, 409)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except OSError:
                self.send_json({'error': 'Local file operation failed. Check disk space and folder access.'}, 500)

        do_GET = do_POST = do_PUT = dispatch

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    studio.recover()
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=7792)
    parser.add_argument('--out', type=Path, default=ROOT / 'clips')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    # Keep each output library's uploads/history together, including custom --out.
    studio = Studio(args.out, args.out.resolve() / '.studio')
    server = make_server(studio, args.port)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Clip Studio: {url}\nOutput: {studio.output}\nKeep this terminal open while rendering.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('Closing Clip Studio. Any current render will finish before this terminal exits.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
