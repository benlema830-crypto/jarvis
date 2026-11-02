# GTA 6 Clip AI Farm — local prototype

Turn a recorded VOD into ranked vertical clips, ready for **human review**. Test
with GTA 5 roleplay recordings now; the pipeline does not depend on a specific game.
This is a standalone local app with a graphical studio and a CLI, not an unattended publishing service.

## Clip Studio — graphical interface

From the Jarvis project folder, run **`clip-farm\start-studio.bat`**, or double-click
that file in Explorer. It uses the clip-farm virtual environment if present,
otherwise Jarvis's existing environment, and opens **http://127.0.0.1:7792**.
Keep the terminal open while working. Nothing in Jarvis itself is restarted.

Alternatively, with the existing Python environment:

```powershell
cd C:\Users\Lemab\Jarvis\clip-farm
..\.venv\Scripts\python.exe studio.py
# Optional: choose another port/output location, or skip opening a browser:
..\.venv\Scripts\python.exe studio.py --port 7792 --out clips --no-browser
```

1. Drop a local VOD or click **browse files**. Optionally add a chat CSV with a
   `time_seconds` column. Uploads are local copies, limited to 8 GB per video and
   20 MB per chat file; originals stay untouched. Use the CLI for larger inputs.
2. Choose clip count, length (15–60 seconds), blur fill or center crop, captions,
   and an existing local Whisper model. Cached models are listed automatically.
3. Click **Find my highlights**. The studio runs the original `clip_farm.main`
   pipeline in a separate process, at 720×1280. The live stage/log display reports
   real pipeline messages; it does not invent a time-to-completion percentage.
4. Preview clips, inspect activity scores and read the SRT caption transcript.
   **Approve** copies the MP4 and SRT to `clips/approved/<run-id>/`.
   **Reject**, or clicking Approved again, removes only those generated review
   copies. Original outputs remain in their `clips/run-.../` directory.
5. Use **Open folder** for the original run folder. The sidebar (or **History** on
   a small screen) restores previous runs and decisions. Completed CLI runs under
   the selected output folder are also imported into history.

The app uses Python's standard-library local server; no Flask/FastAPI installation
or frontend build is needed. Its assets have no CDN/font/network dependencies.
It binds only to loopback, checks the Host and mutation origin/token, streams
uploads to disk, supports seeking in preview videos, and runs one render at a time.
Do not expose it as a public/multi-user server.

Local uploads and run/review state are retained in `.studio/` under the selected
output directory (`clips/.studio/` by default), so output libraries stay separate. Closing
the browser does not cancel a run. Ctrl+C closes the web server and lets an active
render finish before Python exits. A forcibly terminated run is marked interrupted
on the next start, not automatically resumed. There is no cancel/resume UI yet.
Partial pipeline outputs are retained for diagnosis. Nothing is auto-published.

Choose **From URL**, paste a YouTube video, finished Twitch VOD or direct public
video link, set your clip options, and click **Find my highlights**. Only clip
footage you have permission to use. The log shows download percentage, speed and
ETA, followed by FFmpeg merge (when separate audio/video tracks are supplied) and
the normal clip pipeline. The downloaded `source.*` stays in that run's folder.
Live, upcoming and still-processing streams are refused; streaming manifests with
unknown duration are refused too. Playlist/channel collections are not processed.
Downloads are limited to 8 GB per media file, at up to 1080p where available;
network retries are bounded. Private/subscriber-only/sign-in-required videos may
fail with an explanation. No cookies or account access are imported.
Refresh an already-open page after updating/restarting Clip Studio.

Studio checks:

```powershell
..\.venv\Scripts\python.exe -m unittest -v test_clip_farm test_studio test_vod_download
..\.venv\Scripts\python.exe check_studio_browser.py
```

The browser check needs the already-installed Playwright package and Chrome plus
the existing `test-artifacts/*/synthetic.mp4` fixture and a cached Whisper model.
It performs real local ASR/rendering, playback, approve/reject, reload/history,
and responsive-layout checks. Folder opening is mocked; no Explorer window or
external service is used. Screenshots and verification JSON are saved under
`test-artifacts/studio-*/`. No dependencies/models are installed by the check.

## Permission first

**Only download and clip content you own or have permission to use. Obtain the
creator's permission or use their official clipping program, and follow its terms.**
A public VOD or a working download URL is not permission to repost it. Respect
platform rules, attribution, music rights and participants' privacy. Review every
clip and caption before sharing. Nothing is uploaded or published by this tool.

## Setup

Requires Python **3.12** (the pinned NumPy requires 3.12+) and an existing
FFmpeg/ffprobe installation on PATH.
FFmpeg must include `libx264`, AAC and the `subtitles` filter (libass); the synthetic
smoke test also needs `flite`. No executable or model is downloaded automatically.

**Ask for approval before installing packages/tools or downloading models.** After
approval, use a dedicated environment rather than changing Jarvis's environment:

```powershell
cd C:\Users\Lemab\Jarvis\clip-farm
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
```

Direct dependencies are pinned in `requirements.txt`; it is not a complete
transitive lockfile. CPU/int8 is the safe default; no CUDA installation is needed.
GPU mode is optional and requires compatible CTranslate2/CUDA/cuDNN libraries,
independently of any PyTorch installation. See the official
[faster-whisper requirements](https://github.com/SYSTRAN/faster-whisper#requirements).
Do not change shared GPU libraries just for this prototype without approval.

### Local Whisper model

Pass an **existing CTranslate2-format Whisper model directory** with `--model`, or a
model name already present in Hugging Face's local cache. A PyTorch-only Whisper
checkpoint is not the correct format. `local_files_only=True` prevents implicit
downloads. The default name is `tiny.en`; if it is not cached, captions stop with
an error. There is no silent substitution with fake captions or a cloud service.

If you need a new model, obtain approval for the model and download size first.
For example, `tiny.en` has roughly 75 MiB of weights, plus small metadata files;
larger models need substantially more disk, memory and CPU time. An explicit
approved download can be done separately using the official faster-whisper API,
then this CLI can reuse its cache. See
[official model usage](https://github.com/SYSTRAN/faster-whisper#usage).

## Run

With the environment activated and a cached `tiny.en` model:

```powershell
python clip_farm.py "D:\Recordings\my-roleplay-vod.mp4" --top 5 --out clips/
```

Or supply your existing model directory explicitly:

```powershell
python clip_farm.py "D:\Recordings\my-roleplay-vod.mp4" --top 5 --out clips/ --model "D:\Models\faster-whisper-tiny.en"
python clip_farm.py "D:\Recordings\my-roleplay-vod.mp4" --duration 20 --layout crop --chat chat.csv --model "D:\Models\faster-whisper-tiny.en"
```

The default layout is blurred background fill, preserving the whole horizontal
picture in the foreground. `--layout crop` instead center-crops to fill the screen.
The default resolution is **720×1280 at 30 FPS**; `--width 360` or `1080` also works.
Duration is 15–60 seconds (default 30). A shorter source of at least 15 seconds uses
its full duration. Inputs shorter than 15 seconds or without audio are rejected.

An explicit `--no-captions` mode can test cutting/rendering without Whisper. For
CUDA, after independently verifying your runtime, use `--device cuda
--compute-type float16`. No settings in Jarvis or VoiceStudio are used or changed.

### URL input

Only after confirming permission, and with the pinned yt-dlp package installed:

```powershell
python clip_farm.py "https://example.com/your-authorized-vod" --allow-download --top 5 --out clips/ --model "D:\Models\faster-whisper-tiny.en"
```

Uses the [official yt-dlp Python API](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp).
It downloads one VOD, not a playlist, and retains the source in the run directory.
No browser cookies, account credentials, user CLI configs or custom shell hooks
are supplied. DRM/private streams are not bypassed. Some platforms additionally
require authentication or extractor updates; these are not configured automatically.
yt-dlp 2026.10.26 and its YouTube EJS dependency 0.8.0 are installed in Jarvis's
`.venv` under the approved installation. The downloader enables the existing Node
runtime when available; no new system runtime is installed. A real URL-to-clip browser test uses the
[W3C-hosted Big Buck Bunny trailer](https://media.w3.org/2010/05/bunny/trailer.mp4).
Attribution: (c) copyright 2008, Blender Foundation / www.bigbuckbunny.org;
[Creative Commons Attribution 3.0](https://peach.blender.org/about/).
Run `..\.venv\Scripts\python.exe check_url_browser.py` to repeat that opt-in
network test. YouTube/Twitch account-specific restrictions are not tested by it.

### Optional chat

CSV header `time_seconds` (other columns are ignored):

```csv
time_seconds,message
12.4,wow
12.8,what happened
48.1,amazing
```

Also accepts a JSON array or JSONL records with `time_seconds`, or a Twitch export
object containing `comments` with numeric `content_offset_seconds`. Timestamps
are elapsed seconds from the **start of this video**, not wall-clock dates.
`--chat-offset 10` adds ten seconds when aligning a chat file with a trimmed VOD.
Each row counts as one message; message text is never analyzed or copied into the
manifest. `--chat-weight 0.35` controls its contribution (0–1).

## Detection and outputs

1. FFmpeg streams mono audio at 8 kHz; Python computes RMS per half-second. The
   analyzer keeps only these levels, not the decoded audio of the whole VOD.
2. Audio strength above the median and five-second chat-message rates are
   normalized separately and combined. Without useful chat spikes, audio receives
   the full weight. Loud music/noise can score highly; this is an explainable
   heuristic, **not story understanding or a virality predictor**.
3. Select the highest-scoring non-overlapping windows, with 35% of each clip before
   its peak. Boundaries clamp to the video. Flat audio/chat yields no highlights.
   There may be fewer than `--top` clips when distinct windows are unavailable.
4. Only selected windows are transcribed locally with faster-whisper. Short
   word-timed SRT groups are burned into the MP4; the SRT is retained for review.
   Decoding uses FFmpeg PCM, avoiding PyAV decoder-version incompatibilities.
5. FFprobe verifies each output's 9:16 dimensions and duration (0.2 s tolerance).

Each invocation creates a unique `clips/run-<UTC date>-<id>/` directory containing
ranked `clip-01.mp4`, matching `.srt` files and `manifest.json` with scores, source
times, language and verified output properties. Originals/existing clips are not
overwritten. Failed runs may leave partial outputs for diagnosis. Only generated
temporary ASR WAVs are removed after successful transcription. Outputs, transcripts
and test media are gitignored; treat them as private and review before sharing.

## Tests and actual verification

```powershell
python -m unittest -v test_clip_farm
python smoke_test.py --model "D:\Models\existing-faster-whisper-model"
```

The smoke test creates a 44-second FFmpeg test pattern, tones and bundled Flite
synthetic speech. It creates two real Whisper-captioned blur clips, a crop clip,
an independent no-caption comparison and another clip via the actual CLI. It
checks nonempty captions, changed caption pixels, 360×640 geometry and 15-second
durations. It writes results under ignored `test-artifacts/`; no network or private
voice references are used. Flite is needed only for generating this test fixture.

Verified on 2026-10-26 (America/Chicago): **7 unit tests passed** and the full smoke
test passed using existing FFmpeg 9.0.2, Python 3.12, faster-whisper 1.2.1,
CTranslate2 4.8.3, NumPy 2.5.4 and an already-cached large-v3-turbo model on CPU/int8.
No dependencies or models were installed. The unit tests cover chat weighting and
alignment, ranking, boundaries, overlap suppression, silent sources, subtitle
sanitization/no-overwrite and invalid arguments/download permission.

## Still needs work

- Test a permitted GTA 5 roleplay VOD and tune scoring, pre-roll and chat alignment.
- Live-test a permitted URL after approved yt-dlp installation; platform support varies.
- Human-check Whisper errors, noisy speech, silence hallucinations and caption timing.
- Benchmark long VODs and shared-GPU use; no production throughput claims yet.
- Add scene/speaker-aware framing and story-aware selection if the basic clips prove useful.
- This version intentionally has no automatic posting, account integrations or unattended jobs.
