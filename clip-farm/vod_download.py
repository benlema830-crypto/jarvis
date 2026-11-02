"""Shared, finite-VOD downloader for the CLI and Clip Studio."""
import math
from pathlib import Path
import shutil
import time
from urllib.parse import urlsplit


def validate_url(url):
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError('Paste a valid HTTP(S) video URL.')
    url = url.strip()
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or any(c.isspace() for c in url):
        raise ValueError('Paste a valid HTTP(S) video URL.')
    if parsed.username or parsed.password:
        raise ValueError('Do not include passwords or credentials in URLs.')
    return url


def require_vod(info, *, incomplete=False):
    if info.get('_type') in ('playlist', 'multi_video'):
        raise ValueError('Use a single video or VOD link, not a playlist or channel.')
    if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming', 'post_live'):
        raise ValueError('Live, upcoming and still-processing streams are not supported. Use a finished VOD.')
    if info.get('availability') in ('private', 'premium_only', 'subscriber_only', 'needs_auth'):
        raise ValueError('This video is private, subscriber-only or requires sign-in. Use an accessible VOD or upload an authorized local copy.')
    if not incomplete:
        protocols = [info.get('protocol', '')] + [f.get('protocol', '') for f in info.get('requested_formats', [])]
        streaming = any(any(tag in protocol for tag in ('m3u8', 'dash', 'rtmp')) for protocol in protocols)
        duration = info.get('duration')
        finite = isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0
        if streaming and not finite:
            raise ValueError('Cannot confirm a finite stream duration. Use a finished VOD or a local video file.')
    return None


def download(url, folder, allowed):
    if not allowed:
        raise ValueError('URL download requires --allow-download and permission to clip the content.')
    url = validate_url(url)
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise RuntimeError('yt-dlp is missing from this Python environment. Local uploads still work.') from exc
    last = [0.0]

    def progress(data):
        now = time.monotonic()
        if data['status'] == 'finished':
            print('Downloading complete; preparing FFmpeg merge...', flush=True)
        elif data['status'] == 'downloading' and now - last[0] >= 1:
            last[0] = now
            total = data.get('total_bytes') or data.get('total_bytes_estimate')
            done = data.get('downloaded_bytes', 0)
            amount = f'{min(100, done / total * 100):.1f}%' if total else f'{done / 1024**2:.1f} MB'
            speed = data.get('speed')
            eta = data.get('eta')
            print('Downloading ' + amount + (f' | {speed / 1024**2:.1f} MB/s' if speed else '')
                  + (f' | ETA {eta}s' if eta is not None else ''), flush=True)

    class Logger:
        def debug(self, message):
            if message.startswith('[Merger]'):
                print('Preparing FFmpeg merge...', flush=True)
        def warning(self, message):
            print('Download warning: ' + message, flush=True)
        def error(self, message):
            pass  # The exception below supplies the actionable error once.

    options = dict(outtmpl=str(Path(folder) / 'source.%(ext)s'), noplaylist=True,
                   format='bv*[height<=1080]+ba/b[height<=1080]/b', merge_output_format='mp4',
                   quiet=True, no_warnings=False, overwrites=False, logger=Logger(),
                   progress_hooks=[progress], match_filter=require_vod,
                   socket_timeout=30, retries=3, fragment_retries=3,
                   skip_unavailable_fragments=False, max_filesize=8 * 1024**3)
    if shutil.which('node'):
        options['js_runtimes'] = {'node': {'path': shutil.which('node')}}
    # Identify this app on direct media requests; site extractors retain yt-dlp's
    # own browser-compatible headers (YouTube/Twitch can depend on them).
    if Path(urlsplit(url).path).suffix.lower() in ('.mp4', '.webm', '.mov', '.mkv', '.ogv'):
        options['http_headers'] = {'User-Agent': 'ClipStudio/1.0'}
    print('Downloading: checking video access and finished-VOD status...', flush=True)
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
            if not info:
                raise ValueError('No accessible video was found at this link.')
            require_vod(info)
            # Reuse validated metadata; match_filter also guards each selected format.
            downloader.process_ie_result(info, download=True)
    except DownloadError as exc:
        raise ValueError('Download failed. Check the link; private, subscriber-only, removed or sign-in-required videos may be inaccessible. '
                         'Try an authorized local file. Details: ' + str(exc)) from exc
    files = [p for p in Path(folder).glob('source.*') if p.suffix in ('.mp4', '.mkv', '.webm', '.mov', '.ogv', '.flv')]
    if len(files) != 1:
        raise ValueError('Download did not produce one complete video (possibly over the 8 GB download limit). See the log.')
    print('Downloading finished. Starting the clip pipeline...', flush=True)
    return files[0].resolve()
