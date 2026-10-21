"""Control an app's Windows audio session without pressing global media keys."""
import comtypes
from pycaw.pycaw import AudioUtilities

import cc_guard


def control(action, app="", percent=50):
    if action not in ("list", "volume", "mute", "unmute"):
        raise ValueError("Choose list, volume, mute or unmute.")
    if action == "volume" and not 0 <= percent <= 100:
        raise ValueError("Volume must be between zero and one hundred.")
    comtypes.CoInitialize()
    try:
        sessions = []
        for session in AudioUtilities.GetAllSessions():
            try:
                process = session.Process
                if not process:
                    continue
                name = process.name()
            except Exception:
                continue
            if cc_guard.decide("Read", {"file_path": name})[0] == "allow":
                sessions.append((name, session.SimpleAudioVolume))
        if action == "list":
            return "\n".join(f"{name}: {round(vol.GetMasterVolume()*100)}%, {'muted' if vol.GetMute() else 'unmuted'}" for name, vol in sessions) or "No app audio sessions found on the default output."
        query = app.lower().strip().removesuffix(".exe")
        names = sorted({name for name, _ in sessions if query and query == name.lower().removesuffix(".exe")})
        if not names:
            names = sorted({name for name, _ in sessions if query and query in name.lower()})
        if len(names) != 1:
            raise ValueError("Specify one app from the audio-session list. A browser's volume applies to all its tabs.")
        selected = [(name, vol) for name, vol in sessions if name == names[0]]
        for _, volume in selected:
            if action == "volume":
                volume.SetMasterVolume(percent / 100, None)
                if abs(volume.GetMasterVolume()*100 - percent) > 1:
                    raise RuntimeError("Windows did not confirm the volume change.")
            else:
                muted = action == "mute"
                volume.SetMute(muted, None)
                if bool(volume.GetMute()) != muted:
                    raise RuntimeError("Windows did not confirm the mute change.")
        return f"{names[0]} volume set to {percent}%." if action == "volume" else f"{names[0]} {'muted' if action == 'mute' else 'unmuted'}."
    finally:
        comtypes.CoUninitialize()
