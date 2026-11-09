"""Keep a request's reply destination across its background work.

Only trusted ingress supplies a chat ID; prompt text never selects a destination.
Each worker captures its own origin, so later PC/phone turns cannot reroute it.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from queue import Queue


_telegram_chat = ContextVar('reply_telegram_chat', default=None)


@contextmanager
def telegram_turn(chat):
    token = _telegram_chat.set(chat)
    try:
        yield
    finally:
        _telegram_chat.reset(token)


def inherit(function):
    """Capture now, restore while running a worker (including its callbacks)."""
    chat = _telegram_chat.get()

    @wraps(function)
    def run(*args, **kwargs):
        with telegram_turn(chat):
            return function(*args, **kwargs)
    return run


class CommandQueue(Queue):
    """Attach the originating chat to deferred replies, without mutating callers."""

    def put(self, item, block=True, timeout=None):
        chat = _telegram_chat.get()
        if (chat is not None and isinstance(item, dict)
                and ('say' in item or 'prompt' in item)
                and 'telegram' not in item and 'phone' not in item):
            item = dict(item, telegram=chat)
        return super().put(item, block, timeout)
