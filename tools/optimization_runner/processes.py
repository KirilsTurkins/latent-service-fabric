"""Bounded output and process ownership; no process probes inside timed RPCs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from run_phase1_conformance import digest
from .cgroups import cgroup


def snapshot(pid: int) -> dict:
    root = Path(f"/proc/{pid}")
    stat = root.joinpath("stat").read_text().rpartition(") ")[2].split()
    status = dict(line.split(":", 1) for line in root.joinpath("status").read_text().splitlines())
    io = dict(line.split(":", 1) for line in root.joinpath("io").read_text().splitlines())
    return {
        "process_id": pid, "start_time_ticks": stat[19],
        "rss_bytes": str(int(status.get("VmRSS", "0 kB").split()[0]) * 1024),
        "cpu_user_ticks": stat[11], "cpu_system_ticks": stat[12],
        "threads": int(status["Threads"]), "fd_count": len(list(root.joinpath("fd").iterdir())),
        "read_bytes": io["read_bytes"].strip(), "write_bytes": io["write_bytes"].strip(),
    }


class OwnedProcess:
    """Keep the leader unreaped until the owned group has been cleaned up."""

    def __init__(self, command: list[str], log: Path, role: str, timeout: float,
                 cwd: Path, env: dict[str, str] | None = None, overall_deadline_ns: int | None = None):
        executable_sha256 = digest(Path(command[0]))[0]
        self.started_ns = time.monotonic_ns()
        self.deadline_ns = self.started_ns + int(timeout * 1_000_000_000)
        if overall_deadline_ns is not None:
            self.deadline_ns = min(self.deadline_ns, overall_deadline_ns)
        self.log = log.open("xb")
        try:
            self.child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          start_new_session=True)
        except BaseException:
            self.log.close()
            raise
        self.selector = None
        try:
            self.selector = selectors.DefaultSelector()
            assert self.child.stdout is not None
            os.set_blocking(self.child.stdout.fileno(), False)
            self.selector.register(self.child.stdout, selectors.EVENT_READ)
            self.before = snapshot(self.child.pid)
        except BaseException:
            # The caller has not received an owner yet. Roll back acquisition
            # here while the unreaped leader still reserves the process group.
            try:
                os.killpg(self.child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.child.wait(timeout=5)
            if self.child.stdout:
                self.child.stdout.close()
            if self.selector:
                self.selector.close()
            self.log.close()
            raise
        self.bytes = 0
        self.pending = bytearray()
        self.events: list[dict] = []
        self.last_live = self.before
        self.after = self.before
        self.peak_rss = int(self.before["rss_bytes"])
        self.last_sample_ns = self.started_ns
        self.receipt = {
            "process_id": self.child.pid, "start_time_ticks": self.before["start_time_ticks"],
            "role": role, "executable_sha256": executable_sha256,
            "reaped": False, "output_closed": False, "exit_code": None,
        }
        self.closed = False
        self.completed_resources = None

    def exited(self) -> bool:
        return os.waitid(os.P_PID, self.child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None

    def poll(self) -> None:
        if self.closed:
            return
        if time.monotonic_ns() > self.deadline_ns:
            raise TimeoutError(f"owned {self.receipt['role']} process deadline")
        for key, _ in self.selector.select(0):
            data = os.read(key.fd, 16 * 1024)
            if not data:
                self.selector.unregister(key.fileobj)
                continue
            self.bytes += len(data)
            if self.bytes > 4 * 1024 * 1024:
                raise ValueError("owned process output exceeded 4 MiB")
            self.log.write(data)
            self.pending.extend(data)
            while b"\n" in self.pending:
                line, _, rest = self.pending.partition(b"\n")
                self.pending = bytearray(rest)
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(event, dict) and "event" in event:
                    if len(self.events) >= 32:
                        raise ValueError("owned process event limit")
                    self.events.append({"observed_ns": time.monotonic_ns(), "record": event})
        if time.monotonic_ns() - self.last_sample_ns >= 100_000_000:
            self.sample()

    def sample(self) -> dict:
        current = snapshot(self.child.pid)
        if current["start_time_ticks"] != self.receipt["start_time_ticks"]:
            raise ValueError("owned process identity changed")
        self.after = current
        if int(current["rss_bytes"]):
            self.last_live = current
        self.peak_rss = max(self.peak_rss, int(current["rss_bytes"]))
        self.last_sample_ns = time.monotonic_ns()
        return current

    def ready(self) -> dict:
        deadline = min(self.deadline_ns, time.monotonic_ns() + 30_000_000_000)
        while time.monotonic_ns() < deadline:
            self.poll()
            for event in self.events:
                if event["record"].get("event") in ("ready", "started"):
                    return event
            if self.exited():
                raise RuntimeError("server exited before readiness")
            time.sleep(0.01)
        raise TimeoutError("server readiness deadline")

    def wait(self, companion: OwnedProcess | None = None, on_measurement_complete=None) -> None:
        while not self.exited() or self.selector.get_map():
            self.poll()
            if companion:
                companion.poll()
                if companion.exited():
                    raise RuntimeError("server exited during client load")
            if self.completed_resources is None and any(
                    event["record"].get("event") == "measurement-complete" for event in self.events):
                self.sample()
                self.completed_resources = self.resources()
                if on_measurement_complete:
                    on_measurement_complete()
            time.sleep(0.005)
        self.sample()
        self.close()
        if self.receipt["exit_code"] != 0:
            raise RuntimeError(f"owned {self.receipt['role']} exited {self.receipt['exit_code']}")

    def stop(self) -> dict:
        if not self.closed:
            if not self.exited():
                os.kill(self.child.pid, signal.SIGTERM)
            self.deadline_ns = min(self.deadline_ns, time.monotonic_ns() + 15_000_000_000)
            self.wait()
        records = [event["record"] for event in self.events if event["record"].get("event") == "stopped"]
        if len(records) != 1 or records[0].get("clean") is not True:
            raise RuntimeError("server did not attest clean shutdown")
        return records[0]

    def close(self) -> None:
        if self.closed:
            return
        # The leader is still reserved (waitid WNOWAIT), so group PID cannot be
        # recycled between checking ownership and terminating descendants.
        try:
            os.killpg(self.child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.child.wait(timeout=5)
        self.child.stdout.close()
        self.selector.close()
        self.log.close()
        self.receipt.update(reaped=True, output_closed=True, exit_code=self.child.returncode)
        self.closed = True

    def resources(self, before: dict | None = None) -> dict:
        return {"before": before or self.before, "after": self.after,
                "last_live": self.last_live, "peak_rss_bytes": str(self.peak_rss),
                "sample_interval_millis": 100,
                "peak_semantics": "maximum-observed-rss-not-instantaneous-peak"}
