"""Bounded source-clock RSS samples; phase membership uses both read endpoints."""
from tools.optimization_evidence.common import decode, distribution, fields, require, uint

MAX_BYTES = 16 * 1024**2
MAX_ROW_BYTES = 256
MAX_ROWS = {"initial": 40000, "reopen": 20000}
PERIOD_NANOS = 100_000_000
COLUMNS = ("started_nanos", "finished_nanos", "pid", "start_ticks", "rss_bytes",
           "vm_hwm_bytes", "user_ticks", "system_ticks")


def read(source, mode, *, pid, start_ticks, elapsed_nanos):
    """Read an already identity-bound artifact without guessing a parent origin."""
    require(mode in MAX_ROWS and type(pid) is int and pid > 0
            and type(start_ticks) is int and start_ticks >= 0
            and type(elapsed_nanos) is int and elapsed_nanos >= 0,
            "catalog-sampler-owner")
    rows, total, previous_finish, previous_cpu, previous_hwm = [], 0, 0, (0, 0), 0
    while data := source.readline(MAX_ROW_BYTES + 1):
        total += len(data)
        require(total <= MAX_BYTES and len(data) <= MAX_ROW_BYTES and data.endswith(b"\n"),
                "catalog-sampler-byte-bound")
        require(len(rows) < MAX_ROWS[mode], "catalog-sampler-row-bound")
        value = decode(data, MAX_ROW_BYTES)
        require(isinstance(value, list) and len(value) == len(COLUMNS), "catalog-sampler-columns")
        parsed = tuple(uint(item) for item in value)
        started, finished, process, ticks, rss, hwm, user, system = parsed
        require(previous_finish <= started <= finished <= elapsed_nanos, "catalog-sampler-clock")
        require((process, ticks) == (pid, start_ticks), "catalog-sampler-identity")
        require(hwm >= rss and hwm >= previous_hwm and user >= previous_cpu[0]
                and system >= previous_cpu[1], "catalog-sampler-counters")
        rows.append(parsed)
        previous_finish, previous_cpu, previous_hwm = finished, (user, system), hwm
    require(bool(rows), "catalog-sampler-empty")
    return rows


def phase(rows, started_nanos, finished_nanos):
    require(type(started_nanos) is int and type(finished_nanos) is int
            and 0 <= started_nanos <= finished_nanos, "catalog-sampler-phase-clock")
    selected = [row for row in rows if started_nanos <= row[0] <= row[1] <= finished_nanos]
    return {"scope": "fixed-100ms-source-samples-wholly-inside-apply-read-window",
            "sample_count": str(len(selected)),
            "rss_max_bytes": str(max(row[4] for row in selected)) if selected else None,
            "vm_hwm_max_bytes": str(max(row[5] for row in selected)) if selected else None}


def cadence(rows):
    return distribution([right[0] - left[0] for left, right in zip(rows, rows[1:])])


def validate(value, mode, artifacts, directory, owner, elapsed, before_node, final_started):
    if mode == "allocation":
        require(value == {"enabled": False, "reason": "allocation-mode"}, "catalog-profiled-source-sampler")
        return []
    fields(value, "enabled joined source requested_period_nanos samples process_id start_time_ticks "
                  "minimum_start_gap_nanos maximum_start_gap_nanos file")
    require(value["enabled"] is True and value["joined"] is True and value["source"] == "proc-self-status-and-stat"
            and value["requested_period_nanos"] == str(PERIOD_NANOS)
            and (uint(value["process_id"]), uint(value["start_time_ticks"])) == owner,
            "catalog-source-sampler-receipt")
    require(value["file"]["path"] == "sampler.jsonl" and uint(value["file"]["bytes"]) <= MAX_BYTES,
            "catalog-source-sampler-file")
    path = artifacts.nested(directory, value["file"])
    with path.open("rb") as source:
        rows = read(source, mode, pid=owner[0], start_ticks=owner[1], elapsed_nanos=elapsed)
    require(value["samples"] == str(len(rows)) and rows[0][1] <= before_node and rows[-1][1] <= final_started,
            "catalog-source-sampler-window")
    gaps = [right[0] - left[0] for left, right in zip(rows, rows[1:])]
    require(value["minimum_start_gap_nanos"] == (str(min(gaps)) if gaps else None)
            and value["maximum_start_gap_nanos"] == (str(max(gaps)) if gaps else None),
            "catalog-source-sampler-cadence")
    return rows
