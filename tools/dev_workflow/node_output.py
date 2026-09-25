"""Drain an owned node continuously, with bounded redacted diagnostic records."""
import os
import selectors
import threading

from .common import MAX_LOG, decode, require

PROVIDER_COUNTERS = ("controlOwners", "connections", "pendingRequests", "runningRequests", "workers",
                    "cleanupJobs", "failedCleanup", "sessions", "handles", "calls", "results", "ioCalls",
                    "ioRetainedBytes", "blobStages", "blobHandles", "blobWork")


def provider_shutdown(record):
    """Export only the bounded public resource counters, never arbitrary node data."""
    report = record.get("report")
    value = report.get("providers") if isinstance(report, dict) else None
    if (isinstance(value, dict) and type(value.get("clean")) is bool
            and all(type(value.get(key)) is int and 0 <= value[key] <= 18446744073709551615
                    for key in PROVIDER_COUNTERS)):
        return {key: value[key] for key in ("clean", *PROVIDER_COUNTERS)}
    return None


class NodeOutput:
    def __init__(self, child, tokens):
        self.child, self.tokens = child, tokens
        self.retained = bytearray()
        self.clean_stop, self.failure = False, None
        self.provider_shutdown = None
        self.started = None
        self.startup = threading.Event()
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._drain, name="latent-dev-node-output", daemon=True)
        self.worker.start()

    def _line(self, raw, stdout):
        if stdout:
            try:
                record = decode(raw, 16384)
                if (record.get("schemaVersion") == "latent.standalone.status.v1"
                        and record.get("event") == "stopped" and record.get("clean") is True):
                    self.clean_stop = True
                    self.provider_shutdown = provider_shutdown(record)
                if (record.get("schemaVersion") == "latent.standalone.status.v1"
                        and record.get("event") in {"ready", "started"}):
                    with self.lock:
                        self.started = record
                    self.startup.set()
            except (ValueError, AttributeError):
                pass
        text = raw.decode("utf-8", errors="replace")
        for token in self.tokens:
            text = text.replace(token, "[redacted]")
        with self.lock:
            self.retained.extend(text.encode())
            del self.retained[:-MAX_LOG]

    def _drain(self):
        try:
            with selectors.DefaultSelector() as selector:
                buffers, dropping = {}, set()
                for stream in (self.child.stdout, self.child.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                    buffers[stream] = bytearray()
                while selector.get_map():
                    for key, _events in selector.select(timeout=0.2):
                        stream = key.fileobj
                        raw = os.read(stream.fileno(), 8192)
                        if not raw:
                            selector.unregister(stream)
                            if buffers[stream] and stream not in dropping:
                                # An incomplete JSON status cannot prove shutdown.
                                self._line(bytes(buffers[stream]), False)
                            continue
                        for part in raw.splitlines(keepends=True):
                            buffer = buffers[stream]
                            if stream not in dropping:
                                if len(buffer) + len(part) > 16384:
                                    buffer.clear()
                                    dropping.add(stream)
                                    self._line(b"[oversized node diagnostic omitted]\n", False)
                                else:
                                    buffer.extend(part)
                            if part.endswith(b"\n"):
                                if stream not in dropping:
                                    self._line(bytes(buffer), stream is self.child.stdout)
                                buffer.clear()
                                dropping.discard(stream)
        except BaseException:
            self.failure = "node-output-read-failed"

    def logs(self):
        with self.lock:
            return self.retained.decode("utf-8", errors="replace")

    def providers(self, node_id):
        require(self.startup.wait(timeout=2), "node-startup-identity-unavailable")
        with self.lock:
            require(isinstance(self.started, dict) and self.started.get("nodeId") == node_id,
                    "node-startup-identity-unavailable")
            records = self.started.get("providers", [])
            require(isinstance(records, list) and len(records) <= 16
                    and all(isinstance(row, dict) for row in records), "node-provider-startup-format")
            return records

    def finish(self):
        self.worker.join(timeout=3)
        require(not self.worker.is_alive() and self.failure is None, "node-output-drain-unconfirmed")
