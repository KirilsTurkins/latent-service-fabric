"""Linux process-group ownership; no PID-based signal after leader reaping."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time

if __package__:
    from .build_process import BuildProcessError
else:
    from build_process import BuildProcessError


class OwnedProcess:
    def __init__(self):
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise BuildProcessError("child-reaper-unsupported")
        self.process = None
        self.finished = False
        self.owned = True
        self.cleanup_deadline = None

    def spawn(self, command, cwd, env, deadline):
        self.process = subprocess.Popen(
            command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            close_fds=True, start_new_session=True,
        )

    def exited(self):
        try:
            return os.waitid(os.P_PID, self.process.pid,
                             os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
        except ChildProcessError:
            # A competing reaper forfeits the PID reservation. Never signal a
            # potentially reused group ID after discovering that ownership loss.
            self.owned = False
            raise BuildProcessError("process-ownership") from None

    def _live_group_members(self, deadline):
        # Retaining the unreaped leader reserves this group ID. /proc is scanned
        # with fixed per-entry, total-entry and elapsed-time bounds; zombies no
        # longer execute and their parent/init owns eventual zombie reaping.
        with os.scandir("/proc") as entries:
            for index, entry in enumerate(entries):
                if index >= 65536 or time.monotonic() >= deadline:
                    raise BuildProcessError("process-cleanup")
                if not entry.name.isdecimal():
                    continue
                try:
                    with open(Path(entry.path) / "stat", "rb", buffering=0) as source:
                        stat = source.read(4097)
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if len(stat) > 4096:
                    raise BuildProcessError("process-cleanup")
                fields = stat.rpartition(b") ")[2].split()
                if len(fields) < 3:
                    raise BuildProcessError("process-cleanup")
                if int(fields[2]) == self.process.pid and fields[0] not in (b"Z", b"X"):
                    return True
        return False

    def finish(self, deadline):
        if self.finished or self.process is None:
            return
        self.cleanup_deadline = min(deadline, self.cleanup_deadline or deadline)
        deadline = self.cleanup_deadline
        if not self.owned:
            raise BuildProcessError("process-ownership")
        while True:
            self.exited()  # Revalidate the unreaped reservation before killpg.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if self.exited() and not self._live_group_members(deadline):
                break
            if time.monotonic() >= deadline:
                raise BuildProcessError("process-cleanup")
            # A fork racing the first group signal can join after that signal's
            # recipient scan. Re-signal live members while the leader is reserved.
            time.sleep(0.01)
        self.process.wait(timeout=max(0, deadline - time.monotonic()))
        self.finished = True

    def close(self):
        if self.process is not None:
            for stream in (self.process.stdout, self.process.stderr):
                if stream is not None:
                    stream.close()
