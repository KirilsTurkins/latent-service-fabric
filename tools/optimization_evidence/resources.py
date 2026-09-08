"""Parent-observed ownership and sampled resource semantics."""

import re

from .common import digest, fields, integer, require, text, uint


def process(value, role, executable):
    fields(value, "process_id start_time_ticks role executable_sha256 reaped output_closed exit_code")
    integer(value["process_id"], 1)
    require(uint(value["start_time_ticks"]) > 0, "missing-process-start-time")
    require(value["role"] == role and value["executable_sha256"] == executable,
            "crossed-process-executable")
    digest(value["executable_sha256"])
    require(type(value["reaped"]) is bool and type(value["output_closed"]) is bool,
            "invalid-process-ownership")
    if value["exit_code"] is not None:
        integer(value["exit_code"], -255, 255)
    return (value["process_id"], value["start_time_ticks"])


def clean(value):
    return value["reaped"] is True and value["output_closed"] is True and value["exit_code"] == 0


def snapshot(value, owner):
    fields(value, "process_id start_time_ticks rss_bytes cpu_user_ticks cpu_system_ticks threads fd_count read_bytes write_bytes")
    require((value["process_id"], value["start_time_ticks"]) == owner, "crossed-resource-process")
    integer(value["process_id"], 1)
    for name in ("rss_bytes", "cpu_user_ticks", "cpu_system_ticks", "read_bytes", "write_bytes"):
        uint(value[name])
    integer(value["threads"], 1, 65536)
    integer(value["fd_count"], 0, 1_000_000)


def samples(value, owner):
    fields(value, "before after last_live peak_rss_bytes sample_interval_millis peak_semantics")
    for name in ("before", "after", "last_live"):
        snapshot(value[name], owner)
    require(value["sample_interval_millis"] == 100
            and value["peak_semantics"] == "maximum-observed-rss-not-instantaneous-peak",
            "changed-resource-sampling-boundary")
    peak = uint(value["peak_rss_bytes"])
    require(peak >= max(uint(value[name]["rss_bytes"]) for name in ("before", "after", "last_live")),
            "resource-peak-below-observation")
    result = {"sampled_peak_rss_bytes": str(peak),
              "last_live_rss_bytes": value["last_live"]["rss_bytes"]}
    for name in ("cpu_user_ticks", "cpu_system_ticks", "read_bytes", "write_bytes"):
        before, after = uint(value["before"][name]), uint(value["after"][name])
        require(after >= before, "resource-counter-regressed")
        result[name] = str(after - before)
    return result


def cgroup(value):
    names = ("cpu.max", "cpu.stat", "memory.max", "memory.current", "memory.stat",
             "memory.events", "cpu.pressure", "memory.pressure", "io.pressure")
    fields(value, "scope process_membership resolution errors " + " ".join(names))
    require(value["scope"] == "runner-cgroup-shared", "unmatched-cgroup-attribution")
    text(value["process_membership"], 16384, empty=True)
    errors = value["errors"]
    require(isinstance(errors, dict) and set(errors) <= set(names) | {"process_membership", "mountinfo", "resolution"}
            and all(reason in {"missing", "permission-denied", "oversized", "invalid", "unavailable",
                               "ambiguous", "membership-changed"} for reason in errors.values()),
            "unbounded-cgroup-error")
    resolution = fields(value["resolution"], "status path mount_id mount_root mount_point device inode")
    require(resolution["status"] in ("resolved", "unsupported"), "invalid-cgroup-resolution")
    if resolution["status"] == "unsupported":
        require(all(item is None for key, item in resolution.items() if key != "status")
                and all(value[name] is None for name in names)
                and any(key in errors for key in ("process_membership", "mountinfo", "resolution")),
                "fabricated-unavailable-cgroup-counter")
        return
    for name in ("path", "mount_root", "mount_point"):
        item = text(resolution[name])
        require(item.startswith("/") and all(part not in (".", "..") for part in item.split("/")),
                "invalid-cgroup-path")
    for name in ("mount_id", "inode"):
        require(uint(resolution[name]) > 0, "missing-cgroup-identity")
    require(isinstance(resolution["device"], str) and re.fullmatch(r"[0-9]+:[0-9]+", resolution["device"]),
            "invalid-cgroup-device")
    for name in names:
        if value[name] is None:
            require(name in errors, "unexplained-missing-cgroup-counter")
        else:
            text(value[name], 64 * 1024, empty=True)
            require(name not in errors, "cgroup-error-has-measured-counter")


def resources(value, server_owner, client_owner):
    fields(value, "server client cgroup")
    result = {"server": samples(value["server"], server_owner),
              "client": samples(value["client"], client_owner)}
    require(all(uint(value[role]["after"]["rss_bytes"]) > 0 for role in ("server", "client")),
            "missing-live-completion-resource-sample")
    pair = fields(value["cgroup"], "before after")
    for name in ("before", "after"):
        cgroup(pair[name])
    if all(pair[name]["resolution"]["status"] == "resolved" for name in ("before", "after")):
        require(pair["before"]["process_membership"] == pair["after"]["process_membership"]
                and pair["before"]["resolution"] == pair["after"]["resolution"], "changed-cgroup-membership")
    return result
