"""Bind original wrapper observations to Kubernetes, CRI, and worker kernel facts.

No Docker inspect object is manufactured. Controller capture brackets and wrapper
elapsed clocks remain distinct; ancestor limits are not added to leaf usage.
"""
from __future__ import annotations

from fractions import Fraction
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
import re

from tools.optimization_docker import model as docker_model
from tools.optimization_docker import resources as wrapper
from tools.optimization_evidence.common import canonical, fields, integer, require, sha256, text, uint
from . import model

ANCESTOR_FILES = ("cpu.max", "memory.max", "memory.swap.max", "pids.max", "pids.current")
POD_PIDS = 512
ROOT = PurePosixPath("/sys/fs/cgroup")


def cri_timestamp(value, *, unreported=False):
    """Exact CRI Unix nanoseconds; retain raw RFC3339 strings in every receipt.

    crictl renders inspect timestamps as RFC3339Nano, while numeric CRI JSON
    represents the same Unix domain. Neither is a controller monotonic clock.
    """
    if unreported and (value is None or type(value) is int and value == 0
                       or isinstance(value, str) and value in ("0001-01-01T00:00:00Z", "0")):
        return None
    if type(value) is int:
        return integer(value, 0, 2**64 - 1)
    value = text(value, 64)
    if re.fullmatch(r"[0-9]+", value):
        return uint(value)
    match = re.fullmatch(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
                         r"(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})", value)
    require(match is not None, "kubernetes-cri-timestamp")
    zone = match[8]
    offset = 0
    if zone != "Z":
        hours, minutes = int(zone[1:3]), int(zone[4:6])
        require(hours <= 23 and minutes <= 59, "kubernetes-cri-timestamp-offset")
        offset = (hours * 60 + minutes) * (1 if zone[0] == "+" else -1)
    try:
        instant = datetime(*(int(match[index]) for index in range(1, 7)),
                           tzinfo=timezone(timedelta(minutes=offset)))
        delta = instant - datetime(1970, 1, 1, tzinfo=timezone.utc)
    except (ValueError, OverflowError):
        require(False, "kubernetes-cri-timestamp")
    nanos = (delta.days * 86400 + delta.seconds) * 10**9 + int((match[7] or "").ljust(9, "0"))
    return integer(nanos, 0, 2**64 - 1)


def _object(value, reason):
    require(isinstance(value, dict), reason)
    return value


def _id(value):
    value = text(value, 64)
    require(re.fullmatch(r"[0-9a-f]{64}", value), "kubernetes-container-id")
    return value


def _quantity(value, *, cpu=False):
    value = text(value, 64)
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(m|Ki|Mi|Gi|Ti|K|M|G|T)?", value)
    require(match is not None, "kubernetes-resource-quantity")
    suffix = match[2] or ""
    require(suffix in ("", "m") if cpu else suffix != "m", "kubernetes-resource-unit")
    factor = {"": 1, "m": Fraction(1, 1000), "Ki": 2**10, "Mi": 2**20, "Gi": 2**30,
              "Ti": 2**40, "K": 10**3, "M": 10**6, "G": 10**9, "T": 10**12}[suffix]
    return Fraction(match[1]) * factor


def _pod(ready, final, arm, controls, worker, *, startup_protocol=model.CURRENT_STARTUP_PROTOCOL):
    identity = None
    for value, phase in ((ready, "Running"), (final, "Succeeded")):
        _object(value, "kubernetes-pod-object")
        require(value.get("apiVersion") == "v1" and value.get("kind") == "Pod", "kubernetes-pod-kind")
        meta = _object(value.get("metadata"), "kubernetes-pod-metadata")
        current = {key: text(meta.get(key), 253) for key in ("name", "namespace", "uid")}
        if identity is None:
            identity = current
        require(identity == current, "kubernetes-pod-replaced")
        spec = _object(value.get("spec"), "kubernetes-pod-spec")
        require(spec.get("nodeName") == worker["name"] and spec.get("restartPolicy") == "Never"
                and not spec.get("hostNetwork", False) and not spec.get("hostPID", False)
                and not spec.get("hostIPC", False) and not spec.get("shareProcessNamespace", False)
                and not spec.get("runtimeClassName") and not spec.get("initContainers")
                and not spec.get("ephemeralContainers"), "kubernetes-pod-isolation")
        containers = spec.get("containers")
        require(isinstance(containers, list) and len(containers) == 1, "kubernetes-pod-container-count")
        container = _object(containers[0], "kubernetes-pod-container")
        require(container.get("name") == arm and container.get("imagePullPolicy") == "Never"
                and not container.get("command"), "kubernetes-pod-entrypoint")
        resources = fields(container.get("resources"), "requests limits")
        for limits in resources.values():
            fields(limits, "cpu memory")
            require(_quantity(limits["cpu"], cpu=True) == Fraction(controls["cpu_quota"], controls["cpu_period"])
                    and _quantity(limits["memory"]) == controls["memory"], "kubernetes-pod-resource")
        security = _object(container.get("securityContext"), "kubernetes-pod-security")
        require(security.get("readOnlyRootFilesystem") is True and security.get("allowPrivilegeEscalation") is False
                and not security.get("privileged", False) and security.get("capabilities") == {"drop": ["ALL"]},
                "kubernetes-pod-security")
        model.validate_startup_probe(container.get("startupProbe"), startup_protocol=startup_protocol)
        require(not container.get("readinessProbe") and not container.get("livenessProbe"),
                "kubernetes-startup-probe")
        status = _object(value.get("status"), "kubernetes-pod-status")
        require(status.get("phase") == phase, "kubernetes-pod-phase")
        statuses = status.get("containerStatuses")
        require(isinstance(statuses, list) and len(statuses) == 1, "kubernetes-pod-status-count")
        state = statuses[0]
        require(state.get("name") == arm and type(state.get("restartCount")) is int
                and state["restartCount"] == 0 and not state.get("lastState"), "kubernetes-pod-restart")
        if phase == "Running":
            require(state.get("ready") is True and state.get("started") is True
                    and set(state.get("state", {})) == {"running"}, "kubernetes-pod-not-ready")
        else:
            stopped = fields(state.get("state"), "terminated")["terminated"]
            require(type(stopped.get("exitCode")) is int and stopped["exitCode"] == 0
                    and stopped.get("signal", 0) == 0 and stopped.get("reason") == "Completed",
                    "kubernetes-pod-not-clean")
    require(ready["spec"] == final["spec"], "kubernetes-pod-spec-changed")
    before, after = (value["status"]["containerStatuses"][0] for value in (ready, final))
    require(before.get("containerID") == after.get("containerID") and before.get("imageID") == after.get("imageID"),
            "kubernetes-pod-container-changed")
    require(before["state"]["running"].get("startedAt") == after["state"]["terminated"].get("startedAt")
            and isinstance(before["state"]["running"].get("startedAt"), str), "kubernetes-pod-start-changed")
    prefix = "containerd://"
    identifier = text(before.get("containerID"), 80)
    require(identifier.startswith(prefix), "kubernetes-pod-runtime")
    identity.update(container_id=_id(identifier[len(prefix):]), image_id=text(before.get("imageID"), 512),
                    node_name=worker["name"], pod_ready_sha256=sha256(canonical(ready)),
                    pod_final_sha256=sha256(canonical(final)))
    return identity


def _cri(ready, final, identity, arm, controls):
    runtime_spec = None
    for value, expected in ((ready, "CONTAINER_RUNNING"), (final, "CONTAINER_EXITED")):
        _object(value, "kubernetes-cri-object")
        status = _object(value.get("status"), "kubernetes-cri-status")
        require(status.get("id") == identity["container_id"] and status.get("state") == expected,
                "kubernetes-cri-container")
        metadata = status.get("metadata", {})
        require(metadata.get("name") == arm and type(metadata.get("attempt")) is int and metadata["attempt"] == 0,
                "kubernetes-cri-attempt")
        labels = _object(status.get("labels"), "kubernetes-cri-labels")
        require(all(labels.get("io.kubernetes.pod." + key) == identity[key] for key in ("uid", "name", "namespace")),
                "kubernetes-cri-pod")
        info = _object(value.get("info"), "kubernetes-cri-info")
        require(info.get("runtimeType") == "io.containerd.runc.v2" and info.get("removing") is False,
                "kubernetes-cri-runtime")
        _id(info.get("sandboxID"))
        spec = _object(info.get("runtimeSpec"), "kubernetes-runtime-spec")
        if runtime_spec is None:
            runtime_spec = spec
        require(spec == runtime_spec, "kubernetes-runtime-spec-changed")
        process = _object(spec.get("process"), "kubernetes-runtime-process")
        args = process.get("args")
        require(isinstance(args, list) and args and args[0] == "/opt/lsf/optimization-container"
                and process.get("noNewPrivileges") is True and spec.get("root", {}).get("readonly") is True,
                "kubernetes-runtime-process")
        capabilities = _object(process.get("capabilities"), "kubernetes-runtime-capabilities")
        require(all(isinstance(items, list) and not items for items in capabilities.values()),
                "kubernetes-runtime-capabilities")
        linux = _object(spec.get("linux"), "kubernetes-runtime-linux")
        resources = _object(linux.get("resources"), "kubernetes-runtime-resources")
        require(resources.get("cpu", {}).get("quota") == controls["cpu_quota"]
                and resources.get("cpu", {}).get("period") == controls["cpu_period"]
                and resources.get("memory", {}).get("limit") == controls["memory"], "kubernetes-runtime-limits")
    before, after = ready["status"], final["status"]
    require(before.get("createdAt") == after.get("createdAt") and before.get("startedAt") == after.get("startedAt")
            and before.get("imageRef") == after.get("imageRef")
            and ready["info"]["sandboxID"] == final["info"]["sandboxID"], "kubernetes-cri-replaced")
    require(cri_timestamp(before.get("createdAt")) <= cri_timestamp(before.get("startedAt"))
            < cri_timestamp(after.get("finishedAt"))
            and cri_timestamp(before.get("finishedAt"), unreported=True) is None
            and type(after.get("exitCode")) is int and after["exitCode"] == 0
            and after.get("reason") == "Completed", "kubernetes-cri-not-clean")
    identity.update(host_wrapper_pid_at_ready=integer(ready["info"].get("pid"), 1),
                    sandbox_id=ready["info"]["sandboxID"], cri_image_ref=text(before.get("imageRef"), 512),
                    cri_ready_sha256=sha256(canonical(ready)), cri_final_sha256=sha256(canonical(final)),
                    runtime_spec_sha256=sha256(canonical(runtime_spec)))
    return runtime_spec


def _membership(raw):
    value = wrapper._raw(raw)
    require(value is not None, "kubernetes-worker-cgroup-unavailable")
    rows = [row[3:] for row in value.splitlines() if row.startswith("0::")]
    require(len(rows) == 1 and rows[0].startswith("/") and ".." not in PurePosixPath(rows[0]).parts,
            "kubernetes-worker-cgroup")
    return ROOT / rows[0].lstrip("/")


def _process(value, mounted, expected_pid=None, parent=None):
    fields(value, "pid stat stat_after status limits cgroup mountinfo namespaces")
    pid = integer(value["pid"], 1, 2**31 - 1)
    require(expected_pid is None or pid == expected_pid, "kubernetes-worker-pid")
    ticks, ppid = wrapper._stat(wrapper._raw(value["stat"]), pid)
    after, after_parent = wrapper._stat(wrapper._raw(value["stat_after"]), pid)
    require(ticks is not None and ticks == after == mounted["start_time_ticks"] and ppid == after_parent
            and (parent is None or ppid == parent), "kubernetes-worker-process-replaced")
    status = wrapper._raw(value["status"])
    require(status is not None, "kubernetes-worker-status-unavailable")
    rows = [line.split()[1:] for line in status.splitlines() if line.startswith("NSpid:")]
    require(len(rows) == 1 and 1 <= len(rows[0]) <= 16, "kubernetes-worker-nspid")
    nspids = [uint(item) for item in rows[0]]
    require(nspids[0] == pid and nspids[-1] == mounted["pid"], "kubernetes-worker-nspid")
    namespaces = fields(value["namespaces"], "pid mnt net user")
    derived_ns = {name: wrapper._raw(raw) for name, raw in namespaces.items()}
    require(derived_ns == mounted["namespaces"], "kubernetes-worker-namespace")
    limits, mounts = wrapper._raw(value["limits"]), wrapper._raw(value["mountinfo"])
    nofile = None
    if limits is not None:
        rows = [re.fullmatch(r"Max open files\s+(\d+|unlimited)\s+(\d+|unlimited)\s+files\s*", line)
                for line in limits.splitlines() if line.startswith("Max open files")]
        require(len(rows) == 1 and rows[0] is not None, "kubernetes-worker-nofile")
        nofile = {"soft": rows[0][1], "hard": rows[0][2]}
        for number in nofile.values():
            if number != "unlimited":
                uint(number)
    tmp = None
    if mounts is not None:
        rows = [line.split() for line in mounts.splitlines() if len(line.split()) > 6 and line.split()[4] == "/tmp"]
        require(len(rows) == 1, "kubernetes-worker-tmp-mount")
        parts = rows[0]
        require("-" in parts and parts.index("-") + 3 < len(parts), "kubernetes-worker-mountinfo")
        split = parts.index("-")
        tmp = {"filesystem": parts[split + 1], "mount_options": parts[5].split(","),
               "super_options": parts[split + 3].split(",")}
        require(tmp["filesystem"] == "tmpfs" and "rw" in tmp["mount_options"], "kubernetes-worker-tmp-mount")
        sizes = [option[5:] for option in tmp["super_options"] if option.startswith("size=")]
        require(len(sizes) == 1 and re.fullmatch(r"[0-9]+[kmg]?", sizes[0]), "kubernetes-worker-tmp-size")
        size = sizes[0]
        multiplier = {"k": 1024, "m": 1024**2, "g": 1024**3}.get(size[-1], 1)
        require(int(size[:-1] if multiplier != 1 else size) * multiplier == 16 * 1024**2,
                "kubernetes-worker-tmp-size")
    return {"pid": pid, "start_time_ticks": ticks, "parent_pid": ppid, "namespace_pids": nspids,
            "namespaces": derived_ns, "cgroup_path": str(_membership(value["cgroup"])), "nofile": nofile,
            "nofile_unavailable_reason": value["limits"]["unavailable_reason"], "tmp": tmp,
            "tmp_unavailable_reason": value["mountinfo"]["unavailable_reason"], "raw": value}


def _limit(value):
    if value == "max":
        return None
    return uint(value)


def _ancestry(value, leaf, identity, controls, *, native32_systemd_rounding=False):
    require(isinstance(value, list) and 2 <= len(value) <= 16, "kubernetes-cgroup-ancestry-bound")
    require(type(native32_systemd_rounding) is bool, "kubernetes-cgroup-cpu-policy")
    expected, rows, pod_index = PurePosixPath(leaf), [], None
    requested_cpu = {"quota": str(controls["cpu_quota"]), "period": str(controls["cpu_period"])}
    leaf_cpu, rounded = None, False
    effective = {"cpu": None, "memory.max": None, "memory.swap.max": None, "pids.max": None}
    for index, row in enumerate(value):
        fields(row, "path files")
        path = PurePosixPath(text(row["path"], 4096))
        require(str(path) == row["path"] and path == expected and path.is_relative_to(ROOT),
                "kubernetes-cgroup-ancestor-gap")
        expected = path.parent
        files = fields(row["files"], " ".join(ANCESTOR_FILES))
        parsed = {name: wrapper._raw(raw) for name, raw in files.items()}
        # The cgroup root has no resource limit knobs; missing root knobs impose
        # no limit. Every non-root ancestor must be observed, never guessed.
        require(path == ROOT or all(item is not None for item in parsed.values()),
                "kubernetes-cgroup-limit-unavailable")
        limits = {name: None if raw is None else raw.strip() for name, raw in parsed.items()}
        cpu = None
        if limits["cpu.max"] is not None:
            tokens = limits["cpu.max"].split()
            require(len(tokens) == 2 and uint(tokens[1]) > 0, "kubernetes-cgroup-cpu")
            cpu = None if tokens[0] == "max" else Fraction(uint(tokens[0]), uint(tokens[1]))
            if index == 0:
                rounded = tokens != [requested_cpu["quota"], requested_cpu["period"]]
                require(not rounded or native32_systemd_rounding
                        and requested_cpu == {"quota": "12500", "period": "100000"}
                        and tokens == ["13000", "100000"]
                        and path.parent.name == "kubelet-kubepods-pod" + identity["uid"].replace("-", "_") + ".slice"
                        and path.parent.parent == ROOT / "kubelet.slice" / "kubelet-kubepods.slice",
                        "kubernetes-cgroup-leaf-cpu")
                leaf_cpu = {"quota": tokens[0], "period": tokens[1]}
        if cpu is not None:
            effective["cpu"] = cpu if effective["cpu"] is None else min(cpu, effective["cpu"])
        for name in ("memory.max", "memory.swap.max", "pids.max"):
            number = None if limits[name] is None else _limit(limits[name])
            if number is not None:
                effective[name] = number if effective[name] is None else min(number, effective[name])
        if limits["pids.current"] is not None:
            uint(limits["pids.current"])
        if index == 0:
            require(limits["memory.max"] == str(controls["memory"]) and limits["memory.swap.max"] == "0"
                    and path.name in (identity["container_id"], "cri-containerd-" + identity["container_id"] + ".scope"),
                    "kubernetes-cgroup-leaf")
        uid_spellings = (identity["uid"], identity["uid"].replace("-", "_"))
        pod_names = {prefix + uid + suffix for uid in uid_spellings for prefix, suffix in
                     (("pod", ""), ("kubepods-pod", ".slice"), ("kubepods-burstable-pod", ".slice"),
                      ("kubepods-besteffort-pod", ".slice"), ("kubelet-kubepods-pod", ".slice"))}
        if index > 0 and path.name in pod_names:
            if path.name.startswith("kubelet-kubepods-pod"):
                require(path.parent == ROOT / "kubelet.slice" / "kubelet-kubepods.slice",
                        "kubernetes-kubelet-pod-parent")
            require(pod_index is None and limits["pids.max"] == str(POD_PIDS), "kubernetes-pod-pids-limit")
            pod_index = index
        rows.append({"path": str(path), "limits": limits, "files": files})
    require(rows[-1]["path"] == str(ROOT) and pod_index is not None, "kubernetes-cgroup-ancestry-incomplete")
    require(leaf_cpu is not None and (not rounded or rows[pod_index]["limits"]["cpu.max"] == "13000 100000"),
            "kubernetes-cgroup-rounded-pod-cpu")
    require(effective == {"cpu": Fraction(int(leaf_cpu["quota"]), int(leaf_cpu["period"])),
                          "memory.max": controls["memory"], "memory.swap.max": 0, "pids.max": POD_PIDS},
            "kubernetes-cgroup-effective-limits")
    return {"ancestors": rows, "pod_index": pod_index, "leaf_pids_max": rows[0]["limits"]["pids.max"],
            "effective_pids_max": str(POD_PIDS), "effective_memory_max": str(controls["memory"]),
            "effective_swap_max": "0", "effective_cpu": leaf_cpu, "requested_cpu": requested_cpu,
            "effective_cpu_matches_requested": not rounded,
            "cpu_limit_policy": "native-d32-systemd-rounded-cap" if rounded else "exact-requested"}


def _oci_path(spec, leaf, identifier):
    requested = text(spec["linux"].get("cgroupsPath"), 4096)
    if ":" in requested:
        parts = requested.split(":")
        require(len(parts) == 3 and parts == [leaf.parent.name, "cri-containerd", identifier],
                "kubernetes-runtime-cgroup-path")
    else:
        require(requested.startswith("/") and ".." not in PurePosixPath(requested).parts
                and ROOT / requested.lstrip("/") == leaf, "kubernetes-runtime-cgroup-path")


def validate(directory: Path, *, arm: str, density: int, pod_ready: dict, pod_final: dict,
             cri_ready: dict, cri_final: dict, worker: dict, observations: list,
             expected_connections: int | None, expected_snapshots: int = 6,
             startup_protocol=model.CURRENT_STARTUP_PROTOCOL) -> dict:
    """Replay a clean app Pod. Outer replay binds worker identity and signal calls.

    ``observations`` contains controller-bracketed worker reads, one per numbered
    wrapper snapshot. Its clocks must not be compared to wrapper elapsed values.
    """
    controls = docker_model.resources(arm, density)
    require(arm in ("lsf", "native") and type(expected_snapshots) is int and expected_snapshots in (0, 6),
            "kubernetes-resource-preset")
    fields(worker, "name uid container_id")
    text(worker["name"], 253)
    text(worker["uid"], 253)
    _id(worker["container_id"])
    controls = {key: value for key, value in controls.items() if key not in ("nofile_soft", "nofile_hard")}
    controls["pids_limit"] = POD_PIDS
    identity = _pod(pod_ready, pod_final, arm, controls, worker, startup_protocol=startup_protocol)
    runtime_spec = _cri(cri_ready, cri_final, identity, arm, controls)
    identity.update(provider="kubernetes-containerd", worker=worker)
    require(isinstance(observations, list) and len(observations) == expected_snapshots,
            "kubernetes-node-observation-count")
    # Verify leaf limits before allowing the shared parser's explicit provider
    # PID representation. Dynamic observations are subsequently bound by identity.
    ancestries = []
    previous = 0
    for index, row in enumerate(observations, 1):
        fields(row, "snapshot_index started_nanos finished_nanos wrapper child cgroups")
        require(integer(row["snapshot_index"]) == index, "kubernetes-node-observation-order")
        start, end = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(previous <= start <= end, "kubernetes-node-observation-window")
        previous = end
        leaf = _membership(row["wrapper"]["cgroup"])
        require(leaf == _membership(row["child"]["cgroup"]), "kubernetes-worker-crossed-cgroup")
        _oci_path(runtime_spec, leaf, identity["container_id"])
        ancestries.append(_ancestry(row["cgroups"], leaf, identity, controls,
                                    native32_systemd_rounding=arm == "native" and density == 32))
    leaf_pids = ancestries[0]["leaf_pids_max"] if ancestries else None
    require(all(row["leaf_pids_max"] == leaf_pids for row in ancestries), "kubernetes-leaf-pids-changed")
    observed_controls = dict(controls)
    if ancestries:
        cpu = ancestries[0]["effective_cpu"]
        require(all(row["effective_cpu"] == cpu for row in ancestries), "kubernetes-effective-cpu-changed")
        observed_controls.update(cpu_quota=int(cpu["quota"]), cpu_period=int(cpu["period"]))
    result = wrapper.validate_observations(directory, arm=arm, density=density, container_id=identity["container_id"],
        identity=identity, controls=observed_controls, expected_snapshots=expected_snapshots,
        expected_connections=expected_connections, leaf_pids_max=leaf_pids)
    result["requested_controls"] = controls
    fixed = None
    for row, mounted, ancestry in zip(observations, result["snapshots"], ancestries):
        owner = _process(row["wrapper"], mounted["wrapper"], identity["host_wrapper_pid_at_ready"])
        child = _process(row["child"], mounted["child"], parent=owner["pid"])
        current = [{key: process[key] for key in ("pid", "start_time_ticks", "namespaces", "cgroup_path")}
                   for process in (owner, child)]
        if fixed is None:
            fixed = current
        require(current == fixed, "kubernetes-worker-identity-changed")
        for name in ("cpu.max", "memory.max", "memory.swap.max", "pids.max"):
            raw = wrapper._raw(mounted["cgroup"]["files"][name])
            require(raw is None or raw.strip() == ancestry["ancestors"][0]["limits"][name],
                    "kubernetes-mounted-leaf-crossed")
        mounted["provider"] = {"started_nanos": row["started_nanos"], "finished_nanos": row["finished_nanos"],
                               "wrapper": owner, "child": child, "cgroup": ancestry}
    result["provider"] = {"name": "kubernetes-containerd", "runtime_type": cri_ready["info"]["runtimeType"],
                          "runtime_spec": runtime_spec, "worker": worker, "pod_pids_limit": POD_PIDS,
                          "process_observations_available": bool(observations),
                          "process_observations_unavailable_reason": None if observations else "seed-without-snapshots",
                          "resource_scope": "leaf usage; ancestor limits only; no parent usage added"}
    return result
