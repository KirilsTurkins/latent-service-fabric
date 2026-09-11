"""Offline replay of the bounded PID1 wrapper's original observations.

Docker inspect PIDs are host PIDs; event/proc PIDs are container namespace PIDs.
No observer is launched here, and unavailable kernel fields are never zeroes.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path, PurePosixPath
import re
import stat

from tools.optimization_evidence.common import (
    EvidenceError, canonical, decode, fields, integer, require, sha256, text, uint,
)
from tools.phase1_evidence.resources import shutdown as validate_shutdown
from . import model

EVENT_BYTES = 512 * 1024
LOG_BYTES = 256 * 1024
LINE_BYTES = 16 * 1024
RAW_BYTES = 64 * 1024
SCHEMA = "latent.optimization.container-event.v1"
STARTED = {
    "pid1": True, "listen": "0.0.0.0:7070", "child_listen": "127.0.0.1:7071",
    "runtime_workers": 2, "maximum_connections": 32, "buffer_bytes_per_direction": 16384,
    "connect_timeout_millis": 5000, "ready_timeout_millis": 30000,
    "child_term_grace_millis": 10000, "child_kill_wait_millis": 5000,
    "forward_drain_millis": 5000, "maximum_lifetime_millis": 300000, "maximum_snapshots": 6,
}
CGROUP_FILES = (
    "cpu.max cpu.stat cpu.pressure cpuset.cpus.effective memory.max memory.current memory.peak "
    "memory.events memory.swap.max memory.swap.current memory.pressure pids.max pids.current cgroup.procs"
).split()
READ_REASONS = {"open-failed", "read-failed", "byte-limit", "non-utf8"}
FD_REASONS = {
    "fd-directory", "fd-entry", "fd-count-limit", "fd-name", "fd-raced-or-unavailable",
    "fd-target-encoding", "fd-socket-inode",
}


def _file(directory: Path, name: str, maximum: int) -> bytes:
    path = directory / name
    try:
        require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), "wrapper-regular-file")
        with path.open("rb") as source:
            data = source.read(maximum + 1)
    except OSError as error:
        raise EvidenceError("wrapper-file-unreadable") from error
    require(len(data) <= maximum, "wrapper-file-bound")
    return data


def _raw(value, reasons=READ_REASONS, maximum=RAW_BYTES):
    fields(value, "value unavailable_reason")
    if value["value"] is None:
        require(isinstance(value["unavailable_reason"], str)
                and value["unavailable_reason"] in reasons, "wrapper-unavailable-reason")
        return None
    require(value["unavailable_reason"] is None, "wrapper-crossed-availability")
    return text(value["value"], maximum, empty=True)


def _window(value, lower: int, upper: int) -> tuple[int, int]:
    start, end = uint(value["started_nanos"]), uint(value["finished_nanos"])
    require(lower <= start <= end <= upper, "wrapper-observation-window")
    return start, end


def _inspect(ready, final, container_id, controls):
    require(isinstance(container_id, str) and re.fullmatch(r"[0-9a-f]{64}", container_id) is not None,
            "wrapper-container-id")
    for value in (ready, final):
        require(isinstance(value, dict) and value.get("Id") == container_id, "wrapper-inspect-id")
        host, config, state = (value.get(key) for key in ("HostConfig", "Config", "State"))
        require(all(isinstance(part, dict) for part in (host, config, state)), "wrapper-inspect-shape")
        for key, expected in (("CpuPeriod", "cpu_period"), ("CpuQuota", "cpu_quota"),
                              ("Memory", "memory"), ("MemorySwap", "memory_swap"),
                              ("PidsLimit", "pids_limit")):
            require(type(host.get(key)) is int and host[key] == controls[expected], "wrapper-inspect-control")
        require(host.get("CapDrop") == ["ALL"] and host.get("Privileged") is False,
                "wrapper-inspect-capabilities")
        require(host.get("SecurityOpt") in (["no-new-privileges"], ["no-new-privileges:true"]),
                "wrapper-inspect-security")
        require(host.get("PidMode") == "" and (host.get("Init") is None or host.get("Init") is False),
                "wrapper-inspect-pid-mode")
        require(host.get("Ulimits") == [{"Name": "nofile", "Soft": 1024, "Hard": 1024}],
                "wrapper-inspect-nofile")
        require(config.get("Entrypoint") == ["/opt/lsf/optimization-container"], "wrapper-inspect-entrypoint")
        require(value.get("RestartCount") == 0 and type(value.get("RestartCount")) is int,
                "wrapper-inspect-restart")
        require(state.get("OOMKilled") is False and state.get("Dead") is False
                and state.get("Paused") is False and state.get("Restarting") is False
                and state.get("Error") == "", "wrapper-inspect-failure")
    require(ready["HostConfig"] == final["HostConfig"] and ready["Config"] == final["Config"]
            and ready.get("Image") == final.get("Image"), "wrapper-inspect-config-changed")
    require(isinstance(ready.get("Image"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", ready["Image"]) is not None, "wrapper-inspect-image")
    before, after = ready["State"], final["State"]
    require(before.get("Running") is True and before.get("Status") == "running", "wrapper-inspect-not-ready")
    host_pid = integer(before.get("Pid"), 1)
    require(after.get("Running") is False and after.get("Status") == "exited"
            and type(after.get("ExitCode")) is int and after["ExitCode"] == 0
            and type(after.get("Pid")) is int and after["Pid"] == 0, "wrapper-inspect-not-reaped")
    started, finished = before.get("StartedAt"), after.get("FinishedAt")
    require(started == after.get("StartedAt"), "wrapper-inspect-restarted")
    try:
        start_time = datetime.fromisoformat(text(started, 64).replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(text(finished, 64).replace("Z", "+00:00"))
        require(start_time.tzinfo is not None and end_time.tzinfo is not None
                and start_time.year > 1970 and start_time <= end_time, "wrapper-inspect-time")
    except (ValueError, TypeError) as error:
        raise EvidenceError("wrapper-inspect-time") from error
    return {"host_wrapper_pid_at_ready": host_pid, "started_at": started, "finished_at": finished,
            "image_id": ready["Image"], "ready_inspect_sha256": sha256(canonical(ready)),
            "final_inspect_sha256": sha256(canonical(final))}


def _forward(value, previous=None, *, final=False, expected=None):
    fields(value, "capacity buffer_bytes_per_direction accepted rejected completed failed joined aborted live "
           "maximum_live byte_count_scope client_to_app_bytes app_to_client_bytes")
    require(type(value["capacity"]) is int and value["capacity"] == 32
            and type(value["buffer_bytes_per_direction"]) is int and value["buffer_bytes_per_direction"] == 16384
            and value["byte_count_scope"] == "completed-forward-tasks-only", "wrapper-forward-settings")
    counts = {key: uint(value[key]) for key in (
        "accepted", "rejected", "completed", "failed", "joined", "aborted", "live", "maximum_live",
        "client_to_app_bytes", "app_to_client_bytes")}
    require(counts["rejected"] == counts["failed"] == counts["aborted"] == 0, "wrapper-forward-failure")
    require(counts["completed"] == counts["joined"]
            and counts["accepted"] == counts["joined"] + counts["live"]
            and counts["live"] <= counts["maximum_live"] <= min(32, counts["accepted"]),
            "wrapper-forward-conservation")
    if previous is not None:
        require(all(counts[key] >= uint(previous[key]) for key in counts if key != "live"),
                "wrapper-forward-counter-regressed")
    if final:
        require(counts["live"] == 0, "wrapper-forward-live")
        if expected is not None:
            require(counts["accepted"] == integer(expected), "wrapper-forward-connection-count")
    return value


def _stat(raw, pid):
    require(raw is not None, "wrapper-process-identity-unavailable")
    head, sep, tail = raw.rpartition(") ")
    require(bool(sep) and head.startswith(str(pid) + " ("), "wrapper-proc-stat-pid")
    parts = tail.split()
    require(len(parts) >= 20 and parts[0] in ("R", "S", "D", "I"), "wrapper-proc-stat-state")
    return str(uint(parts[19])), uint(parts[1])


def _status_number(raw, name, kib=False):
    if raw is None:
        return None
    for line in raw.splitlines():
        if line.startswith(name):
            tokens = line[len(name):].split()
            if len(tokens) != (2 if kib else 1) or (kib and tokens[1] != "kB"):
                return None
            if not re.fullmatch(r"[0-9]+", tokens[0]):
                return None
            number = int(tokens[0])
            if number > (2**64 - 1) // (1024 if kib else 1):
                return None
            return str(number * (1024 if kib else 1))
    return None


def _process(value, pid, lower, upper, port):
    fields(value, "pid started_nanos finished_nanos identity_stable start_time_ticks start_time_ticks_after "
           "stat stat_after status rss_bytes threads rss_unavailable_reason threads_unavailable_reason "
           "fd_count socket_descriptors fd_unavailable_reason tcp tcp6 listener_rows listeners_unavailable_reason "
           "namespaces cgroup")
    require(integer(value["pid"], 1) == pid, "wrapper-process-pid")
    start, end = _window(value, lower, upper)
    before = _stat(_raw(value["stat"]), pid)
    after = _stat(_raw(value["stat_after"]), pid)
    require(value["identity_stable"] is True and before == after
            and before[0] == value["start_time_ticks"] == value["start_time_ticks_after"]
            and uint(before[0]) > 0 and before[1] == (0 if pid == 1 else 1), "wrapper-process-identity")
    status = _raw(value["status"])
    for name, source, kib in (("rss_bytes", "VmRSS:", True), ("threads", "Threads:", False)):
        expected = _status_number(status, source, kib)
        reason = "rss_unavailable_reason" if kib else "threads_unavailable_reason"
        require(value[name] == expected and value[reason] == (None if expected is not None else "status-field-unavailable"),
                "wrapper-status-projection")
        if expected is not None:
            require(uint(expected) > 0, "wrapper-empty-live-process")
    namespaces = fields(value["namespaces"], "pid mnt net user")
    namespace_ids = {}
    for name, item in namespaces.items():
        observed = _raw(item, {"link-limit-or-encoding", "read-link-failed"}, 4096)
        require(observed is not None and re.fullmatch(name + r":\[[0-9]+\]", observed) is not None,
                "wrapper-namespace-identity-unavailable")
        namespace_ids[name] = observed
    membership = _raw(value["cgroup"])
    tcp, tcp6 = _raw(value["tcp"]), _raw(value["tcp6"])
    listeners = None
    sockets = value["socket_descriptors"]
    if value["fd_count"] is None:
        require(sockets is None and value["fd_unavailable_reason"] in FD_REASONS, "wrapper-fd-unavailable")
    else:
        count = uint(value["fd_count"])
        require(count <= 1024 and isinstance(sockets, dict) and len(sockets) <= count
                and value["fd_unavailable_reason"] is None, "wrapper-fd-bound")
        for fd, inode in sockets.items():
            require(uint(fd) <= 2**32 - 1 and uint(inode) > 0, "wrapper-socket-identity")
        if tcp is not None and tcp6 is not None:
            listeners = []
            for table in (tcp, tcp6):
                for line in table.splitlines()[1:]:
                    tokens = line.split()
                    if len(tokens) < 10:
                        listeners = None
                        break
                    if tokens[3] == "0A" and tokens[9] in sockets.values():
                        listeners.append(line)
                if listeners is None:
                    break
    require(value["listener_rows"] == listeners and value["listeners_unavailable_reason"] ==
            (None if listeners is not None else "socket-table-or-fd-unavailable"), "wrapper-listener-projection")
    if listeners is not None:
        address = "00000000:1B9E" if port == 7070 else "0100007F:1B9F"
        require(len(listeners) == 1 and listeners[0].split()[1] == address, "wrapper-listener-address")
    return {"pid": pid, "start_time_ticks": before[0], "namespaces": namespace_ids,
            "started_nanos": str(start), "finished_nanos": str(end),
            **{key: value[key] for key in ("rss_bytes", "rss_unavailable_reason", "threads",
                "threads_unavailable_reason", "fd_count", "fd_unavailable_reason", "socket_descriptors",
                "listener_rows", "listeners_unavailable_reason")},
            "listener_count": None if listeners is None else str(len(listeners)), "cgroup_membership": membership,
            "cgroup_unavailable_reason": value["cgroup"]["unavailable_reason"]}


def _directory(membership, mountinfo):
    if membership is None or mountinfo is None:
        return None
    path = next((line[3:] for line in membership.splitlines() if line.startswith("0::")), None)
    if path is None or not path.startswith("/") or ".." in path.split("/"):
        return None
    for line in mountinfo.splitlines():
        head, sep, tail = line.partition(" - ")
        if not sep:
            return None
        if not tail.split() or tail.split()[0] != "cgroup2":
            continue
        tokens = head.split()
        if len(tokens) < 5:
            return None
        root, mount = tokens[3:5]
        if "\\" in root or mount != "/sys/fs/cgroup":
            continue
        if PurePosixPath(path).is_relative_to(PurePosixPath(root)):
            relative = PurePosixPath(path).relative_to(root)
            # Rust PathBuf::join(empty) retains this separator. PurePosixPath
            # normalizes it away, so reconstruct the actual observer spelling.
            return mount + "/" if not relative.parts else str(PurePosixPath(mount) / relative)
    return None


def _number(raw):
    return None if raw is None else str(uint(raw.strip()))


def _pairs(raw):
    if raw is None:
        return None
    result = {}
    for line in raw.splitlines():
        tokens = line.split()
        require(len(tokens) == 2 and re.fullmatch(r"[a-z_]+", tokens[0]) is not None
                and tokens[0] not in result, "wrapper-cgroup-counter")
        result[tokens[0]] = str(uint(tokens[1]))
    return result


def _cgroup(value, controls, lower, upper, wrapper, child, *, leaf_pids_max=None):
    fields(value, "started_nanos finished_nanos membership mountinfo directory mapping_unavailable_reason files")
    _window(value, lower, upper)
    membership, mountinfo = _raw(value["membership"]), _raw(value["mountinfo"])
    directory = _directory(membership, mountinfo)
    require(value["directory"] == directory and value["mapping_unavailable_reason"] ==
            (None if directory is not None else "cgroup-v2-mapping-unavailable"), "wrapper-cgroup-mapping")
    for process in (wrapper, child):
        if membership is not None and process["cgroup_membership"] is not None:
            require(membership == process["cgroup_membership"], "wrapper-crossed-cgroup")
    raw_files = fields(value["files"], " ".join(CGROUP_FILES))
    parsed, unavailable = {}, {}
    for name, raw in raw_files.items():
        reasons = READ_REASONS if directory is not None else {"cgroup-v2-mapping-unavailable"}
        parsed[name] = _raw(raw, reasons)
        if directory is None:
            require(parsed[name] is None, "wrapper-unmapped-cgroup-file")
        unavailable[name] = raw["unavailable_reason"]
    limits = {}
    for name, expected in (("memory.max", controls["memory"]), ("memory.swap.max", 0)):
        limits[name] = _number(parsed[name])
        if limits[name] is not None:
            require(uint(limits[name]) == expected, "wrapper-effective-control")
    if leaf_pids_max is None:
        limits["pids.max"] = _number(parsed["pids.max"])
        if limits["pids.max"] is not None:
            require(uint(limits["pids.max"]) == controls["pids_limit"], "wrapper-effective-control")
    else:
        require(isinstance(leaf_pids_max, str) and (leaf_pids_max == "max"
                or re.fullmatch(r"[1-9][0-9]{0,19}", leaf_pids_max)), "wrapper-provider-pids-limit")
        limits["pids.max"] = None if parsed["pids.max"] is None else parsed["pids.max"].strip()
        if limits["pids.max"] is not None:
            require(limits["pids.max"] == leaf_pids_max, "wrapper-effective-control")
    limits["cpu.max"] = None
    if parsed["cpu.max"] is not None:
        tokens = parsed["cpu.max"].split()
        require(len(tokens) == 2 and uint(tokens[0]) == controls["cpu_quota"]
                and uint(tokens[1]) == controls["cpu_period"], "wrapper-effective-cpu")
        limits["cpu.max"] = {"quota": tokens[0], "period": tokens[1]}
    cpus = parsed["cpuset.cpus.effective"]
    if cpus is not None:
        require(re.fullmatch(r"[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*\n?", cpus) is not None,
                "wrapper-effective-cpuset")
    numbers = {name: _number(parsed[name]) for name in (
        "memory.current", "memory.peak", "memory.swap.current", "pids.current")}
    for name, maximum in (("memory.current", controls["memory"]), ("memory.swap.current", 0),
                           ("pids.current", controls["pids_limit"])):
        if numbers[name] is not None:
            require(uint(numbers[name]) <= maximum, "wrapper-cgroup-resource-limit")
    processes = None
    if parsed["cgroup.procs"] is not None:
        processes = [uint(item) for item in parsed["cgroup.procs"].split()]
        require(len(processes) == 2 and set(processes) == {1, child["pid"]}, "wrapper-unowned-cgroup-process")
    cpu, memory = _pairs(parsed["cpu.stat"]), _pairs(parsed["memory.events"])
    if memory is not None:
        require(all(uint(memory[key]) == 0 for key in ("oom", "oom_kill", "oom_group_kill") if key in memory),
                "wrapper-cgroup-oom")
    return {"started_nanos": value["started_nanos"], "finished_nanos": value["finished_nanos"],
            "directory": directory, "mapping_unavailable_reason": value["mapping_unavailable_reason"],
            "membership": value["membership"], "mountinfo": value["mountinfo"], "files": raw_files,
            "limits": limits, "unavailable_reasons": unavailable, "cpu_stat": cpu, "memory_events": memory,
            "cgroup_process_ids": processes, "cpuset_cpus_effective": None if cpus is None else cpus.strip(),
            **numbers}


def _child_records(data, arm):
    ready = stopped = None
    for line in data.split(b"\n"):
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError, RecursionError):
            continue
        if not isinstance(value, dict) or value.get("event") not in ("ready", "stopped"):
            continue
        value = decode(line, LINE_BYTES)  # Duplicate keys cannot forge an identity.
        if value["event"] == "ready":
            require(ready is None and stopped is None, "wrapper-duplicate-child-ready")
            if arm == "native":
                fields(value, "event implementation address")
                require(value["implementation"] == "native-reference"
                        and value["address"] == "http://127.0.0.1:7071", "wrapper-child-ready")
            else:
                fields(value, "schemaVersion event nodeId endpoint ready")
                require(value["schemaVersion"] == "latent.standalone.status.v1"
                        and value["nodeId"] == "optimization-node" and value["endpoint"] == "127.0.0.1:7071"
                        and value["ready"] is True, "wrapper-child-ready")
            ready = value
        else:
            require(ready is not None and stopped is None and value.get("clean") is True,
                    "wrapper-child-stopped")
            if arm == "native":
                fields(value, "event implementation clean")
                require(value["implementation"] == "native-reference", "wrapper-child-stopped")
            else:
                fields(value, "schemaVersion event clean report")
                require(value["schemaVersion"] == "latent.standalone.status.v1", "wrapper-child-stopped")
                require(isinstance(value["report"], dict) and {"compiler", "cleanup"} <= value["report"].keys(),
                        "wrapper-missing-shutdown-owners")
                validate_shutdown(value["report"], cells=4)
                require(value["report"]["quarantinedCells"] == 0, "wrapper-quarantined-cell")
            stopped = value
    require(ready is not None and stopped is not None, "wrapper-missing-child-status")
    return ready, stopped


def _log(directory, receipt, name, arm):
    fields(receipt, "path bytes lines_processed sha256 eof error ready stopped maximum_bytes maximum_line_bytes")
    require(receipt["path"] == name and type(receipt["maximum_bytes"]) is int
            and receipt["maximum_bytes"] == LOG_BYTES and type(receipt["maximum_line_bytes"]) is int
            and receipt["maximum_line_bytes"] == LINE_BYTES, "wrapper-log-settings")
    data = _file(directory, name, LOG_BYTES)
    # Actual source splits LF only, including empty LF lines and a final partial line.
    lines = data.split(b"\n")
    count = len(lines) - 1 + bool(lines[-1])
    require(all(len(line) + (index < len(lines) - 1) <= LINE_BYTES for index, line in enumerate(lines)),
            "wrapper-log-line-bound")
    require(uint(receipt["bytes"]) == len(data) and uint(receipt["lines_processed"]) == count
            and receipt["sha256"] == sha256(data) and receipt["eof"] is True and receipt["error"] is None,
            "wrapper-log-receipt")
    ready, stopped = _child_records(data, arm) if name == "child-stdout.bin" else (None, None)
    require(receipt["ready"] == ready and receipt["stopped"] == stopped, "wrapper-log-status-crossed")
    return {"path": name, "bytes": str(len(data)), "sha256": sha256(data)}, ready, stopped


def validate(directory: Path, *, arm: str, density: int, container_id: str,
             ready_inspect: dict, final_inspect: dict, expected_snapshots: int = 6,
             expected_connections: int | None = None) -> dict:
    """Require a complete clean wrapper lifecycle, then derive bounded resources.

    This does not bind SIGUSR1 API times to event times: the owning orchestration
    replay performs that separate check. A seed has zero resource snapshots.
    """
    require(arm in ("lsf", "native"), "wrapper-arm")
    controls = model.resources(arm, density)
    require(type(expected_snapshots) is int and expected_snapshots in (0, 6), "wrapper-snapshot-preset")
    if expected_connections is not None:
        integer(expected_connections)
    require(directory.is_dir() and not directory.is_symlink(), "wrapper-directory")
    identity = _inspect(ready_inspect, final_inspect, container_id, controls)
    return validate_observations(directory, arm=arm, density=density, container_id=container_id,
                                 identity=identity, controls=controls, expected_snapshots=expected_snapshots,
                                 expected_connections=expected_connections)


def validate_observations(directory: Path, *, arm: str, density: int, container_id: str,
                          identity: dict, controls: dict, expected_snapshots: int = 6,
                          expected_connections: int | None = None, leaf_pids_max: str | None = None) -> dict:
    """Replay common wrapper bytes after the provider has verified its own facts.

    A non-default leaf PID limit is supplied only by a provider which separately
    verifies the effective ancestor limit. It is never a replacement inspect DTO.
    """
    require(arm in ("lsf", "native"), "wrapper-arm")
    model.resources(arm, density)  # Keep the shared bounded arm/density presets.
    require(isinstance(identity, dict) and isinstance(controls, dict), "wrapper-provider-facts")
    identity = dict(identity)
    require(type(expected_snapshots) is int and expected_snapshots in (0, 6), "wrapper-snapshot-preset")
    if expected_connections is not None:
        integer(expected_connections)
    require(directory.is_dir() and not directory.is_symlink(), "wrapper-directory")
    data = _file(directory, "events.ndjson", 10 * EVENT_BYTES)
    raw_lines = data.splitlines(keepends=True)
    require(len(raw_lines) == expected_snapshots + 3 and all(line.endswith(b"\n")
            and len(line) <= EVENT_BYTES for line in raw_lines), "wrapper-event-framing")
    events = [decode(line, EVENT_BYTES) for line in raw_lines]
    child_pid, previous_time = None, 0
    for index, event in enumerate(events):
        fields(event, "schema sequence event app wrapper_pid child_pid elapsed_nanos detail")
        require(event["schema"] == SCHEMA and integer(event["sequence"]) == index
                and event["app"] == arm and integer(event["wrapper_pid"], 1) == 1, "wrapper-event-identity")
        pid = integer(event["child_pid"], 2)
        if child_pid is None:
            child_pid = pid
        require(child_pid == pid, "wrapper-child-pid-changed")
        elapsed = uint(event["elapsed_nanos"])
        require(elapsed >= previous_time, "wrapper-event-clock")
        previous_time = elapsed
    require([event["event"] for event in events] == ["started", "ready"] + ["snapshot"] * expected_snapshots
            + ["stopped"], "wrapper-event-order")
    require(canonical(events[0]["detail"]) == canonical(STARTED), "wrapper-start-settings")
    ready = fields(events[1]["detail"], "listen child_listen child_status")
    require(ready["listen"] == STARTED["listen"] and ready["child_listen"] == STARTED["child_listen"],
            "wrapper-ready-listener")
    final = fields(events[-1]["detail"], "clean failure stop_requested child forward copy_tasks_joined "
                   "output_tasks_joined stdout stderr snapshots")
    require(final["clean"] is True and final["failure"] is None and final["stop_requested"] is True
            and final["copy_tasks_joined"] is True and final["output_tasks_joined"] is True
            and integer(final["snapshots"]) == expected_snapshots, "wrapper-unclean-shutdown")
    exit_record = fields(final["child"], "reaped term_sent kill_sent exit_code signal error")
    require(exit_record["reaped"] is True and exit_record["term_sent"] is True and exit_record["kill_sent"] is False
            and type(exit_record["exit_code"]) is int and exit_record["exit_code"] == 0
            and exit_record["signal"] is None and exit_record["error"] is None, "wrapper-child-not-reaped")
    stdout, child_ready, child_stopped = _log(directory, final["stdout"], "child-stdout.bin", arm)
    stderr, _, _ = _log(directory, final["stderr"], "child-stderr.bin", arm)
    require(ready["child_status"] == child_ready, "wrapper-ready-record-crossed")
    rows, fixed_identity, previous_forward = [], None, None
    previous_end = uint(events[1]["elapsed_nanos"])
    previous_cgroup = None
    for index, event in enumerate(events[2:-1], 1):
        sample = fields(event["detail"], "snapshot_index started_nanos finished_nanos wrapper child cgroup forward")
        require(integer(sample["snapshot_index"]) == index, "wrapper-snapshot-order")
        start, end = _window(sample, previous_end, uint(event["elapsed_nanos"]))
        wrapper = _process(sample["wrapper"], 1, start, end, 7070)
        child = _process(sample["child"], child_pid, uint(wrapper["finished_nanos"]), end, 7071)
        require(wrapper["namespaces"] == child["namespaces"] and uint(wrapper["start_time_ticks"])
                <= uint(child["start_time_ticks"]), "wrapper-crossed-process-namespace")
        current_identity = {name: {key: process[key] for key in ("pid", "start_time_ticks", "namespaces")}
                            for name, process in (("wrapper", wrapper), ("child", child))}
        if fixed_identity is None:
            fixed_identity = current_identity
        require(current_identity == fixed_identity, "wrapper-process-replaced")
        cgroup = _cgroup(sample["cgroup"], controls, uint(child["finished_nanos"]), end, wrapper, child,
                         leaf_pids_max=leaf_pids_max)
        if previous_cgroup is not None:
            for key in ("cpu_stat", "memory_events"):
                before, after = previous_cgroup[key], cgroup[key]
                if before is not None and after is not None:
                    require(all(uint(after[name]) >= uint(value) for name, value in before.items() if name in after),
                            "wrapper-cgroup-counter-regressed")
            if previous_cgroup["membership"]["value"] is not None and cgroup["membership"]["value"] is not None:
                require(previous_cgroup["membership"] == cgroup["membership"], "wrapper-cgroup-changed")
        forward = _forward(sample["forward"], previous_forward)
        rows.append({"snapshot_index": index, "event_sequence": event["sequence"],
                     "event_elapsed_nanos": event["elapsed_nanos"], "started_nanos": str(start), "finished_nanos": str(end),
                     "wrapper": wrapper, "child": child, "cgroup": cgroup, "forward": forward})
        previous_end, previous_forward, previous_cgroup = uint(event["elapsed_nanos"]), forward, cgroup
    forward = _forward(final["forward"], previous_forward, final=True, expected=expected_connections)
    identity.update({"wrapper_pid": 1, "child_pid": child_pid, "processes": fixed_identity,
                     "process_identity_unavailable_reason": "seed-without-snapshots" if fixed_identity is None else None})
    return {"container_id": container_id, "arm": arm, "density": density, "identity": identity,
            "effective_controls": controls, "snapshots": rows, "forward": forward,
            "shutdown": {"wrapper": final, "child_ready": child_ready, "child_stopped": child_stopped,
                         "child_reaped": exit_record["reaped"], "copy_tasks_joined": final["copy_tasks_joined"],
                         "output_closed": final["output_tasks_joined"] and final["stdout"]["eof"] and final["stderr"]["eof"]},
            "files": [{"path": "events.ndjson", "bytes": str(len(data)), "sha256": sha256(data)}, stdout, stderr]}
