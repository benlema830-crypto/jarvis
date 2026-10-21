"""Bounded, in-memory voice diagnostics. Never stores speech, audio or exceptions."""
import math
import threading
import time

_lock = threading.Lock()
_phase = "starting"
_api = "not_checked"
_recognition = {"reason": "none", "at": None}
_output_error = False
_voice = _ears = _listener = None
_text_mode = False


def phase(value):
    global _phase
    if value not in {"starting", "loading_voice", "loading_microphone", "briefing", "ready", "failed"}:
        raise ValueError("Unknown startup phase")
    with _lock:
        _phase = value


def api_state(value):
    global _api
    if value not in {"not_checked", "requesting", "responded", "interrupted", "error"}:
        raise ValueError("Unknown API state")
    with _lock:
        _api = value


def recognition(reason):
    global _recognition
    if reason not in {"none", "voice_not_matched", "recognized", "no_speech", "recognition_error",
                      "wake_word_required", "accepted", "interruption_rejected"}:
        raise ValueError("Unknown recognition reason")
    with _lock:
        _recognition = {"reason": reason, "at": time.time()}


def output_failed():
    global _output_error
    with _lock:
        _output_error = True


def bind(*, voice=None, ears=None, listener=None, text_mode=False):
    global _voice, _ears, _listener, _text_mode
    with _lock:
        _voice, _ears, _listener, _text_mode = voice, ears, listener, text_mode


def stream_active(stream):
    try:
        return bool(stream.active)
    except Exception:
        return False


def snapshot(state, listening_mode):
    with _lock:
        voice, ears, listener = _voice, _ears, _listener
        result = {"startup": _phase, "ai_service": _api, "recognition": dict(_recognition),
                  "text_mode": _text_mode, "output_error": _output_error}
    now = time.monotonic()
    mic_active = bool(ears and stream_active(ears.stream))
    # An open device alone doesn't establish a working recognition pipeline.
    mic_receiving = bool(mic_active and now - ears.last_input < 2)
    processing = bool(ears and now - ears.last_processed < 2)
    listener_alive = bool(listener and listener.is_alive())
    level = float(ears.level) if mic_receiving and ears else 0.0
    player = voice._player if voice else None
    result.update(
        state=state, listening_mode=listening_mode,
        microphone=str(ears.mic)[:160] if ears else None,
        microphone_active=mic_active, microphone_receiving=mic_receiving,
        processing=processing, listener_alive=listener_alive,
        input_level=round(min(1.0, max(0.0, level)), 4) if math.isfinite(level) else 0.0,
        voice_lock=ears.voiceprint is not None if ears else None,
        output=str(player.device_name)[:160] if player else None,
        output_active=stream_active(player._stream) if player else False,
        speech_pending=bool(voice and not voice._idle.is_set()),
    )
    return result
