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
_recoveries = {}
_recovering = set()
_recovery_started = False


def output_recovered():
    global _output_error
    with _lock:
        _output_error = False


def recover(component, automatic=False):
    """Serialized, bounded retry. Never repeats an AI request or a user's action."""
    if component not in {'microphone', 'output'}:
        raise ValueError('Choose microphone or output.')
    now = time.monotonic()
    with _lock:
        previous = _recoveries.get(component, {})
        if component in _recovering or now < previous.get('retry_at', 0):
            return {'component': component, 'status': 'waiting', 'message': 'Recovery already running or cooling down.'}
        device = _ears if component == 'microphone' else _voice
        if device is None:
            return {'component': component, 'status': 'unavailable', 'message': 'This audio component is not loaded.'}
        _recovering.add(component)
        attempts = previous.get('attempts', 0) + 1
        _recoveries[component] = {'status': 'recovering', 'attempts': attempts, 'at': time.time(), 'automatic': automatic}
    try:
        message = device.recover_input() if component == 'microphone' else device.recover_output()
        result = {'status': 'recovered', 'attempts': 0, 'message': message, 'retry_at': now+5}
    except Exception as exc:
        result = {'status': 'failed', 'attempts': attempts, 'message': f'Reconnect the device and try again ({type(exc).__name__}).',
                  'retry_at': time.monotonic()+min(60, 5*2**min(attempts, 4))}
    finally:
        with _lock:
            _recovering.discard(component)
    with _lock:
        _recoveries[component].update(result)
        return {'component': component, **{k: v for k, v in _recoveries[component].items() if k != 'retry_at'}}


def request_recovery(component):
    if component not in {'microphone', 'output'}:
        raise ValueError('Choose microphone or output.')
    threading.Thread(target=recover, args=(component,), daemon=True, name='audio-recovery').start()
    return {'status': 'requested', 'component': component}


def recovery_tick():
    import conversation_settings
    with _lock:
        voice, ears, ready = _voice, _ears, _phase == 'ready'
    if not ready:
        return
    if ears:
        ears.pause_seconds = conversation_settings.read()['pause_seconds']
        if not stream_active(ears.stream) or time.monotonic()-ears.last_input > 4:
            recover('microphone', automatic=True)
    if voice:
        player = voice._player
        stalled = time.monotonic()-getattr(player, 'last_callback', time.monotonic()) > 4
        if not stream_active(player._stream) or stalled:
            recover('output', automatic=True)


def start_recovery():
    global _recovery_started
    with _lock:
        if _recovery_started:
            return
        _recovery_started = True
    def watch():
        while True:
            time.sleep(3)
            try:
                recovery_tick()
            except Exception:
                pass  # a probe failure is retried; the voice threads remain independent
    threading.Thread(target=watch, daemon=True, name='audio-health').start()


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
        result['recovery'] = {name: {k: v for k, v in value.items() if k != 'retry_at'} for name, value in _recoveries.items()}
    import runtime_metrics
    result['resources'] = runtime_metrics.snapshot()
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
