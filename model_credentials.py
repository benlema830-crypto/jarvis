"""Local OpenAI credential storage protected by the current Windows account."""
import base64
import os
from pathlib import Path
import win32crypt

STORE = Path(__file__).resolve().parent / 'data' / 'openai-key.dpapi'


def load_openai_key():
    if STORE.is_file():
        return win32crypt.CryptUnprotectData(base64.b64decode(STORE.read_bytes()), None, None, None, 0)[1].decode()
    return os.getenv('OPENAI_API_KEY', '')


def save_openai_key(key):
    if not key or any(c.isspace() for c in key):
        raise ValueError('Enter a key without spaces or line breaks.')
    protected = win32crypt.CryptProtectData(key.encode(), 'JARVIS OpenAI', None, None, None, 0)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    temp = STORE.with_suffix('.tmp')
    temp.write_bytes(base64.b64encode(protected))
    os.replace(temp, STORE)
