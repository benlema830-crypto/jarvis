#!/usr/bin/env python3
"""Local highlight ranking, vertical video rendering and Whisper captions."""
from __future__ import annotations

import argparse
from array import array
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import uuid
from urllib.parse import urlsplit
import wave

BIN_SECONDS = 0.5
SAMPLE_RATE = 8000


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"{Path(command[0]).name} failed: {(stderr or '')[-2500:]}")
    return result.stdout


def probe(path):
    return json.loads(run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ]))


def video_duration(info):
    if not any(s["codec_type"] == "video" for s in info["streams"]):
        raise ValueError("Input has no video stream.")
    return float(info["format"]["duration"])


def audio_levels(source):
    """Stream PCM in half-second bins; memory scales with bins, not decoded audio."""
    process = subprocess.Popen([
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-map", "0:a:0",
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    levels = []
    try:
        while True:
            data = process.stdout.read(int(SAMPLE_RATE * BIN_SECONDS) * 2)
            if not data:
                break
            samples = array("h")
            samples.frombytes(data)
            if sys.byteorder != "little":
                samples.byteswap()
            rms = math.sqrt(sum(x * x for x in samples) / max(1, len(samples))) / 32768
            levels.append(rms)
    except BaseException:
        if process.poll() is None:
            process.terminate()
        process.wait()
        raise
    finally:
        process.stdout.close()
    code = process.wait()
    if code or not levels:
        raise RuntimeError("Could not decode an audio stream for loudness analysis.")
    return levels


def chat_rates(path, bins, offset=0):
    """CSV time_seconds or JSON/JSONL time_seconds; Twitch comments also accepted."""
    counts = [0.0] * bins
    if not path:
        return counts
    path = Path(path)
    with path.open(encoding="utf-8-sig") as handle:
        if path.suffix.lower() == ".csv":
            rows = list(csv.DictReader(handle))
        elif path.suffix.lower() == ".jsonl":
            rows = [json.loads(line) for line in handle if line.strip()]
        else:
            content = json.load(handle)
            rows = content.get("comments", []) if isinstance(content, dict) else content
    if not isinstance(rows, list):
        raise ValueError("Chat must be a JSON array, Twitch comments object, JSONL or CSV.")
    for row in rows:
        timestamp = row.get("time_seconds", row.get("content_offset_seconds"))
        if timestamp is None:
            raise ValueError("Each chat message needs time_seconds or content_offset_seconds.")
        seconds = float(timestamp) + offset
        if not math.isfinite(seconds):
            raise ValueError("Chat timestamps must be finite seconds relative to the VOD.")
        index = math.floor(seconds / BIN_SECONDS)
        if 0 <= index < bins:
            counts[index] += 1
    # Five-second centered message-rate window, in messages/second.
    return [sum(counts[max(0, i-5):min(bins, i+5)]) / 5 for i in range(bins)]


def normalize(values):
    baseline = statistics.median(values)
    span = max(values, default=0) - baseline
    return [max(0.0, (x - baseline) / span) if span > 1e-9 else 0.0 for x in values]


def rank_highlights(levels, chat, duration, length, top, chat_weight=0.35):
    audio = normalize(levels)
    messages = normalize(chat)
    has_chat = any(messages)
    weight = chat_weight if has_chat else 0.0
    scores = [(1-weight) * a + weight * c for a, c in zip(audio, messages)]
    ranked = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    selected = []
    for index in ranked:
        if scores[index] <= 0:
            break
        peak = (index + 0.5) * BIN_SECONDS
        start = min(max(0.0, peak - length * 0.35), duration - length)
        end = start + length
        if any(start < c["end"] and end > c["start"] for c in selected):
            continue
        selected.append({"start": round(start, 3), "end": round(end, 3),
                         "peak": round(peak, 3), "score": round(scores[index], 5),
                         "audio_score": round(audio[index], 5),
                         "chat_score": round(messages[index], 5)})
        if len(selected) == top:
            break
    return selected


def stamp(seconds):
    millis = max(0, round(seconds * 1000))
    seconds, ms = divmod(millis, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def write_srt(segments, path, duration):
    """Short, word-timed caption groups; never insert invented narration."""
    cues = []
    for segment in segments:
        words = list(segment.words or [])
        if not words:
            words = [type("Word", (), {"start": segment.start, "end": segment.end,
                                       "word": segment.text})()]
        group = []
        for word in words:
            if group and (len(" ".join(w.word.strip() for w in group)) + len(word.word) > 36
                          or word.end - group[0].start > 3.5):
                cues.append(group)
                group = []
            group.append(word)
        if group:
            cues.append(group)
    with path.open("x", encoding="utf-8") as handle:
        cue_index = 0
        for group in cues:
            start = max(0.0, float(group[0].start))
            end = min(duration, float(group[-1].end))
            text = " ".join(w.word.strip() for w in group).strip()
            # Suppress subtitle markup / ASS override sequences in model output.
            for token in ("{", "}", "<", ">", "\\"):
                text = text.replace(token, "")
            if end <= start or not text:
                continue
            cue_index += 1
            handle.write(f"{cue_index}\n{stamp(start)} --> {stamp(end)}\n{text}\n\n")
    return cue_index


def load_whisper(args):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is missing. See README; installation needs approval.") from exc
    # Deliberately prohibit implicit model downloads, including named HF models.
    return WhisperModel(args.model, device=args.device, compute_type=args.compute_type,
                        local_files_only=True, cpu_threads=args.cpu_threads)


def caption(model, audio, target, args, duration):
    import numpy as np  # already a faster-whisper dependency
    # Supplying PCM avoids PyAV/FFmpeg ABI issues in unrelated installed runtimes.
    with wave.open(str(audio), "rb") as handle:
        samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
        samples = samples.astype(np.float32) / 32768.0
    segments, info = model.transcribe(samples, language=args.language, beam_size=1,
                                     word_timestamps=True, vad_filter=False,
                                     condition_on_previous_text=False)
    return write_srt(segments, target, duration), info.language


def render(source, candidate, target, subtitle, args):
    width, height = args.width, args.width * 16 // 9
    if args.layout == "crop":
        graph = (f"[0:v:0]scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height},setsar=1[v]")
    else:
        graph = (f"[0:v:0]split=2[bg][fg];"
                 f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height},boxblur=20:2[blur];"
                 f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease:"
                 "force_divisible_by=2[front];"
                 f"[blur][front]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    if subtitle is not None:
        # Renderer cwd is a generated directory; only safe generated basenames enter filter syntax.
        graph += (f";[v]subtitles=filename='{subtitle.name}':original_size={width}x{height}:"
                  "force_style='FontName=Arial,FontSize=22,Outline=2,MarginV=24,Alignment=2'[out]")
    else:
        graph += ";[v]null[out]"
    run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
         "-ss", str(candidate["start"]), "-i", str(source),
         "-t", str(candidate["end"] - candidate["start"]),
         "-filter_complex", graph, "-map", "[out]", "-map", "0:a:0",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-r", "30", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(target)],
        cwd=target.parent)


def download(url, folder, allowed):
    if not allowed:
        raise ValueError("URL download requires --allow-download and permission to clip the content.")
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise ValueError("Do not put credentials in input URLs.")
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("yt-dlp is missing. Local files still work; see README.") from exc
    # Python API does not load user CLI configs, cookies, plugins or shell commands.
    options = {"outtmpl": str(folder / "source.%(ext)s"), "noplaylist": True,
               "format": "bv*+ba/b", "merge_output_format": "mp4", "quiet": True,
               "no_warnings": True, "overwrites": False}
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        if not info or info.get("_type") == "playlist":
            raise ValueError("Expected one VOD, not a playlist.")
    files = [p for p in folder.glob("source.*") if p.suffix not in (".part", ".ytdl")]
    if len(files) != 1:
        raise RuntimeError("Could not identify one completed VOD download.")
    return files[0].resolve()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", help="Local video path or permitted HTTP(S) VOD URL")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--out", type=Path, default=Path("clips"))
    p.add_argument("--duration", type=float, default=30, help="Clip duration, 15–60 seconds")
    p.add_argument("--layout", choices=("crop", "blur"), default="blur")
    p.add_argument("--width", type=int, default=720, help="9:16 width: 360, 720 or 1080")
    p.add_argument("--chat", type=Path)
    p.add_argument("--chat-offset", type=float, default=0, help="Seconds added to chat timestamps")
    p.add_argument("--chat-weight", type=float, default=0.35)
    p.add_argument("--model", default="tiny.en", help="Existing local model path or cached model name")
    p.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    p.add_argument("--compute-type", default="int8")
    p.add_argument("--cpu-threads", type=int, default=4)
    p.add_argument("--language", default=None, help="Language code; default auto-detect")
    p.add_argument("--no-captions", action="store_true", help="Explicitly skip local Whisper")
    p.add_argument("--allow-download", action="store_true", help="Confirm permission for URL download")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if not 1 <= args.top <= 100 or not 15 <= args.duration <= 60:
        raise ValueError("--top must be 1–100 and --duration must be 15–60 seconds.")
    if args.width not in (360, 720, 1080) or not 0 <= args.chat_weight <= 1:
        raise ValueError("Choose width 360/720/1080 and chat weight 0–1.")
    if not math.isfinite(args.chat_offset) or args.cpu_threads < 1:
        raise ValueError("Chat offset must be finite and CPU threads must be positive.")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is not on PATH. See README; no tools are auto-installed.")
    is_url = urlsplit(args.input).scheme.lower() in ("http", "https")
    source = None if is_url else Path(args.input).expanduser().resolve()
    if source is not None and not source.is_file():
        raise ValueError("Input video does not exist.")
    if is_url and not args.allow_download:
        raise ValueError("Downloading requires --allow-download and permission to clip the content.")
    # Check model readiness before expensive work or downloading a VOD.
    model = None if args.no_captions else load_whisper(args)
    folder = args.out.resolve() / (datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S-")
                                 + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    if is_url:
        source = download(args.input, folder, args.allow_download)
    info = probe(source)
    duration = video_duration(info)
    if duration < 15:
        raise ValueError("Input must contain at least 15 seconds of video.")
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise ValueError("Input needs an audio stream for loudness detection.")
    length = min(args.duration, duration)
    print("Analyzing audio loudness…", flush=True)
    levels = audio_levels(source)
    rates = chat_rates(args.chat, len(levels), args.chat_offset)
    candidates = rank_highlights(levels, rates, duration, length, args.top, args.chat_weight)
    if not candidates:
        raise ValueError("No loudness or chat spikes found; use a source with varying activity.")
    report = {"algorithm": "half-second RMS above median + five-second chat rate; non-overlapping",
              "source_duration": duration, "layout": args.layout, "captions": model is not None,
              "requested_top": args.top, "clips": candidates}
    for number, candidate in enumerate(candidates, 1):
        stem = f"clip-{number:02d}"
        subtitle = folder / f"{stem}.srt" if model is not None else None
        print(f"Rendering {number}/{len(candidates)} at {candidate['start']:.2f}s…", flush=True)
        if model is not None:
            audio = folder / f"{stem}-asr.wav"
            run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-ss", str(candidate["start"]),
                 "-i", str(source), "-t", str(length), "-vn", "-ac", "1", "-ar", "16000",
                 "-c:a", "pcm_s16le", str(audio)])
            count, language = caption(model, audio, subtitle, args, length)
            candidate.update(caption_cues=count, language=language)
            # Only this run's generated intermediate; retain SRT and final video.
            audio.unlink()
        target = folder / f"{stem}.mp4"
        render(source, candidate, target, subtitle, args)
        result = probe(target)
        video = next(s for s in result["streams"] if s["codec_type"] == "video")
        actual_duration = video_duration(result)
        if video["width"] * 16 != video["height"] * 9 or abs(actual_duration - length) > 0.2:
            raise RuntimeError("Rendered clip failed aspect ratio/duration verification.")
        candidate.update(file=target.name, actual_duration=actual_duration,
                         width=video["width"], height=video["height"])
    (folder / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Created {len(candidates)} clip(s): {folder}")
    if len(candidates) < args.top:
        print("Fewer than requested: insufficient distinct, non-overlapping activity peaks.")
    return folder


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
