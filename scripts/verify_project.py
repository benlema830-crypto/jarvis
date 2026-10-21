"""Run inert checks and save a concise local report. No live assistant requests."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = {'time_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'checks': []}
    for label, args in [
            ('unit', ['-m', 'unittest', 'discover', '-s', 'tests']),
            ('brain_browser', ['tests/check_brain_browser.py']),
            ('holo_browser', ['tests/check_holo_browser.py'])]:
        print(f'Running {label}...', flush=True)
        started = time.monotonic()
        try:
            result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True,
                                    encoding='utf-8', errors='replace', timeout=180,
                                    env=dict(os.environ, JARVIS_OLLAMA_ENABLED='0', PYTHONIOENCODING='utf-8'))
            output = result.stdout + result.stderr
            status = 'skipped' if 'SKIP:' in output else 'passed' if result.returncode == 0 else 'failed'
        except subprocess.TimeoutExpired:
            output, status = 'Timed out after 180 seconds.', 'failed'
        report['checks'].append({'name': label, 'status': status,
            'seconds': round(time.monotonic() - started, 2), 'output': output[-12000:]})
        print(f'{label}: {status}', flush=True)
    destination = ROOT / 'data/reports/project-verification.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Report: {destination}')
    return int(any(check['status'] == 'failed' for check in report['checks']))


if __name__ == '__main__':
    sys.exit(main())
