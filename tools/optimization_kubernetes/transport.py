"""Original bounded API bytes; credentials stay outside publishable evidence."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import ssl
import time
from urllib.parse import urlencode

from tools.optimization_docker.engine import API_VERSION, Engine
from tools.optimization_docker.owned import encoded, identifier, stamp
from tools.optimization_evidence.common import decode, require, sha256

MAX_RESPONSE = 8 * 1024**2


@contextmanager
def hard_deadline(seconds):
    """The Linux collector's synchronous API calls own one scoped wall alarm."""
    if os.name != "posix":  # Pure transport fixtures also run on Windows.
        yield
        return
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "kubernetes-existing-wall-alarm")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signal, _frame):
        raise TimeoutError("kubernetes-api-wall-deadline")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def blob(data):
    return {"bytes": str(len(data)), "sha256": sha256(data),
            "base64": base64.b64encode(data).decode("ascii")}


class Journal:
    def __init__(self, path: Path, maximum=256 * 1024**2):
        self.path, self.maximum = path, maximum
        self.count = self.size = 0
        with path.open("xb"):
            pass

    def append(self, value):
        row = {"ordinal": self.count, **value}
        data = encoded(row)
        require(self.count < 20_000 and self.size + len(data) <= self.maximum,
                "kubernetes-journal-bound")
        with self.path.open("ab") as stream:
            stream.write(data)
        self.count += 1
        self.size += len(data)
        return row


def private_tls(kubeconfig: Path, directory: Path):
    """Read the single-context kind-generated config, never log key material."""
    data = kubeconfig.read_bytes()
    require(0 < len(data) <= 32 * 1024 and not directory.exists(), "kubernetes-private-config")
    text = data.decode("utf-8-sig")
    directory.mkdir(mode=0o700, parents=True)
    paths = {}
    for key, name in (("certificate-authority-data", "ca.pem"),
                      ("client-certificate-data", "client.pem"), ("client-key-data", "client.key")):
        values = re.findall(r"^\s*" + key + r":\s*([A-Za-z0-9+/=]+)\s*$", text, re.MULTILINE)
        require(len(values) == 1, "kubernetes-single-private-credential")
        raw = base64.b64decode(values[0], validate=True)
        require(0 < len(raw) <= 16 * 1024, "kubernetes-credential-bound")
        path = directory / name
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o600)
        paths[key] = path
    context = ssl.create_default_context(cafile=paths["certificate-authority-data"])
    context.load_cert_chain(paths["client-certificate-data"], paths["client-key-data"])
    return context


class Kubernetes:
    def __init__(self, host: str, context: ssl.SSLContext, journal: Journal):
        require(re.fullmatch(r"lsf-112-[a-f0-9]{12}-control-plane", host) is not None,
                "kubernetes-owned-api-host")
        self.host, self.context, self.journal = host, context, journal

    def call(self, method, path, body=None, *, expected=(200,), timeout=15, json_response=True):
        require(method in ("GET", "POST", "DELETE") and isinstance(path, str)
                and path.startswith("/") and not path.startswith("//")
                and len(path) <= 16384 and all(33 <= ord(c) <= 126 for c in path),
                "kubernetes-api-request")
        require(type(timeout) is int and 1 <= timeout <= 60, "kubernetes-api-timeout")
        request = b"" if body is None else encoded(body).rstrip(b"\n")
        require(len(request) <= MAX_RESPONSE, "kubernetes-request-bound")
        connection = http.client.HTTPSConnection(self.host, 6443, timeout=timeout, context=self.context)
        start, received, status, failure, complete = stamp(), bytearray(), None, None, False
        try:
            with hard_deadline(timeout):
                connection.request(method, path, request, {"Content-Type": "application/json", "Connection": "close"})
                response = connection.getresponse()
                status = response.status
                require(response.getheader("Content-Encoding", "identity") == "identity",
                        "kubernetes-api-content-encoding")
                while True:
                    remaining = timeout - (time.monotonic_ns() - int(start)) / 10**9
                    require(remaining > 0, "kubernetes-api-deadline")
                    if getattr(connection, "sock", None) is not None:
                        connection.sock.settimeout(remaining)
                    chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(received)))
                    if not chunk:
                        break
                    received.extend(chunk)
                    require(len(received) <= MAX_RESPONSE, "kubernetes-api-response-bound")
                require(time.monotonic_ns() - int(start) <= timeout * 10**9, "kubernetes-api-deadline")
            complete = True
            require(status in expected, "kubernetes-api-status")
            value = (decode(bytes(received), MAX_RESPONSE) if received else None) if json_response else bytes(received)
        except BaseException as error:
            failure = type(error).__name__
            raise
        finally:
            connection.close()
            row = self.journal.append({"provider": "kubernetes", "method": method, "path": path,
                "request": blob(request), "response": blob(bytes(received)), "status": status,
                "started_nanos": start, "finished_nanos": stamp(), "response_complete": complete,
                "connection_closed": True, "json_response": json_response, "failure": failure,
                "timeout_seconds": timeout, "expected_statuses": list(expected)})
        return value, row["ordinal"]


def multiplexed(raw):
    """Decode Docker non-TTY exec frames without losing stderr or short frames."""
    stdout, stderr, offset = bytearray(), bytearray(), 0
    while offset < len(raw):
        require(len(raw) - offset >= 8, "kubernetes-exec-short-header")
        head = raw[offset:offset + 8]
        size = int.from_bytes(head[4:], "big")
        require(head[0] in (1, 2) and head[1:4] == b"\0\0\0"
                and size <= MAX_RESPONSE and offset + 8 + size <= len(raw), "kubernetes-exec-frame")
        (stdout if head[0] == 1 else stderr).extend(raw[offset + 8:offset + 8 + size])
        offset += 8 + size
    return bytes(stdout), bytes(stderr)


class Worker:
    """Only the recorded owned kind worker may execute finite observer commands."""
    def __init__(self, engine: Engine, container_id: str, owner: str, journal: Journal):
        self.engine, self.container_id = engine, identifier(container_id)
        require(re.fullmatch(r"lsf-112-[a-f0-9]{12}", owner) is not None, "kubernetes-cluster-owner")
        self.owner, self.journal = owner, journal
        actual, receipt = engine.request("GET", "/containers/" + container_id + "/json")
        require(actual["Id"] == container_id and actual["Name"] == "/" + owner + "-worker"
                and actual["Config"]["Labels"].get("io.x-k8s.kind.cluster") == owner
                and actual["Config"]["Labels"].get("io.x-k8s.kind.role") == "worker"
                and actual["State"]["Running"] is True, "kubernetes-worker-ownership")
        self.journal.append({"provider": "docker", "operation": "worker-identity",
                             "response": blob(engine.last_body), "receipt": receipt})

    def command(self, argv, *, timeout=20, expected=(0,)):
        require(isinstance(argv, list) and 1 <= len(argv) <= 64
                and all(isinstance(arg, str) and "\0" not in arg and len(arg) <= 16384 for arg in argv)
                and type(timeout) is int and 1 <= timeout <= 60, "kubernetes-worker-command")
        # The remote timeout owns its child even if the API connection disappears.
        command = ["timeout", "--signal=TERM", "--kill-after=5s", str(timeout) + "s", *argv]
        request = {"AttachStdin": False, "AttachStdout": True, "AttachStderr": True,
                   "Tty": False, "Privileged": False, "Cmd": command}
        start, records, raw, final, failure = stamp(), [], b"", None, None
        try:
            value, receipt = self.engine.request("POST", "/containers/" + self.container_id + "/exec",
                                                  request, expected=(201,))
            records.append({"request": request, "receipt": receipt, "response": blob(self.engine.last_body)})
            exec_id = identifier(value["Id"])
            body = b'{"Detach":false,"Tty":false}'
            raw, receipt = self.engine._exchange("POST", "/v" + API_VERSION + "/exec/" + exec_id + "/start",
                [body], len(body), expected=(200,), timeout=timeout + 10, maximum=MAX_RESPONSE)
            records.append({"request": blob(body), "receipt": receipt, "response": blob(raw)})
            final, receipt = self.engine.request("GET", "/exec/" + exec_id + "/json")
            records.append({"receipt": receipt, "response": blob(self.engine.last_body)})
            require(final["ID"] == exec_id and final["ContainerID"] == self.container_id
                    and final["Running"] is False and type(final["ExitCode"]) is int
                    and final["ExitCode"] in expected, "kubernetes-worker-exec-not-clean")
            stdout, stderr = multiplexed(raw)
            require(not stderr, "kubernetes-worker-exec-stderr")
        except BaseException as error:
            failure = type(error).__name__
            if getattr(error, "receipt", None) is not None:
                records.append({"receipt": error.receipt, "response": blob(error.body)})
            raise
        finally:
            row = self.journal.append({"provider": "docker", "operation": "worker-exec",
                "container_id": self.container_id, "argv": argv, "timeout_seconds": timeout,
                "started_nanos": start, "finished_nanos": stamp(), "records": records,
                "failure": failure})
        return stdout, row["ordinal"]

    def json(self, argv, **kwargs):
        raw, call = self.command(argv, **kwargs)
        return decode(raw, MAX_RESPONSE), call

    def upload(self, archive: Path, destination: str):
        root = "/var/local/lsf112/" + self.owner
        require(destination == root or destination.startswith(root + "/"), "kubernetes-upload-owned-path")
        require(".." not in Path(destination).parts and archive.is_file() and not archive.is_symlink()
                and 0 < archive.stat().st_size <= 40 * 1024**2, "kubernetes-upload-bound")
        raw, receipt, failure, checksum = b"", None, None, None
        size = archive.stat().st_size
        try:
            with archive.open("rb") as stream:
                checksum = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
                stream.seek(0)
                raw, receipt = self.engine._exchange("PUT", "/v" + API_VERSION + "/containers/" + self.container_id
                    + "/archive?" + urlencode({"path": destination, "noOverwriteDirNonDir": "1"}),
                    iter(lambda: stream.read(65536), b""), size,
                    expected=(200,), timeout=60, maximum=MAX_RESPONSE, content_type="application/x-tar")
            require(receipt["request_sha256"] == checksum, "kubernetes-upload-changed")
        except BaseException as error:
            failure = type(error).__name__
            receipt = getattr(error, "receipt", receipt)
            raw = getattr(error, "body", raw)
            raise
        finally:
            row = self.journal.append({"provider": "docker", "operation": "worker-upload",
                "container_id": self.container_id, "destination": destination,
                "archive": {"bytes": str(size), "sha256": checksum},
                "response": blob(raw), "receipt": receipt, "failure": failure})
        return row["ordinal"]
