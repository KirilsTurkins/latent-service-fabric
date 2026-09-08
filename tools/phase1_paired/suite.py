"""Pair ordering, supervised identities, immutable controls and complete raw rows."""

from pathlib import Path

from ..phase1_evidence.common import fields, integer, read_json, require, text, uint
from . import candidate, control
from .artifacts import Artifacts, bootstrap
from .common import METHOD, PREFIX, build_controls, host_controls, identity, plan


def validate(path: Path):
    path = path.resolve()
    value = fields(read_json(path), "schema method profile plan runs artifacts control_build candidate_guest_sources", "historical_method_sources")
    require(value["schema"] == PREFIX + "suite.v1" and value["method"] == METHOD, "invalid-paired-suite")
    plan(value["plan"])
    require(value["profile"] == value["plan"]["profile"] and value["plan"]["repetition"] == 1, "paired-suite-plan-mismatch")
    artifacts = Artifacts(path.parent, value["artifacts"])
    built = bootstrap(artifacts, value["control_build"], value["candidate_guest_sources"])
    full = value["profile"] == "full"
    method_sources = value.get("historical_method_sources")
    require(not full or method_sources is not None, "full-pair-missing-retained-method-source")
    if method_sources is not None:
        expected_paths = ["apps/latentd/src/bin/phase0_baseline/" + name + ".rs" for name in ("run", "activation", "timing", "definitions")]
        expected_paths += ["crates/latent-wasmtime/src/" + name + ".rs" for name in ("lib", "backend")]
        require(isinstance(method_sources, list) and len(method_sources) == len(expected_paths), "incomplete-historical-method-source")
        require({item.get("path") for item in method_sources} == set(expected_paths), "crossed-historical-method-source")
        for item in method_sources:
            fields(item, "path artifact")
            artifacts.path(item["artifact"])
    expected_order = [(repetition, arm) for repetition in range(1, (7 if full else 1) + 1)
                      for arm in (("control", "candidate") if repetition % 2 else ("candidate", "control"))]
    require(isinstance(value["runs"], list) and 1 <= len(value["runs"]) <= len(expected_order), "invalid-paired-run-count")
    records, previous, seen_processes, arm_identities, controls = [], 0, set(), {}, None
    for row, (repetition, arm) in zip(value["runs"], expected_order):
        fields(row, "repetition arm status reason identity command raw process cleanup host_after started_micros finished_micros")
        require(type(row["repetition"]) is int and row["repetition"] == repetition and row["arm"] == arm, "paired-order-changed")
        started, finished = uint(row["started_micros"]), uint(row["finished_micros"])
        require(previous <= started <= finished, "overlapping-or-reordered-paired-processes")
        previous = finished
        observed = row["identity"]
        identity(observed, arm, full=full)
        shared = {"host": host_controls(observed["environment"]), "build": build_controls(observed["build"])}
        if controls is None:
            controls = shared
        require(shared == controls, "paired-host-or-build-confound")
        fixed = {key: observed[key] for key in ("source", "build", "binary", "fixtures")}
        require(arm not in arm_identities or arm_identities[arm] == fixed, "paired-arm-identity-changed")
        arm_identities[arm] = fixed
        if arm == "control":
            require(observed["source"] == built["source"] and observed["build"] == built["build"], "control-not-bound-to-bootstrap")
            for key, ref in (("binary", built["binary"]), ("fixtures", built["component"])):
                actual = observed[key] if key == "binary" else observed[key][0]
                require(all(actual[name] == ref[name] for name in ("sha256", "bytes")), "control-execution-input-mismatch")
        else:
            for name, observed_ref in (("collector", observed["binary"]), ("echo-capsule.wasm", observed["fixtures"][0])):
                ref = artifacts.rows.get("reproduction/candidate/" + name)
                require(ref is not None and all(ref[key] == observed_ref[key] for key in ("sha256", "bytes")), "candidate-reproduction-missing")
        selected = dict(value["plan"], repetition=repetition)
        require(row["status"] in ("passed", "failed"), "invalid-paired-run-status")
        directory = f"pair-{repetition:02}/{arm}/"
        for filename, expected in (("identity.json", observed), ("plan.json", selected)):
            require(directory + filename in artifacts.rows and artifacts.json(artifacts.rows[directory + filename]) == expected,
                    "per-run-input-not-bound")
        command(row["command"], arm, selected)
        if row["status"] == "failed":
            require(row["reason"] == "collector-failed", "invalid-paired-failure-reason")
            if row["raw"] is not None:
                artifacts.path(row["raw"])  # Partial JSON is retained, never selected as passing data.
            for key in ("process", "cleanup", "host_after"):
                if row[key] is not None:
                    artifacts.path(row[key])
            records.append({"arm": arm, "repetition": repetition, "status": "failed", "reason": row["reason"]})
            continue
        require(row["reason"] is None and row["raw"] is not None, "passed-pair-without-raw")
        expected_raw = directory + ("baseline.json" if arm == "control" else "candidate.json")
        require(row["raw"]["path"] == expected_raw, "crossed-paired-raw-artifact")
        process = receipt(artifacts, row, directory)
        process_identity = (process["process_id"], uint(process["start_time_ticks"]))
        require(process_identity not in seen_processes, "paired-process-reused")
        seen_processes.add(process_identity)
        after = artifacts.json(row["host_after"])
        require(host_controls(after) == controls["host"], "paired-host-changed-during-run")
        raw = artifacts.json(row["raw"])
        result = (control.parse(raw, selected, observed, built) if arm == "control" else
                  candidate.parse(raw, selected, observed, artifacts, artifacts.path(row["raw"])))
        require(result["process_identity"] in (None, process_identity), "candidate-probed-another-process")
        result.update({"arm": arm, "repetition": repetition, "status": "passed", "reason": None,
                       "raw": row["raw"], "identity": observed,
                       "parent_elapsed_micros": str(finished - started), "process_identity":
                       {"process_id": process_identity[0], "start_time_ticks": str(process_identity[1])}})
        records.append(result)
    return {"suite": value, "records": records, "controls": controls,
            "complete": len(records) == len(expected_order) and all(row["status"] == "passed" for row in records)}


def receipt(artifacts, row, directory):
    for key, filename in (("process", "process.json"), ("cleanup", "parent-cleanup.json"), ("host_after", "host-after.json")):
        require(row[key] is not None and row[key]["path"] == directory + filename, "crossed-parent-receipt")
    process = fields(artifacts.json(row["process"]), "process_id start_time_ticks reaped output_closed exit_code")
    integer(process["process_id"], 1)
    require(uint(process["start_time_ticks"]) > 0 and process["reaped"] is True and process["output_closed"] is True
            and type(process["exit_code"]) is int and process["exit_code"] == 0, "paired-process-not-reaped-cleanly")
    require(artifacts.json(row["cleanup"]) == {"removed": True}, "paired-parent-cleanup-failed")
    return process


def command(value, arm, selected):
    require(isinstance(value, list) and 1 <= len(value) <= 64, "invalid-paired-command")
    for argument in value:
        text(argument, 8192)
    if arm == "candidate":
        require(value[1:] == ["--exact", "standalone::measurements::comparison::phase1_comparison_collector",
                             "--ignored", "--nocapture", "--test-threads=1"], "candidate-command-changed")
    else:
        require(len(value) % 2 == 1, "invalid-control-command")
        pairs = list(zip(value[1::2], value[2::2], strict=True))
        options = dict(pairs)
        require(len(options) == len(pairs), "duplicate-control-option")
        expected = {"--mode": "full", "--profile-workload": "warm-execution",
                    "--warm-samples": str(selected["warmup_samples"] + selected["measured_samples"]),
                    "--fuel": "10000000000", "--memory-bytes": "16777216", "--pool-capacity": "2",
                    "--pool-queue-capacity": "3", "--runtime-workers": "2", "--wasmtime-allocator": "on-demand",
                    "--wasmtime-copy-on-write-images": "true", "--prepared-cache-enabled": "true"}
        require(set(options) == set(expected) | {"--capsule", "--executable-harness-probe", "--parent-launch-unix-micros", "--output-json", "--output-report"}
                and all(options[key] == item for key, item in expected.items()), "control-command-changed")
