"""Best-effort local text redaction. Never modifies authentication headers or image bytes."""
import json
import re
from pathlib import Path
import threading

STORE = Path(__file__).resolve().parent / 'data' / 'privacy.json'
LOCK = threading.RLock()
PATTERNS = [
    ('private key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----')),
    ('credential', re.compile(r'\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b')),
    ('bearer token', re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}')),
    ('credential assignment', re.compile(r'''(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|client[_ -]?secret)["']?\s*[:=]\s*["']?[^\s,"'<>}]{4,}''')),
    ('SSN', re.compile(r'\b\d{3}-\d{2}-\d{4}\b')),
    ('JWT', re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b')),
    ('service token', re.compile(r'\b(?:xox[baprs]-[A-Za-z0-9-]{10,}|\d{8,12}:[A-Za-z0-9_-]{30,})\b')),
    ('URL credentials', re.compile(r'https?://[^\s/@:]+:[^\s/@]+@',re.I)),
]


def settings():
    try:
        data = json.loads(STORE.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('terms'), list):
            raise ValueError('Invalid privacy settings.')
        return data
    except FileNotFoundError:
        return {'terms': [], 'email': False, 'phone': False}


def configure(terms, email=False, phone=False):
    if not isinstance(terms, list) or len(terms) > 100 or any(not isinstance(t, str) or not 3 <= len(t) <= 200 for t in terms):
        raise ValueError('Use at most 100 exact phrases, 3–200 characters each.')
    if type(email) is not bool or type(phone) is not bool:
        raise ValueError('Email and phone settings must be true or false.')
    data = {'terms': list(dict.fromkeys(terms)), 'email': email, 'phone': phone}
    with LOCK:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        temp = STORE.with_suffix('.tmp')
        temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        temp.replace(STORE)
    return data


def redact(text):
    if not isinstance(text, str):
        return text
    config = settings()
    for term in sorted(config['terms'], key=len, reverse=True):
        text = re.sub(re.escape(term), '[REDACTED: selected text]', text, flags=re.I)
    for name, pattern in PATTERNS:
        text = pattern.sub('[REDACTED: ' + name + ']', text)
    if config.get('email'):
        text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '[REDACTED: email]', text)
    if config.get('phone'):
        text = re.sub(r'(?<!\w)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\w)', '[REDACTED: phone]', text)
    return text


def payload(value):
    """Copy SDK blocks/dicts while preserving binary images and protocol identifiers."""
    if hasattr(value, 'model_dump'):
        value = value.model_dump(exclude_none=True)
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [payload(v) for v in value]
    if isinstance(value, dict):
        return {k: '[REDACTED: credential]' if k.casefold() in {'password','api_key','access_token','refresh_token','client_secret'}
                else v if (k == 'data' and value.get('type') == 'base64') or k in {'image_url', 'imageUrl', 'id', 'call_id', 'tool_use_id',
                              'type', 'role', 'name', 'model', 'media_type'} else payload(v)
                for k, v in value.items()}
    return value
