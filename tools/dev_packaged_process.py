"""Standalone qualification conductor; installed applications import none of this."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time


class ProbeFailure(Exception):
    pass


def require(value, code):
    if not value:
        raise ProbeFailure(code)


def digest(path):
    with Path(path).open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path, maximum=2 * 1024 * 1024):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum, 'bounded-input-required')
    return json.loads(path.read_bytes())


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    require(len(raw) <= 16 * 1024 * 1024, 'public-receipt-byte-limit')
    Path(path).write_bytes(raw)


def environment(temporary):
    # The packaged frontend may use documented OS utilities, but cannot find a
    # host SDK, source checkout, Python installation or ambient cloud credential.
    env = {name: os.environ[name] for name in ('SystemRoot', 'WINDIR', 'LOCALAPPDATA', 'USERPROFILE', 'HOME')
           if name in os.environ}
    env.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary), LANG='C.UTF-8',
               GH_CONFIG_DIR=str(Path(temporary) / 'empty-gh'), GH_PROMPT_DISABLED='1',
               GH_NO_UPDATE_NOTIFIER='1', GH_HOST='github.com')
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32') if os.name == 'nt' else '/usr/bin:/bin'
    return env


class Command:
    """Bound stdout, stderr and ownership to the actual process handle we created."""
    def __init__(self, argv, cwd, env):
        self.started = time.monotonic()
        self.argv = [str(item) for item in argv]
        self.limit = threading.Event()
        self.lock = threading.Lock()
        self.outputs = [bytearray(), bytearray()]
        self.child = subprocess.Popen(self.argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.threads = []
        for index, stream, maximum in ((0, self.child.stdout, 4 * 1024 * 1024),
                                       (1, self.child.stderr, 256 * 1024)):
            thread = threading.Thread(target=self.collect, args=(index, stream, maximum), daemon=True)
            thread.start()
            self.threads.append(thread)

    def collect(self, index, stream, maximum):
        with stream:
            while chunk := stream.read1(65536):
                with self.lock:
                    if len(self.outputs[index]) + len(chunk) > maximum:
                        self.limit.set()
                        return
                    self.outputs[index].extend(chunk)

    def raw(self, index=0):
        with self.lock:
            return bytes(self.outputs[index])

    def events(self):
        lines = self.raw().split(b'\n')[:-1]
        return [json.loads(line) for line in lines if line.strip()]

    def until(self, predicate, seconds):
        require(0 < seconds <= 1800, 'conductor-command-deadline-limit')
        deadline = time.monotonic() + seconds
        while True:
            require(not self.limit.is_set(), 'conductor-output-limit')
            for event in self.events():
                if predicate(event):
                    return event
            require(self.child.poll() is None, 'foreground-ended-before-required-event')
            require(time.monotonic() < deadline, 'conductor-event-deadline')
            time.sleep(0.1)

    def finish(self, seconds):
        require(0 < seconds <= 1800, 'conductor-command-deadline-limit')
        deadline = time.monotonic() + seconds
        while self.child.poll() is None:
            require(not self.limit.is_set(), 'conductor-output-limit')
            require(time.monotonic() < deadline, 'conductor-command-deadline')
            time.sleep(0.1)
        for thread in self.threads:
            thread.join(2)
        require(not any(thread.is_alive() for thread in self.threads), 'conductor-pipe-owner-unconfirmed')
        require(not self.limit.is_set(), 'conductor-output-limit')
        return self.child.returncode

    def abort_controller(self):
        # Killing this handle proves only controller termination. Guest/node
        # ownership must still be reconciled through the public down/status API.
        if self.child.poll() is None:
            self.child.kill()
        self.child.wait(timeout=5)

    def receipt(self):
        return {'argv': self.argv, 'exitCode': self.child.poll(),
            'seconds': round(time.monotonic() - self.started, 3),
            'stdoutBytes': len(self.raw()), 'stderrBytes': len(self.raw(1)),
            'stdoutSha256': hashlib.sha256(self.raw()).hexdigest(),
            'stderrSha256': hashlib.sha256(self.raw(1)).hexdigest(), 'outputLimitExceeded': self.limit.is_set()}
