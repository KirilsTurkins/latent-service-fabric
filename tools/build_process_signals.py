"""Main-thread cancellation over the entire owned process lifetime."""
from contextlib import contextmanager
import signal
import threading

_active = None


class _Cancellation:
    def __init__(self):
        self.previous = {}
        self.pending = None
        self.depth = 0

    def _deliver(self, number, frame=None):
        previous = self.previous[number]
        if callable(previous):
            previous(number, frame)
        elif number == signal.SIGTERM:
            # SIG_DFL would bypass Python finally blocks on Linux. Translate it
            # into an orderly exit until process ownership has been released.
            raise SystemExit(128 + number)
        else:
            raise KeyboardInterrupt()

    def handle(self, number, frame):
        # Never throw asynchronously: even entry into a Python finally/context
        # manager has bytecode-sized windows before its shield is established.
        if self.pending is None:
            self.pending = number

    def check(self):
        """Deliver only at an explicit point whose caller owns cleanup."""
        if not self.depth and self.pending is not None:
            number = self.pending
            self.pending = None
            self._deliver(number)

    @contextmanager
    def defer(self):
        """Record one cancellation while ownership acquisition/cleanup runs."""
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1
            self.check()


@contextmanager
def owned_cancellation():
    """Preserve ignored signals; restore host handlers after ownership release.

    Popen can be interrupted after OS child creation but before returning its
    owner. Acquisition/cleanup use defer; capture remains cancellable. Forced
    asynchronous exception injection and abrupt supervisor death are unsupported.
    """
    global _active
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("process-main-thread-required")
    if _active is not None:
        # Observer and subprocess scopes share pending state. An inner handler
        # must not consume a signal merely by handing it to another record-only
        # handler, and the outer owner must retain handlers between commands.
        yield _active
        return
    cancellation = _Cancellation()
    numbers = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        numbers.append(signal.SIGBREAK)
    try:
        for number in numbers:
            previous = signal.getsignal(number)
            if previous != signal.SIG_IGN:
                cancellation.previous[number] = previous
                signal.signal(number, cancellation.handle)
        _active = cancellation
        yield cancellation
    finally:
        _active = None
        for number, previous in cancellation.previous.items():
            signal.signal(number, previous)
        cancellation.check()
