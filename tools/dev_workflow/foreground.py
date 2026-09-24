"""An explicit foreground controller owns the WSL session lifetime."""
from contextlib import contextmanager
import subprocess
import time

from tools import build_process
from tools.build_process_signals import owned_cancellation
from . import backend, process, wsl
from .common import DevError, require


@contextmanager
def lease(connection):
    if connection.config['kind'] != 'wsl2':
        yield lambda: None
        return
    config = connection.config
    wsl.verify_workspace(connection.cwd.parent, connection.workspace, config)
    # One unprivileged, silent session per foreground workspace. Its stdin is a
    # private pipe: controller exit closes it, including abrupt Windows death.
    # No global idle setting, background Windows service or shell is involved.
    argv = [backend.wsl_executable(), '--distribution', config['distribution'], '--user', config['user'],
            '--exec', backend.GUEST_PYTHON, '-I', '-c', 'import os; os.read(0,1)']
    owner = build_process._new_owner()
    with owned_cancellation() as cancellation:
        try:
            with cancellation.defer():
                owner.spawn(argv, connection.cwd, process.environment(), time.monotonic() + 10, stdin=subprocess.PIPE)
            def check():
                cancellation.check()
                require(not owner.exited(), 'workspace-session-lost-inspect-status')
            check()
            yield check
        finally:
            with cancellation.defer():
                try:
                    if owner.process is not None and owner.process.stdin is not None:
                        owner.process.stdin.close()
                        deadline = time.monotonic() + 2
                        while not owner.exited() and time.monotonic() < deadline:
                            time.sleep(0.02)
                    owner.finish(time.monotonic() + 5)
                except BaseException:
                    raise DevError('workspace-session-cleanup-unconfirmed', uncertain=True) from None
                finally:
                    owner.close()
