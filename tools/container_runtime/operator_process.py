"""Finite Docker CLI ownership with bounded stdin/output and cancellation."""
import os
import selectors
import signal
import subprocess
import time

from native_runtime.common import InstallError, require


def run(arguments, input_file=None, seconds=20):
    require(os.name == 'posix', 'operator-linux-or-wsl-required')
    process = subprocess.Popen(arguments, stdin=input_file or subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/nonexistent'})
    deadline, raw, diagnostics = time.monotonic() + seconds, bytearray(), bytearray()
    handlers = {}
    def cancelled(*_):
        raise InstallError('operator-worker-cancelled-outcome-unconfirmed')
    try:
        for event in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            handlers[event] = signal.signal(event, cancelled)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            selector.register(process.stderr, selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < deadline, 'operator-channel-timeout-outcome-unconfirmed')
                for key, _ in selector.select(min(0.1, deadline - time.monotonic())):
                    data = os.read(key.fd, 8192)
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        (raw if key.fileobj is process.stdout else diagnostics).extend(data)
                        require(len(raw) + len(diagnostics) <= 524288, 'operator-channel-output-bound')
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        require(process.returncode == 0, 'operator-channel-or-permission-failed')
        return bytes(raw)
    except subprocess.TimeoutExpired as error:
        raise InstallError('operator-channel-timeout-outcome-unconfirmed') from error
    finally:
        for event, handler in handlers.items():
            signal.signal(event, handler)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        process.stdout.close(); process.stderr.close()
