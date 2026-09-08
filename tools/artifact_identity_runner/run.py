"""One timed probe child; allocation profiling is always a separate run."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import time

from optimization_runner.cgroups import cgroup
from optimization_runner.processes import OwnedProcess
from . import resources
from .files import compress_folded, fingerprint, reference, total_bytes, warm, write_json
from .helpers import command, directory_bytes
from .model import MAX_FILE_BYTES, MAX_TOTAL_BYTES, run_record


def profile_reports(prefix: Path, printer: str, decompressor: str, output: Path,
                    deadline: int, remaining: int) -> dict:
    matches = list(prefix.parent.glob(prefix.name + "*.zst"))
    if len(matches) != 1:
        raise ValueError("heaptrack-raw-count")
    raw = matches[0]
    fingerprint(raw)
    report = prefix.parent / "heaptrack-report.txt"
    command([printer, str(raw)], report, 120, output, deadline,
            watched=prefix.parent, remaining=remaining)
    refs = {"raw": reference(raw, output), "report": reference(report, output)}
    interpreted = prefix.parent / "interpreted.heaptrack"
    command([decompressor, "--decompress", "--stdout", str(raw)], interpreted,
            120, output, deadline, maximum=MAX_FILE_BYTES, watched=prefix.parent, remaining=remaining)
    refs["interpreted"] = reference(interpreted, output)
    for kind in ("allocations", "peak"):
        path = prefix.parent / f"{kind}.folded"
        command([printer, "--file", str(raw), "--flamegraph-cost-type", kind,
                 "--print-peaks", "0", "--print-allocators", "0", "--print-temporary", "0",
                 "--print-flamegraph", str(path)], prefix.parent / f"{kind}.log",
                120, output, deadline, watched=prefix.parent, remaining=remaining)
        if path.stat().st_size == 0:
            raise ValueError("heaptrack-profile-empty")
        refs[kind] = compress_folded(path, output)
    return refs


def collect(record: dict, directory: Path, binary: dict, fixture: dict, output: Path,
            deadline: int, heaptrack_print: str, decompressor: str) -> None:
    """Update a pre-retained receipt even when acquisition or verification fails."""
    import resource  # Linux-only execution; the population/model remains portable.

    directory.mkdir(parents=True)
    record["warmup"] = warm(output / fixture["root"], fixture["files"], output)
    if reference(output / binary["path"], output) != binary:
        raise ValueError("retained-binary-mutated")
    remaining = MAX_TOTAL_BYTES - total_bytes(output)
    mode = record["mode"]
    usage = resource.getrusage(resource.RUSAGE_CHILDREN) if mode == "normal" else None
    owner = None
    first = completion = last = None
    peak = high_water = 0
    observed = 0
    last_sample = 0
    try:
        if time.monotonic_ns() >= deadline:
            raise TimeoutError("probe-deadline-before-spawn")
        owner = OwnedProcess(record["command"], directory / "probe.log", "identity-" + mode,
                             60 if mode == "normal" else 180, output,
                             overall_deadline_ns=deadline)
        record["process"] = owner.receipt
        while not owner.exited() or owner.selector.get_map():
            owner.poll()
            for event in owner.events[observed:]:
                value = event["record"]
                if value.get("event") == "ready" and record["ready"] is None:
                    write_json(directory / "ready.json", value)
                    record["ready"] = reference(directory / "ready.json", output)
                    record["probe_process"] = resources.bind(value["process_id"], owner,
                                                             output / binary["path"], binary["sha256"])
                    first = resources.sample(value["process_id"], record["probe_process"]["start_time_ticks"])
                    last = first
                elif value.get("event") == "measurement-complete" and completion is None:
                    write_json(directory / "result.json", value)
                    record["result"] = reference(directory / "result.json", output)
                    identity = record["probe_process"]
                    if identity is None or value.get("process_id") != identity["process_id"]:
                        raise ValueError("result-probe-association")
                    completion = resources.sample(identity["process_id"], identity["start_time_ticks"])
                    last = completion
                    if value.get("outcome") != "passed":
                        raise ValueError("probe-operation-failed")
                else:
                    raise ValueError("unexpected-probe-event")
            observed = len(owner.events)
            if completion is None and record["probe_process"] is not None and time.monotonic_ns() - last_sample >= 100_000_000:
                identity = record["probe_process"]
                if not resources.exited(identity):
                    last = resources.sample(identity["process_id"], identity["start_time_ticks"])
                last_sample = time.monotonic_ns()
            if directory_bytes(directory) > remaining:
                raise ValueError("profile-artifact-total-bound")
            for item in (first, completion, last):
                if item:
                    peak = max(peak, int(item["rss_bytes"]))
                    high_water = max(high_water, int(item["kernel_high_water_rss_bytes"]))
            time.sleep(0.005)
        if completion is None:
            raise ValueError("probe-result-missing")
    finally:
        if owner is not None:
            owner.close()
            record["process"] = owner.receipt
            if usage is not None:
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                record["cpu"] = {
                    "scope": "whole-owned-process-rusage-children",
                    "user_micros": str(round((Decimal(str(after.ru_utime)) - Decimal(str(usage.ru_utime))) * Decimal(1_000_000))),
                    "system_micros": str(round((Decimal(str(after.ru_stime)) - Decimal(str(usage.ru_stime))) * Decimal(1_000_000))),
                }
            if record["probe_process"]:
                record["probe_process"]["observed_exited"] = resources.exited(record["probe_process"])
            record["resources"] = {
                "probe": {"before": first, "completion": completion, "last_live": last,
                          "maximum_observed_rss_bytes": str(peak),
                          "kernel_high_water_rss_bytes": str(high_water), "sample_interval_millis": 100,
                          "before_semantics": "first-observed-after-ready-not-guaranteed-pre-operation",
                          "scope": "normal-probe" if mode == "normal" else "heaptrack-instrumented-probe"},
                "wrapper": owner.resources(), "cgroup": cgroup(),
            }
            record["log"] = reference(directory / "probe.log", output)
    if record["process"]["exit_code"] != 0 or not record["probe_process"]["observed_exited"]:
        raise ValueError("probe-exit-failed")
    if mode == "allocation":
        record["profile_refs"] = profile_reports(directory / "heaptrack", heaptrack_print, decompressor,
                                                output, deadline, remaining)
    record.update(status="passed", reason=None)


def make_run(pair: int, arm: str, size: str, operation: str, mode: str,
             suite: dict, output: Path, heaptrack: str) -> tuple[dict, Path]:
    fixture = suite["fixtures"][size]
    size_bytes = int(fixture["manifest"]["component_bytes"])
    iterations = max(1, min(4096, 64 * 1024 * 1024 // size_bytes)) if suite["profile"] == "full" and operation == "hash" else 1
    directory = output / "runs" / f"{pair:02}-{arm}-{size}-{operation}-{mode}"
    argv = [str(output / suite["builds"][arm]["binary"]["path"]), "measure", "--operation", operation,
            "--fixture", str(output / fixture["root"]), "--iterations", str(iterations)]
    if mode == "allocation":
        argv = [heaptrack, "--output", str(directory / "heaptrack"), *argv]
    return run_record(pair, arm, size, operation, mode, argv), directory
