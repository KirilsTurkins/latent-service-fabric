"""Decode fixed worker observations while keeping the original exec bytes."""
from __future__ import annotations

import base64
import re

from tools.optimization_docker.owned import stamp
from tools.optimization_evidence.common import require


def fields(raw):
    require(len(raw) <= 2 * 1024**2, "kubernetes-observer-output-bound")
    result = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(b"\t")
        name = key.decode("ascii")
        require(separator and name not in result and re.fullmatch(r"[a-z0-9_.]+", name)
                and len(result) < 160, "kubernetes-observer-field")
        if value == b"-":
            result[name] = {"value": None, "unavailable_reason": "open-failed"}
        else:
            data = base64.b64decode(value, validate=True)
            require(len(data) <= 65536 and base64.b64encode(data) == value, "kubernetes-observer-value")
            result[name] = {"value": data.decode("utf-8"), "unavailable_reason": None}
    return result


def observation(raw, index, started, finished, *, client=False):
    selected = fields(raw)
    value = {"snapshot_index": index, "started_nanos": started, "finished_nanos": finished}
    consumed = set()
    for role in (("wrapper",) if client else ("wrapper", "child")):
        pid_name = role + ".pid"
        pid = selected[pid_name]["value"]
        require(isinstance(pid, str) and re.fullmatch(r"[1-9][0-9]*", pid), "kubernetes-observer-pid")
        consumed.add(pid_name)
        process = {"pid": int(pid), "namespaces": {}}
        for name in ("stat", "stat_after", "status", "limits", "cgroup", "mountinfo"):
            process[name] = selected[role + "." + name]
            consumed.add(role + "." + name)
        for name in ("pid", "mnt", "net", "user"):
            process["namespaces"][name] = selected[role + ".ns." + name]
            consumed.add(role + ".ns." + name)
        value[role] = process
    value["cgroups"] = []
    for ordinal in range(16):
        prefix = "cgroup." + str(ordinal) + "."
        if prefix + "path" not in selected:
            break
        path = selected[prefix + "path"]["value"]
        consumed.add(prefix + "path")
        current = {"path": path, "files": {}}
        for name in ("cpu.max", "memory.max", "memory.swap.max", "pids.max", "pids.current"):
            current["files"][name] = selected[prefix + name]
            consumed.add(prefix + name)
        value["cgroups"].append(current)
    require(consumed == selected.keys() and value["cgroups"], "kubernetes-observer-shape")
    return value


def observe(worker, script, container_id, cri, index):
    pid = cri["info"]["pid"]
    raw, identity_call = worker.command(["cat", f"/proc/{pid}/stat"])
    head, separator, tail = raw.decode().rpartition(") ")
    require(separator and head.startswith(str(pid) + " ("), "kubernetes-worker-process-stat")
    ticks = tail.split()[19]
    started = stamp()
    raw, call = worker.command(["sh", script, "observe", str(pid), container_id, ticks])
    value = observation(raw, index, started, stamp())
    return value, {"identity_call": identity_call, "call": call, "start_time_ticks": ticks}
