# GTA 6 Clip AI Farm — local prototype

Turn a recorded VOD into ranked vertical clips, ready for **human review**. Test
with GTA 5 roleplay recordings now; the pipeline does not depend on a specific game.
This is a standalone CLI, not a Jarvis plugin or an unattended publishing service.

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
require an approved JavaScript runtime, authentication or extractor updates; these
are not installed/configured here. URL downloads were **not live-tested** in this
prototype: yt-dlp is not installed in the existing test environment, and no
third-party content was downloaded.

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
