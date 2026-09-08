"""Parent-observed ownership and sampled resource semantics."""

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
    fields(value, "scope process_membership cpu.max cpu.stat memory.max memory.current memory.stat memory.events cpu.pressure memory.pressure io.pressure")
    require(value["scope"] == "runner-cgroup-shared", "unmatched-cgroup-attribution")
    text(value["process_membership"], 16384)
    for name, item in value.items():
        if name not in ("scope", "process_membership") and item is not None:
            text(item, 64 * 1024, empty=True)


def resources(value, server_owner, client_owner):
    fields(value, "server client cgroup")
    result = {"server": samples(value["server"], server_owner),
              "client": samples(value["client"], client_owner)}
    pair = fields(value["cgroup"], "before after")
    for name in ("before", "after"):
        cgroup(pair[name])
    require(pair["before"]["process_membership"] == pair["after"]["process_membership"],
            "changed-cgroup-membership")
    return result
