"""Hidden suspended child creation, Job ownership before any recipe runs."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess
import time

if __package__:
    from .build_process import BuildProcessError
else:
    from build_process import BuildProcessError


class _BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t), ("active_process_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [("times", ctypes.c_int64 * 4), ("faults", wintypes.DWORD),
                ("total", wintypes.DWORD), ("active", wintypes.DWORD), ("terminated", wintypes.DWORD)]


class _Thread(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("id", wintypes.DWORD),
                ("owner", wintypes.DWORD), ("priority", wintypes.LONG), ("delta", wintypes.LONG),
                ("flags", wintypes.DWORD)]


def _require(value, reason):
    if not value:
        raise BuildProcessError(reason)


class _Job:
    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Thread32First": ([wintypes.HANDLE, ctypes.POINTER(_Thread)], wintypes.BOOL),
            "Thread32Next": ([wintypes.HANDLE, ctypes.POINTER(_Thread)], wintypes.BOOL),
            "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "GetProcessIdOfThread": ([wintypes.HANDLE], wintypes.DWORD),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        }
        for name, (args, result) in signatures.items():
            getattr(self.api, name).argtypes = args
            getattr(self.api, name).restype = result
        self.handle = self.api.CreateJobObjectW(None, None)
        _require(self.handle, "job-create")
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise BuildProcessError("job-configure")

    def assign_and_resume(self, process, deadline):
        _require(self.api.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))),
                 "job-assignment")
        snapshot = self.api.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD.
        _require(snapshot not in (None, ctypes.c_void_p(-1).value), "thread-snapshot")
        found = None
        try:
            row = _Thread(size=ctypes.sizeof(_Thread))
            more = self.api.Thread32First(snapshot, ctypes.byref(row))
            count = 0
            while more:
                count += 1
                _require(count <= 262144 and time.monotonic() < deadline, "thread-snapshot-limit")
                if row.owner == process.pid:
                    _require(found is None, "suspended-initial-thread")
                    found = row.id
                row.size = ctypes.sizeof(_Thread)
                more = self.api.Thread32Next(snapshot, ctypes.byref(row))
            _require(found is not None, "suspended-initial-thread")
            # Querying the opened handle defeats thread-ID reuse between snapshot
            # and OpenThread; the still-owned process handle reserves its PID.
            thread = self.api.OpenThread(0x0802, False, found)
            _require(thread, "initial-thread-open")
            try:
                _require(self.api.GetProcessIdOfThread(thread) == process.pid, "initial-thread-owner")
                _require(self.api.ResumeThread(thread) == 1, "initial-thread-resume")
            finally:
                self.api.CloseHandle(thread)
        finally:
            self.api.CloseHandle(snapshot)

    def active(self):
        value = _Accounting()
        _require(self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(value),
                 ctypes.sizeof(value), None), "job-accounting")
        return value.active

    def terminate(self):
        _require(self.api.TerminateJobObject(self.handle, 1), "job-terminate")

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class OwnedProcess:
    def __init__(self):
        self.process = None
        self.finished = False
        self.cleanup_deadline = None
        self.job = _Job()

    def spawn(self, command, cwd, env, deadline):
        self.process = subprocess.Popen(
            command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, close_fds=True,
            creationflags=0x00000004 | 0x08000000,  # CREATE_SUSPENDED | CREATE_NO_WINDOW.
        )
        self.job.assign_and_resume(self.process, deadline)

    def exited(self):
        return self.process.poll() is not None

    def finish(self, deadline):
        if self.finished or self.process is None:
            return
        self.cleanup_deadline = min(deadline, self.cleanup_deadline or deadline)
        deadline = self.cleanup_deadline
        # Also covers assignment failure: the still-suspended unassigned leader
        # cannot have executed recipe code or created descendants.
        if self.process.poll() is None:
            self.process.kill()
        self.job.terminate()
        self.process.wait(timeout=max(0, deadline - time.monotonic()))
        while self.job.active():
            _require(time.monotonic() < deadline, "process-cleanup")
            time.sleep(0.01)
        self.finished = True

    def close(self):
        self.job.close()
        if self.process is not None:
            for stream in (self.process.stdout, self.process.stderr):
                if stream is not None:
                    stream.close()
            # Popen normally retains this handle until GC; release it now so a
            # caller retaining the CompletedProcess does not prolong ownership.
            self.process._handle.Close()
