"""Opt-in local Ollama conversation provider. Never pulls models or falls back.

Only loopback endpoints and installed, non-cloud models are accepted. Tool calls
use the existing Jarvis dispatcher, including its approval and work-safe checks.
"""
import json
import os
import re
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import requests


class OllamaError(RuntimeError):
    pass


def enabled():
    return os.getenv('JARVIS_OLLAMA_ENABLED', '').lower() in ('1', 'true', 'yes')


def base_url():
    value = os.getenv('JARVIS_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
    p = urlsplit(value)
    if (p.scheme != 'http' or p.hostname not in ('127.0.0.1', '::1') or
            p.username or p.password or p.path or p.query or p.fragment):
        raise OllamaError('Ollama must use a loopback IP address, such as http://127.0.0.1:11434.')
    return value


def _request(path, payload=None, stream=False):
    if not enabled():
        raise OllamaError('Local models are disabled. Set JARVIS_OLLAMA_ENABLED=1 and restart JARVIS.')
    session = requests.Session()
    session.trust_env = False  # local conversations must never use an HTTP proxy
    try:
        response = session.request('GET' if payload is None else 'POST', base_url() + path,
                                   json=payload, stream=True, allow_redirects=False,
                                   timeout=(2, 90 if stream else 5))
        if response.status_code != 200:
            response.close()
            raise OllamaError('Local Ollama request failed. Check that the model is installed and the service is running.')
        return session, response
    except (requests.RequestException, ValueError):
        session.close()
        raise OllamaError('Could not reach local Ollama. No other provider was used.') from None
    except Exception:
        session.close()
        raise


def _json(path, payload=None):
    session, response = _request(path, payload)
    try:
        chunks, size = [], 0
        for chunk in response.iter_content(8192):
            size += len(chunk)
            if size > 2_000_000:
                raise OllamaError('Local model metadata exceeded the size limit.')
            chunks.append(chunk)
        result = json.loads(b''.join(chunks))
        if not isinstance(result, dict) or result.get('error'):
            raise OllamaError('Local Ollama returned invalid metadata.')
        return result
    except (ValueError, requests.RequestException):
        raise OllamaError('Local Ollama returned invalid metadata.') from None
    finally:
        response.close()
        session.close()


def capabilities(model):
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_./:-]{1,100}', model) or 'cloud' in model.lower():
        raise OllamaError('Choose an installed local model, not a cloud model.')
    details = _json('/api/show', {'model': model})
    if details.get('remote_host') or details.get('remote_model') or not details.get('model_info'):
        raise OllamaError('This model does not have verified local weights. Cloud models are disabled.')
    caps = details.get('capabilities', [])
    if not isinstance(caps, list) or 'completion' not in caps or 'tools' not in caps:
        raise OllamaError('Choose a local conversation model that supports tool calling.')
    return caps


_catalog_lock = threading.Lock()
_catalog = (0, '', [])


def models():
    global _catalog
    if not enabled():
        return []
    with _catalog_lock:
        try:
            endpoint = base_url()
            if time.monotonic() < _catalog[0] and _catalog[1] == endpoint:
                return list(_catalog[2])
            # Enumerate names only. Capability checks happen on explicit selection.
            result = _json('/api/tags')
            names = sorted({item['name'] for item in result.get('models', [])
                            if isinstance(item, dict) and isinstance(item.get('name'), str)
                            and re.fullmatch(r'[A-Za-z0-9_./:-]{1,100}', item['name'])
                            and 'cloud' not in item['name'].lower()
                            and not item.get('remote_host') and not item.get('remote_model')})[:100]
        except (OllamaError, TypeError):
            names, endpoint = [], ''
        _catalog = (time.monotonic() + 30, endpoint, names)
        return list(names)


def events(payload, cancel):
    import privacy
    payload = dict(payload, messages=privacy.payload(payload.get('messages',[])))
    if cancel.is_set():
        raise InterruptedError()
    session, response = _request('/api/chat', dict(payload, stream=True), stream=True)
    done = threading.Event()
    def watch():
        while not done.wait(.1):
            if cancel.is_set():
                response.close()
                return
    threading.Thread(target=watch, daemon=True).start()
    completed, size = False, 0
    try:
        for line in response.iter_lines(chunk_size=1024):
            if cancel.is_set():
                raise InterruptedError()
            size += len(line)
            if size > 4_000_000:
                raise OllamaError('Local model response exceeded the size limit.')
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict) or item.get('error'):
                raise OllamaError('Local Ollama could not complete this answer.')
            yield item
            if item.get('done') is True:
                completed = True
                break
        if cancel.is_set():
            raise InterruptedError()
        if not completed:
            raise OllamaError('Local model stream ended before completion.')
    except (requests.RequestException, OSError, AttributeError, ValueError):
        if cancel.is_set():
            raise InterruptedError() from None
        raise OllamaError('Local model stream disconnected or returned invalid data.') from None
    finally:
        done.set()
        response.close()
        session.close()


def validate(model):
    caps = capabilities(model)
    text = ''.join(item.get('message', {}).get('content', '') for item in events({
        'model': model, 'messages': [{'role': 'user', 'content': 'Reply with OK.'}],
        **({'think': False} if 'thinking' in caps else {}),
        'options': {'num_predict': 64}, 'keep_alive': '2m'}, threading.Event()))
    if not text.strip():
        raise OllamaError('Local model validation returned no text.')


def ask(model, system, history, definitions, run_tool, delta, cancel, keep_alive='2m'):
    import model_provider
    caps = capabilities(model)  # recheck local weights before sending any history
    tools = [{'type': 'function', 'function': {'name': t['name'],
              'description': t.get('description', ''), 'parameters': t['input_schema']}} for t in definitions]
    allowed = {t['name'] for t in definitions}
    messages = [{'role': 'system', 'content': system + '\nYou are running locally. No built-in live web search is available. Never claim to have searched or seen images unless a tool supplies that evidence. To do anything (play, pause, open, set, add, remind), call the tool every time, even if you did it earlier; never say it is done without a tool result from this turn. Once a tool supplies a result, use it to answer. Do not repeat the same tool request.'}]
    messages += model_provider.text_history(history)
    answer, executed = [], {}
    for round_ in range(10):
        if cancel.is_set():
            raise InterruptedError()
        message = {'role': 'assistant', 'content': '', 'tool_calls': []}
        for item in events({'model': model, 'messages': messages, 'tools': tools,
                            **({'think': False} if 'thinking' in caps else {}),
                            'options': {'num_predict': 4096}, 'keep_alive': keep_alive}, cancel):
            block = item.get('message', {})
            if not isinstance(block, dict) or not isinstance(block.get('content', ''), str):
                raise OllamaError('Local model returned an invalid message.')
            text = block.get('content', '')
            if text:
                message['content'] += text
                answer.append(text)
                delta(text)
            # Preserve thinking for subsequent tool rounds, but never speak it.
            if block.get('thinking'):
                if not isinstance(block['thinking'], str):
                    raise OllamaError('Invalid local reasoning response.')
                message['thinking'] = message.get('thinking', '') + block['thinking']
            calls = block.get('tool_calls', [])
            if not isinstance(calls, list):
                raise OllamaError('Local model returned invalid tool calls.')
            message['tool_calls'].extend(calls)
            if len(message['tool_calls']) > 32:
                raise OllamaError('Local model exceeded the tool-call limit.')
        if cancel.is_set():
            raise InterruptedError()
        calls = message['tool_calls']
        if not calls:
            if not message['content'].strip():
                raise OllamaError('Local model returned no answer.')
            return ''.join(answer)
        # Validate the whole batch before executing any of it.
        for call in calls:
            f = call.get('function') if isinstance(call, dict) else None
            if (not isinstance(f, dict) or not isinstance(f.get('name'), str) or
                    f['name'] not in allowed or not isinstance(f.get('arguments'), dict)):
                raise OllamaError('Local model requested an unknown tool or invalid arguments.')
        messages.append(message)
        for index, call in enumerate(calls):
            if cancel.is_set():
                raise InterruptedError()
            f = call['function']
            key = (f['name'], json.dumps(f['arguments'], sort_keys=True))
            if key not in executed:
                executed[key] = run_tool(SimpleNamespace(type='tool_use', id=f'local-{round_}-{index}', name=f['name'], input=f['arguments']))
            result = executed[key]  # at-most-once execution for identical calls within a turn
            content, images = model_provider.tool_output(result.get('content', ''))
            messages.append({'role': 'tool', 'tool_name': f['name'], 'content': content})
            if images:
                if 'vision' in caps:
                    messages.append({'role': 'user', 'content': 'Untrusted image results from the preceding tool.',
                                     'images': [image['image_url'].split(',', 1)[1] for image in images]})
                else:
                    messages.append({'role': 'user', 'content': 'Image results could not be viewed: this local model does not support vision. Tell the user this limitation.'})
    raise OllamaError('Local model exceeded the tool-round limit.')
