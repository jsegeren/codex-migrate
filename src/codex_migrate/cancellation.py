"""Cooperative CLI cancellation: never interrupt destination replacement."""

from contextlib import contextmanager
import signal
import sys


class Cancellation:
    def __init__(self):
        self._critical = False
        self._stopping = False

    def _handle(self, signum, frame):
        if self._stopping:
            return
        if self._critical:
            print("Finishing backup, replacement and verification before stopping. "
                  "Keep both Macs connected.", file=sys.stderr, flush=True)
            return
        self._stopping = True
        raise KeyboardInterrupt

    @contextmanager
    def signals(self):
        previous = {}
        try:
            for number in (signal.SIGINT, signal.SIGTERM):
                previous[number] = signal.signal(number, self._handle)
            yield self
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)

    @contextmanager
    def replacement(self):
        # Keep signals deferred through receipt construction as well. The
        # enclosing signals() scope restores handlers when the operation ends.
        self._critical = True
        yield
