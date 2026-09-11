"""One finite Linux kubectl attach owner, without background reader threads."""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time

from tools.artifact_identity_runner.resources import process_stat
from tools.optimization_docker.owned import stamp
from tools.optimization_evidence.common import require

_SUBREAPER_ACTIVE = False


class _Subreaper:
    """A single main-thread owner temporarily adopts orphaned helper children."""
    def __init__(self):
        global _SUBREAPER_ACTIVE
        require(sys.platform == "linux" and threading.current_thread() is threading.main_thread()
                and not _SUBREAPER_ACTIVE, "kubernetes-attach-subreaper-owner")
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        self.libc.prctl.restype = ctypes.c_int
        self.previous = self.current()
        self.restored = False
        self._call(36, 1)  # PR_SET_CHILD_SUBREAPER
        _SUBREAPER_ACTIVE = True

    def _call(self, option, value):
        if self.libc.prctl(option, value, 0, 0, 0) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))

    def current(self):
        value = ctypes.c_int()
        self._call(37, ctypes.addressof(value))  # PR_GET_CHILD_SUBREAPER
        require(value.value in (0, 1), "kubernetes-attach-subreaper-state")
        return value.value

    def close(self):
        global _SUBREAPER_ACTIVE
        try:
            self._call(36, self.previous)
            self.restored = self.current() == self.previous
            require(self.restored, "kubernetes-attach-subreaper-restore")
        finally:
            _SUBREAPER_ACTIVE = False


class Attach:
    def __init__(self, argv, directory: Path):
        self.argv, self.started = list(argv), stamp()
        self.stdout = (directory / "attach-stdout.ndjson").open("xb")
        self.stderr = (directory / "attach-stderr.bin").open("xb")
        self.child = self.selector = None
        self.buffer = bytearray()
        self.bytes = {"stdout": 0, "stderr": 0, "stdin": 0}
        self.hashes = {key: hashlib.sha256() for key in self.bytes}
        self.closed = self.forced = False
        self.start_ticks = None
        self.subreaper = None
        self.descendant_reaps = []
        self.group_gone = True
        try:
            self.subreaper = _Subreaper()
            self.child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True)
            self.group_gone = False
            self.start_ticks = process_stat(self.child.pid)[19]
            self.selector = selectors.DefaultSelector()
            for stream, role in ((self.child.stdout, "stdout"), (self.child.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                self.selector.register(stream, selectors.EVENT_READ, role)
            os.set_blocking(self.child.stdin.fileno(), False)
        except BaseException:
            self.close(force=True)
            raise

    def _read(self, timeout):
        for key, _ in self.selector.select(timeout):
            if key.data == "stdin":
                continue
            block = os.read(key.fd, 65536)
            if not block:
                self.selector.unregister(key.fileobj)
                continue
            role = key.data
            self.bytes[role] += len(block)
            require(self.bytes[role] <= (1024**2 if role == "stdout" else 256 * 1024),
                    "kubernetes-attach-output-bound")
            self.hashes[role].update(block)
            getattr(self, role).write(block)
            getattr(self, role).flush()
            if role == "stdout":
                self.buffer.extend(block)
                require(len(self.buffer) <= 1024**2, "kubernetes-attach-buffer-bound")

    def next_line(self, timeout=120):
        until = time.monotonic() + timeout
        while True:
            index = self.buffer.find(b"\n")
            if index >= 0:
                require(index + 1 <= 4096, "kubernetes-attach-line-bound")
                line = bytes(self.buffer[:index + 1])
                del self.buffer[:index + 1]
                return line
            require(len(self.buffer) <= 4096, "kubernetes-attach-line-bound")
            if not any(key.data == "stdout" for key in self.selector.get_map().values()):
                require(not self.buffer, "kubernetes-attach-partial-line")
                raise EOFError("kubernetes-attach-eof")
            require(time.monotonic() < until, "kubernetes-attach-read-deadline")
            self._read(min(0.1, until - time.monotonic()))

    def send_line(self, line):
        require(isinstance(line, bytes) and 1 < len(line) <= 64 * 1024
                and line.endswith(b"\n") and b"\n" not in line[:-1], "kubernetes-attach-command-line")
        until, view = time.monotonic() + 15, memoryview(line)
        self.selector.register(self.child.stdin, selectors.EVENT_WRITE, "stdin")
        try:
            while view:
                require(time.monotonic() < until, "kubernetes-attach-write-deadline")
                self._read(0.01)
                try:
                    count = os.write(self.child.stdin.fileno(), view)
                except BlockingIOError:
                    continue
                require(count > 0, "kubernetes-attach-short-write")
                self.bytes["stdin"] += count
                require(self.bytes["stdin"] <= 1024**2, "kubernetes-attach-input-bound")
                self.hashes["stdin"].update(view[:count])
                view = view[count:]
        finally:
            self.selector.unregister(self.child.stdin)

    def _reap_descendants(self):
        """After the leader is reaped, wait only for its adopted process group."""
        require(self.child.returncode is not None, "kubernetes-attach-leader-not-reaped")
        until = time.monotonic() + 5
        signalled = False
        while True:
            try:
                pid, status = os.waitpid(-self.child.pid, os.WNOHANG)
            except ChildProcessError:
                break
            if pid:
                self.descendant_reaps.append({"process_id": pid, "exit_code": os.waitstatus_to_exitcode(status),
                                               "reaped_nanos": stamp()})
                require(len(self.descendant_reaps) <= 256, "kubernetes-attach-descendant-bound")
            elif not signalled:
                # WNOHANG=0 proves that an adopted child still pins this group;
                # no signal is sent based only on a potentially reused PGID.
                self.forced = True
                try:
                    os.killpg(self.child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                signalled = True
            else:
                time.sleep(0.01)
            require(time.monotonic() < until, "kubernetes-attach-descendant-deadline")
        try:
            os.killpg(self.child.pid, 0)
        except ProcessLookupError:
            self.group_gone = True
        require(self.group_gone, "kubernetes-attach-process-group-remains")

    def close(self, *, force=False):
        if self.closed:
            return self.receipt
        failure = None
        try:
            if self.child is not None:
                until = time.monotonic() + (0 if force else 15)
                while self.selector is not None and self.selector.get_map() and time.monotonic() < until:
                    self._read(0.05)
                exited = os.waitid(os.P_PID, self.child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                while exited is None and not force and time.monotonic() < until:
                    time.sleep(0.01)
                    exited = os.waitid(os.P_PID, self.child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if force or exited is None or self.selector is not None and self.selector.get_map():
                    self.forced = True
                    try:
                        os.killpg(self.child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if self.selector is not None:
                    until = time.monotonic() + 5
                    while self.selector.get_map() and time.monotonic() < until:
                        self._read(0.05)
                    require(not self.selector.get_map(), "kubernetes-attach-streams-not-closed")
                if not force:
                    require(not self.buffer, "kubernetes-attach-unconsumed-output")
                self.child.wait(timeout=5)
                self._reap_descendants()
        except BaseException as error:
            failure = type(error).__name__
            if self.child is not None:
                self.forced = True
                if self.child.returncode is None:
                    try:
                        os.killpg(self.child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.child.wait(timeout=5)
                self._reap_descendants()
            raise
        finally:
            if self.child is not None:
                for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
                    stream.close()
            if self.selector is not None:
                self.selector.close()
            self.stdout.close()
            self.stderr.close()
            restore_error = None
            if self.subreaper is not None:
                try:
                    self.subreaper.close()
                except BaseException as error:
                    restore_error = error
                    failure = failure or type(error).__name__
            self.closed = True
            self.receipt = {"argv": self.argv, "process_id": None if self.child is None else self.child.pid,
                "start_time_ticks": self.start_ticks, "started_nanos": self.started,
                "finished_nanos": stamp(), "exit_code": None if self.child is None else self.child.returncode,
                "reaped": self.child is not None and self.child.returncode is not None,
                "output_closed": True, "forced_kill": self.forced, "failure": failure,
                "process_group_gone": self.group_gone, "descendant_reaps": self.descendant_reaps,
                "subreaper": None if self.subreaper is None else {"previous": self.subreaper.previous,
                    "enabled": True, "restored": self.subreaper.restored},
                "streams": {key: {"bytes": str(self.bytes[key]), "sha256": "sha256:" + self.hashes[key].hexdigest()}
                            for key in self.bytes}}
            if restore_error is not None:
                raise restore_error
        return self.receipt
