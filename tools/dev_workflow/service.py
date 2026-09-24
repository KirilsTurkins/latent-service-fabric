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
from tools.native_runtime.common import InstallError
from tools.native_runtime.layout import Layout
from . import paths, process, state
from .common import DevError, MAX_LOG, decode, encode, require
from .node_output import NodeOutput


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


def guest_instance() -> dict:
    # A distro restart can replace its PID namespace without rebooting the shared
    # WSL kernel. Record both; a stale numeric PID is never an ownership proof.
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    init = Path("/proc/1/stat").read_text().rsplit(")", 1)[1].split()
    return {"bootId": boot, "pidNamespace": str(Path("/proc/self/ns/pid").stat().st_ino), "initStartTicks": init[19]}


def disconnected(root: Path) -> dict:
    prior = state.load(root, "lifecycle.json") if (root / "lifecycle.json").exists() else {"state": "stopped", "dataRetained": True}
    if prior["state"] in {"stopped", "purged"}:
        return prior
    previous = prior.get("guestInstance")
    if previous and previous != guest_instance():
        # No process from an old boot/PID namespace can survive here. Confirm
        # that a new controller has not already acquired this workspace.
        with state.lock(root, "supervisor.lock"), state.lock(root / "runtime", "run.lock"):
            prior.update(state="stopped", reaped=True, cleanShutdown=False,
                         failure="guest-restarted-inspect-operation-receipts", dataRetained=True)
            state.atomic(root, "lifecycle.json", prior)
        return prior
    raise DevError("supervisor-disconnected-cleanup-unknown", uncertain=True)


def request(root: Path, operation: str, *, timeout: float = 30) -> dict:
    require(operation in {"status", "logs", "down"}, "supervisor-command")
    paths.private_root(root)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("supervisor-control-deadline")
            connection.settimeout(remaining)
            try:
                connection.connect(str(socket_path(root)))
                break
            except BlockingIOError:
                # Linux AF_UNIX may report EAGAIN rather than waiting for its
                # bounded listen queue. No command has been sent at this point.
                time.sleep(min(0.01, remaining))
        peer = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        require(struct.unpack("3i", peer)[1] == os.geteuid(), "supervisor-peer-owner")
        connection.sendall(encode({"operation": operation}))
        connection.shutdown(socket.SHUT_WR)
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("supervisor-control-deadline")
            connection.settimeout(remaining)
            raw = connection.recv(min(65536, MAX_LOG * 2 + 1 - len(data)))
            if not raw:
                break
            data.extend(raw)
            require(len(data) <= MAX_LOG * 2, "supervisor-response-limit")
        return decode(bytes(data), MAX_LOG * 2)


def start(root: Path, helper: Path) -> dict:
    from .common import MAX_START_SECONDS
    deadline = time.monotonic() + MAX_START_SECONDS
    layout = Layout.local(root / "runtime")
    checks.preflight(layout)
    try:
        current = request(root, "status", timeout=2)
        require(current.get("state") == "ready", "existing-supervisor-not-ready")
        return current
    except (FileNotFoundError, ConnectionRefusedError):
        disconnected(root)
    # The durable record is diagnostic only; it never authorizes killing a PID.
    node_config = decode(paths.read(layout.node.parent, layout.node.name))
    wait_for_restart_lease(root, node_config)
    state.atomic(root, "lifecycle.json", {"state": "starting", "profile": node_config["securityProfile"],
                                         "guestInstance": guest_instance()})
    child = subprocess.Popen([sys.executable, "-I", str(helper), "supervise", str(root)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True, start_new_session=True, env=process.environment())
    while time.monotonic() < deadline:
        require(child.poll() is None, "workspace-supervisor-start-failed")
        try:
            result = request(root, "status", timeout=1)
            if result.get("state") == "ready":
                return result
            require(result.get("state") != "failed", "workspace-node-start-failed")
        except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError, socket.timeout):
            pass
        time.sleep(0.05)
    raise DevError("workspace-readiness-deadline-status-required", uncertain=True)


def wait_for_restart_lease(root: Path, node_config: dict) -> None:
    if node_config["supplyChain"]["mode"] != "enforced" or not (root / "lifecycle.json").exists():
        return
    # The runtime persists a future clock ceiling. Its public configuration
    # bounds that lease to at most five seconds. Wait after confirmed process
    # cleanup; never edit the ledger, advance the clock or retry an effect.
    with state.lock(root, "supervisor.lock"), state.lock(root / "runtime", "run.lock"):
        previous = state.load(root, "lifecycle.json")
        require(previous["state"] == "stopped" and previous.get("reaped") is True,
                "confirm-stopped-owner-before-enforced-restart")
        deadline = time.monotonic() + 5
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(0.1, remaining))


def supervise(root: Path) -> int:
    paths.private_root(root)
    layout = Layout.local(root / "runtime")
    owner = OwnedProcess()
    selector = selectors.DefaultSelector()
    reaped = False
    output = None
    selected_socket = socket_path(root)
    node_config = decode(paths.read(layout.node.parent, layout.node.name))
    profile = node_config["securityProfile"]
    current = {"state": "starting", "profile": profile, "node": node_config["nodeId"], "guestInstance": guest_instance()}
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
            output = NodeOutput(owner.process, [item["token"] for item in node_config["credentials"]])
            # The bounded installer readiness probe checks node identity, credentials,
            # profile, pressure availability and admission-ready state.
            current["readiness"] = checks.readiness(layout, timeout=120)
            current["providers"] = output.providers(node_config["nodeId"])
            current["state"] = "ready"
            state.atomic(root, "lifecycle.json", current)
            stopping = False
            while not stopping:
                if owner.exited():
                    raise DevError("owned-node-exited")
                require(output.failure is None, "node-output-read-failed")
                for key, _events in selector.select(timeout=0.2):
                    connection, _address = server.accept()
                    with connection:
                        try:
                            connection.settimeout(2)
                            peer = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                            require(peer[1] == os.geteuid(), "supervisor-request-owner")
                            raw = bytearray()
                            while part := connection.recv(4097 - len(raw)):
                                raw.extend(part)
                                require(len(raw) <= 4096, "supervisor-request-byte-limit")
                            document = decode(bytes(raw), 4096)
                            require(set(document) == {"operation"}, "supervisor-request-fields")
                            operation = document["operation"]
                            require(operation in {"status", "logs", "down"}, "supervisor-command")
                        except (DevError, OSError):
                            # A partial/malformed controller connection owns no
                            # node process. In particular startup probes may
                            # time out while retained packages are verified.
                            continue
                        if operation == "logs":
                            # Only the node's structured bounded diagnostics are returned.
                            result = {**current, "logs": output.logs()}
                        elif operation == "down":
                            stopping = True
                            os.kill(owner.process.pid, signal.SIGTERM)
                            until = time.monotonic() + 7
                            while not owner.exited() and time.monotonic() < until:
                                time.sleep(0.02)
                            owner.finish(time.monotonic() + 5)
                            reaped = True
                            output.finish()
                            current.update(state="stopped", reaped=True, dataRetained=True,
                                cleanShutdown=owner.process.returncode == 0 and output.clean_stop)
                            state.atomic(root, "lifecycle.json", current)
                            result = current
                        else:
                            result = current
                        try:
                            connection.sendall(encode(result))
                        except (BrokenPipeError, ConnectionResetError, socket.timeout):
                            # Keep a committed down disposition in the durable
                            # record even when its original response is lost.
                            pass
            return 0
        except BaseException as error:
            current["failure"] = (error.code if isinstance(error, DevError)
                                  else str(error) if isinstance(error, InstallError) else type(error).__name__)
            state.atomic(root, "node-start-failure.json", {"code": current["failure"],
                "diagnostics": output.logs()[-8192:] if output else "node-process-not-started"})
            state.atomic(root, "lifecycle.json", {**current, "state": "failed", "cleanup": "pending"})
            return 1
        finally:
            try:
                owner.finish(time.monotonic() + 5)
                reaped = True
                if output:
                    output.finish()
            finally:
                owner.close()
                selector.close()
                server.close()
                selected_socket.unlink(missing_ok=True)
                if not reaped:
                    state.atomic(root, "lifecycle.json", {**current, "state": "uncertain", "cleanup": "unconfirmed"})
                elif current["state"] != "stopped":
                    state.atomic(root, "lifecycle.json", {**current, "state": "stopped", "reaped": True,
                        "cleanShutdown": False, "failure": current.get("failure", "node-or-supervisor-failed"), "dataRetained": True})
