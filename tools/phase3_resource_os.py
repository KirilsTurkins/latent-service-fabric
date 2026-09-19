"""Finite /proc inventory rooted exclusively in an unreaped owned process group."""
from __future__ import annotations

import os
from pathlib import Path
import re
import time

from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_profile import LIMITS


def proc_stat(data):
    fields = data.rpartition(") ")[2].split()
    require(len(fields) >= 22 and fields[2].isdigit() and fields[19].isdigit(), "resource-proc-stat")
    return {"parent": int(fields[1]), "group": int(fields[2]), "session": int(fields[3]),
            "startTimeTicks": fields[19], "userTicks": fields[11], "systemTicks": fields[12]}


def network_counts(tables, sockets):
    listening, connected, datagrams = set(), set(), set()
    for kind, lines in tables.items():
        require(len(lines) <= LIMITS["maximumNetworkRows"] + 1, "resource-network-bound")
        for line in lines[1:]:
            fields = line.split()
            require(len(fields) >= 10, "resource-network-shape")
            if fields[9] in sockets:
                if kind.startswith("udp"):
                    datagrams.add(fields[9])
                elif fields[3] == "0A":
                    listening.add(fields[9])
                else:
                    connected.add(fields[9])
    return {"listeners": len(listening), "tcpConnections": len(connected), "udpSockets": len(datagrams)}


class Probe:
    def __init__(self, process, executable_identity):
        self.process = process
        self.pid = process.owner.process.pid
        actual_executable = Path(f"/proc/{self.pid}/exe").resolve(strict=True)
        require(file_identity(actual_executable) == executable_identity, "resource-process-executable")
        current = proc_stat(self.read_initial("stat"))
        require(current["group"] == current["session"] == self.pid, "resource-unowned-process-group")
        self.identity = {"processId": self.pid, "startTimeTicks": current["startTimeTicks"],
                         "executableSha256": executable_identity["sha256"]}

    def read_initial(self, name):
        with Path(f"/proc/{self.pid}/{name}").open("rb") as source:
            data = source.read(65537)
        require(len(data) <= 65536, "resource-proc-read-bound")
        return data.decode("ascii")

    def sample(self):
        require(not self.process.closed and not self.process.owner.finished and not self.process.owner.exited(),
                "resource-process-not-owned")
        began = time.monotonic_ns()
        deadline = time.monotonic() + LIMITS["sampleSeconds"]
        remaining = LIMITS["maximumProcBytes"]

        def read(path, maximum=65536):
            nonlocal remaining
            self.process.cancellation.check()
            require(time.monotonic() < deadline, "resource-proc-deadline")
            with path.open("rb") as source:
                data = source.read(min(maximum, remaining) + 1)
            require(len(data) <= min(maximum, remaining), "resource-proc-read-bound")
            remaining -= len(data)
            return data.decode("ascii")

        root = Path(f"/proc/{self.pid}")
        before = proc_stat(read(root / "stat"))
        require(before["startTimeTicks"] == self.identity["startTimeTicks"]
                and before["group"] == before["session"] == self.pid, "resource-process-replaced")
        pending, rows, known = [self.pid], [], set()
        while pending:
            process_id = pending.pop()
            require(process_id not in known and len(known) < LIMITS["maximumProcesses"],
                    "resource-process-tree-bound")
            known.add(process_id)
            directory = Path(f"/proc/{process_id}")
            current = proc_stat(read(directory / "stat"))
            require(current["group"] == current["session"] == self.pid, "resource-descendant-group")
            status = dict(line.split(":", 1) for line in read(directory / "status").splitlines())
            sockets, descriptors, disappeared, tasks = set(), 0, 0, 0
            with os.scandir(directory / "fd") as entries:
                for entry in entries:
                    descriptors += 1
                    require(descriptors <= LIMITS["maximumDescriptors"], "resource-descriptor-bound")
                    try:
                        target = os.readlink(entry.path)
                    except FileNotFoundError:
                        disappeared += 1
                        continue
                    require(len(target) <= 4096, "resource-link-bound")
                    matched = re.fullmatch(r"socket:\[([0-9]{1,20})\]", target)
                    if matched:
                        sockets.add(matched[1])
            children = set()
            with os.scandir(directory / "task") as entries:
                for entry in entries:
                    tasks += 1
                    require(tasks <= LIMITS["maximumTasks"], "resource-task-bound")
                    children.update(int(value) for value in read(Path(entry.path) / "children").split())
            pending.extend(sorted(children))
            tables = {kind: read(directory / "net" / kind, 1048576).splitlines()
                      for kind in ("tcp", "tcp6", "udp", "udp6")}
            memory = {"rssBytes": int(status["VmRSS"].split()[0]) * 1024,
                      "highWaterRssBytes": int(status["VmHWM"].split()[0]) * 1024}
            rows.append({"processId": process_id, "startTimeTicks": current["startTimeTicks"],
                         "threads": int(status["Threads"]), "tasks": tasks,
                         "handles": descriptors, "sockets": len(sockets), "disappearedDescriptors": disappeared,
                         **network_counts(tables, sockets), **memory})
        after = proc_stat(read(root / "stat"))
        require(after["startTimeTicks"] == before["startTimeTicks"], "resource-process-replaced")
        metrics = {key: sum(row[key] for row in rows) for key in
                   ("threads", "tasks", "handles", "sockets", "listeners", "tcpConnections",
                    "udpSockets", "rssBytes", "highWaterRssBytes", "disappearedDescriptors")}
        metrics["processes"] = len(rows)
        return {"identity": self.identity, "beganMonotonicNanos": str(began),
                "finishedMonotonicNanos": str(time.monotonic_ns()), "metrics": metrics, "processTree": rows,
                "procBytesRead": LIMITS["maximumProcBytes"] - remaining,
                "consistency": "non-atomic-finite-scan", "unavailable": {
                    "rendererHeapBytes": "guest-JS-allocator-not-exported",
                    "allocatorRetainedBytes": "RSS-is-not-an-allocator-retention-counter"}}
