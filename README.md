# J.A.R.V.I.S.

An Iron Man–style voice assistant for Windows, powered by Claude. Say "Hey Jarvis" and talk to him. He answers in a British voice, and can act on your PC as well as answer questions.

## What he can do

- **Hearing:** a "hey Jarvis" wake word, speech recognition that runs locally on your GPU (faster-whisper), and an optional voice lock so he only responds to you. Interrupt him any time with "Jarvis, stop", Ctrl+Alt+J, or the HUD's STOP button.
- **Voice:** ElevenLabs if you have a key, otherwise the free offline Kokoro voice. You can send it to any speaker.
- **Brain:** Claude, with live web search, long-term memory, reminders and timers, a startup briefing (weather, calendar, what you were last working on), and a HUD that shows what he's doing.
- **On your PC:**
  - Open any app.
  - Find and open files.
  - Control media and volume.
  - Read your clipboard.
  - Look at your screen.
- **Agents:**
  - A **screen agent** that clicks and types its way through apps and websites (Claude computer use).
  - **Terminal tasks** that hand jobs to Claude Code in the background: files, system checks, troubleshooting, scripts, coding.
  - Both pause and ask you out loud before anything risky, and only your spoken "yes" counts.
- **Work-safe mode:** Outlook and Teams are hidden from screenshots, the agents and the activity log.

## Requirements

- Windows 10 or 11, Python 3.12, and a microphone.
- An [Anthropic API key](https://console.anthropic.com/settings/keys).
- Optional:
  - An NVIDIA GPU for fast local speech recognition. It falls back to the CPU without one.
  - An [ElevenLabs](https://elevenlabs.io) API key for the premium voice.
  - [Claude Code](https://code.claude.com), installed and logged in, for terminal tasks.

## Setup

1. Create a virtual environment and install the requirements:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Download the Kokoro voice model into a `models` folder: [`kokoro-v1.0.onnx` and `voices-v1.0.bin`](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0).

3. Copy `.env.example` to `.env` and fill it in. At minimum this is `ANTHROPIC_API_KEY`; every setting is explained in the file.

4. Optional:
   - Run `enroll.bat` to set up the voice lock.
   - Run `elevenlabs.bat` to design or pick an ElevenLabs voice.
   - Run `.venv\Scripts\python.exe install_startup.py` to start Jarvis when you log in.

5. Start him with `run.bat`. Use `run.bat --text` to type instead of talk. The HUD opens at http://127.0.0.1:7777.

The speech-recognition and wake-word models download automatically the first time you run him.

## Safety

The agents can control your mouse, keyboard and terminal, so:
- They ask out loud before deleting, installing or uninstalling software, or changing system settings. Approvals are checked in code, so the AI can't approve for you.
- Outlook and Teams are always off-limits.
- "Stop", Ctrl+Alt+J, or the HUD's STOP button cancels any task.
- Your keys and personal data (`.env`, `data/`) are excluded from git.

Run the tests with `.venv\Scripts\python.exe -m unittest discover tests`.
