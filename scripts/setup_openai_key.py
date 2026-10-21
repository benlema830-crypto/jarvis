"""User-facing masked credential entry; never print the credential or API errors."""
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import simpledialog, messagebox
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model_credentials import save_openai_key


def main():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    while True:
        key = simpledialog.askstring('JARVIS - OpenAI API key',
            'Paste your OpenAI API key below.\n\nIt will be encrypted for your Windows account.\n'
            'This checks API access without generating a paid answer.\n'
            'JARVIS still needs its OpenAI backend before it can switch.', show='*', parent=root)
        if key is None:
            break
        key = key.strip()
        if not key or any(c.isspace() for c in key):
            messagebox.showerror('JARVIS', 'Enter a key without whitespace.', parent=root)
            continue
        try:
            result = requests.get('https://api.openai.com/v1/models',
                headers={'Authorization': 'Bearer ' + key}, timeout=20, allow_redirects=False)
            if result.status_code != 200:
                messagebox.showerror('JARVIS', f'API access check returned HTTP {result.status_code}. '
                    'Check the key and its model-list permissions. Nothing was saved.', parent=root)
                continue
            models = sorted(item['id'] for item in result.json().get('data', []) if isinstance(item.get('id'), str))
            save_openai_key(key)
            status = ROOT / 'data/reports/openai-setup.json'
            status.parent.mkdir(parents=True, exist_ok=True)
            status.write_text(json.dumps({'credential_saved': True, 'models_access_verified': True,
                'inference_verified': False, 'models': models}, indent=2), encoding='utf-8')
            key = ''
            messagebox.showinfo('JARVIS', 'Key saved securely. OpenAI accepted the API access check.\n\n'
                'The overnight build can now use this connection.\n'
                'JARVIS has not switched models yet.', parent=root)
            break
        except (requests.RequestException, ValueError, OSError, KeyError):
            messagebox.showerror('JARVIS', 'Setup could not finish. Check your connection and try again. '
                'No credential details were logged.', parent=root)
    root.destroy()


if __name__ == '__main__':
    main()
