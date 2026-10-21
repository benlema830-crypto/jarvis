"""Finite, sequential reference-parity build queue through the running assistant."""
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'data' / 'reports'
STATE = REPORTS / 'overnight-queue.json'
STOP = ROOT / 'data' / 'STOP-OVERNIGHT'
LOCK = ROOT / 'data' / 'overnight-queue.lock'
BASE = 'http://127.0.0.1:7778'


def api(path, body=None):
    request = Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def save(status, **details):
    payload = dict(status=status, updated=time.strftime('%Y-%m-%d %H:%M:%S'),
                   pid=os.getpid(), **details)
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    os.replace(temp, STATE)


def session_list():
    data = api('/sessions')
    if not isinstance(data.get('sessions'), list):
        raise RuntimeError('Unexpected session response; no task dispatched.')
    return data['sessions']


def check_deadline(deadline):
    if STOP.exists():
        raise RuntimeError('Stop file found. No further stages will start.')
    if time.monotonic() >= deadline:
        raise RuntimeError('Three-hour queue limit reached. No further stages will start.')


def run():
    REPORTS.mkdir(parents=True, exist_ok=True)
    # Exclusive lock prevents overlapping launchers; stale locks require inspection.
    with LOCK.open('x', encoding='utf-8') as handle:
        handle.write(str(os.getpid()))
    stage = 0
    deadline = time.monotonic() + 3 * 60 * 60
    try:
        sessions = session_list()
        if any(s.get('name', '').startswith('Reference Night ') for s in sessions):
            raise RuntimeError('Reference-night sessions already exist; refusing to repeat work.')
        save('waiting_for_current_build', stage=0)
        while any(s.get('status') in ('running', 'waiting') for s in sessions):
            check_deadline(deadline)
            time.sleep(10)
            sessions = session_list()
        initial = next((s for s in sessions if s.get('name') == 'Jarvis Builder'), None)
        if initial and initial.get('status') != 'completed':
            raise RuntimeError('Initial voice build did not complete; inspect its report.')
        for stage in range(1, 5):
            check_deadline(deadline)
            name = f'Reference Night {stage}'
            task = (f'Read docs/plans/JARVIS-TARGET.txt and docs/plans/OVERNIGHT-SEQUENCE.txt. '
                    f'Implement only STAGE {stage} from OVERNIGHT-SEQUENCE.txt, following its '
                    f'common rules and 25-minute timebox. Save data/reports/OVERNIGHT-{stage}.txt. '
                    'This is the authorized reference-parity build. Do not run later stages yourself.')
            command = (f'Open a Codex agent session named {name} in the Jarvis project. '
                       f'Then use send_agent_task in work mode for that exact named session '
                       f'with this task: {task} Start it now; do not just explain it.')
            save('dispatching', stage=stage, session=name)
            # Never retry POST: an uncertain response may already have enqueued work.
            result = api('/command', {'text': command})
            if not result.get('ok'):
                raise RuntimeError('Command not accepted; no automatic retry.')
            acknowledged = False
            ack_deadline = time.monotonic() + 180
            while True:
                check_deadline(deadline)
                sessions = session_list()
                entry = next((s for s in sessions if s.get('name') == name), None)
                if entry and entry.get('task'):
                    acknowledged = True
                    status = entry.get('status')
                    save('running_stage', stage=stage, session=name,
                         agent_status=status, progress=entry.get('progress', ''))
                    if status in ('failed', 'interrupted'):
                        raise RuntimeError(f'{name}: {status}. {entry.get("report", "")}')
                    if status == 'completed':
                        (REPORTS / f'OVERNIGHT-{stage}-SESSION.txt').write_text(
                            entry.get('report', ''), encoding='utf-8')
                        break
                if not acknowledged and time.monotonic() >= ack_deadline:
                    raise RuntimeError('Task was not acknowledged within 3 minutes; no retry.')
                time.sleep(10)
        save('completed', stage=4, report='data/reports/OVERNIGHT-FINAL.txt')
    except Exception as exc:
        save('stopped', stage=stage, reason=str(exc))
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == '__main__':
    if '--check' in sys.argv:
        assert (ROOT / 'docs/plans/JARVIS-TARGET.txt').is_file()
        assert (ROOT / 'docs/plans/OVERNIGHT-SEQUENCE.txt').is_file()
        print('Queue prerequisites OK; live sessions:', len(session_list()))
    else:
        run()
