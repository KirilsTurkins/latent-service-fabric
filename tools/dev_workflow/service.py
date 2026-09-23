"""Linux supervisor owns one workspace node and a bounded private control socket."""
from __future__ import annotations

import ctypes
from pathlib import Path
import os
import selectors
import signal
import socket
import struct
import subprocess
import sys
import time

from tools.build_process_linux import OwnedProcess
from tools.native_runtime import checks
from tools.native_runtime.layout import Layout
from . import paths, process, state
from .common import DevError, MAX_LOG, decode, encode, require


def parent_death():
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    # The supervisor is single-threaded. Abrupt supervisor death kills its node.
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
        os._exit(125)


def socket_path(root: Path) -> Path:
    result = root / "control.sock"
    require(len(os.fsencode(result)) <= 100, "private-linux-home-path-too-long")
    return result


def request(root: Path, operation: str, *, timeout: float = 30) -> dict:
    require(operation in {"status", "logs", "down"}, "supervisor-command")
    paths.private_root(root)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(socket_path(root)))
        peer = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        require(struct.unpack("3i", peer)[1] == os.geteuid(), "supervisor-peer-owner")
        connection.sendall(encode({"operation": operation}))
        connection.shutdown(socket.SHUT_WR)
        data = bytearray()
        while raw := connection.recv(min(65536, MAX_LOG * 2 + 1 - len(data))):
            data.extend(raw)
            require(len(data) <= MAX_LOG * 2, "supervisor-response-limit")
        return decode(bytes(data), MAX_LOG * 2)


def start(root: Path, helper: Path) -> dict:
    layout = Layout.local(root / "runtime")
    checks.preflight(layout)
    try:
        current = request(root, "status", timeout=2)
        require(current.get("state") == "ready", "existing-supervisor-not-ready")
        return current
    except (FileNotFoundError, ConnectionRefusedError):
        pass
    # The durable record is diagnostic only; it never authorizes killing a PID.
    state.atomic(root, "lifecycle.json", {"state": "starting", "profile": "local-experimental-v1"})
    child = subprocess.Popen([sys.executable, "-I", str(helper), "supervise", str(root)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True, start_new_session=True, env=process.environment())
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        require(child.poll() is None, "workspace-supervisor-start-failed")
        try:
            result = request(root, "status", timeout=1)
            if result.get("state") == "ready":
                return result
            require(result.get("state") != "failed", "workspace-node-start-failed")
        except (FileNotFoundError, ConnectionRefusedError, socket.timeout):
            pass
        time.sleep(0.05)
    raise DevError("workspace-readiness-deadline-status-required", uncertain=True)


def supervise(root: Path) -> int:
    paths.private_root(root)
    layout = Layout.local(root / "runtime")
    owner = OwnedProcess()
    selector = selectors.DefaultSelector()
    retained = bytearray()
    clean = False
    selected_socket = socket_path(root)
    node_config = decode(paths.read(layout.node.parent, layout.node.name))
    profile = node_config["securityProfile"]
    current = {"state": "starting", "profile": profile, "node": node_config["nodeId"]}
    with state.lock(root, "supervisor.lock"), state.lock(layout.prefix, "run.lock"):
        if selected_socket.exists():
            require(selected_socket.is_socket() and selected_socket.lstat().st_uid == os.geteuid(), "unsafe-control-socket")
            selected_socket.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(selected_socket))
        selected_socket.chmod(0o600)
        server.listen(1)
        server.setblocking(False)
        selector.register(server, selectors.EVENT_READ, "control")
        try:
            binary = checks.current(layout) / "bin/latentd"
            owner.process = subprocess.Popen([str(binary), "serve", "--config", str(layout.node)],
                cwd=layout.data, env=process.environment(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, start_new_session=True,
                preexec_fn=parent_death)
            for stream in (owner.process.stdout, owner.process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, "log")
            # The bounded installer readiness probe checks node identity, credentials,
            # profile, pressure availability and admission-ready state.
            current["readiness"] = checks.readiness(layout)
            current["state"] = "ready"
            state.atomic(root, "lifecycle.json", current)
            stopping = False
            while not stopping:
                if owner.exited():
                    raise DevError("owned-node-exited")
                for key, _events in selector.select(timeout=0.2):
                    if key.data == "log":
                        raw = os.read(key.fileobj.fileno(), 8192)
                        if raw:
                            retained.extend(raw)
                            del retained[:-MAX_LOG]
                        else:
                            selector.unregister(key.fileobj)
                        continue
                    connection, _address = server.accept()
                    with connection:
                        connection.settimeout(2)
                        peer = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        require(peer[1] == os.geteuid(), "supervisor-request-owner")
                        raw = connection.recv(4097)
                        document = decode(raw, 4096)
                        require(set(document) == {"operation"}, "supervisor-request-fields")
                        operation = document["operation"]
                        require(operation in {"status", "logs", "down"}, "supervisor-command")
                        if operation == "logs":
                            # Only the node's structured bounded diagnostics are returned.
                            text = retained.decode("utf-8", errors="replace")
                            for credential in node_config["credentials"]:
                                text = text.replace(credential["token"], "[redacted]")
                            result = {**current, "logs": text}
                        elif operation == "down":
                            stopping = True
                            os.kill(owner.process.pid, signal.SIGTERM)
                            until = time.monotonic() + 7
                            while not owner.exited() and time.monotonic() < until:
                                time.sleep(0.02)
                            owner.finish(time.monotonic() + 5)
                            clean = True
                            current.update(state="stopped", reaped=True, dataRetained=True)
                            state.atomic(root, "lifecycle.json", current)
                            result = current
                        else:
                            result = current
                        connection.sendall(encode(result))
            return 0
        except BaseException:
            state.atomic(root, "lifecycle.json", {**current, "state": "failed", "cleanup": "pending"})
            return 1
        finally:
            try:
                owner.finish(time.monotonic() + 5)
                clean = True
            finally:
                owner.close()
                selector.close()
                server.close()
                selected_socket.unlink(missing_ok=True)
                if not clean:
                    state.atomic(root, "lifecycle.json", {**current, "state": "uncertain", "cleanup": "unconfirmed"})
