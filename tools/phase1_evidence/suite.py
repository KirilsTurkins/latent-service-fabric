"""Retain every attempted collector run, including absent and truncated output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (KINDS, MAX_ARTIFACTS, PREFIX, REPETITIONS, EvidenceError, canonical,
                     fields, integer, read_json, require, text, uint, validate_identity,
                     validate_plan, verify_artifact)
from .raw import read_raw, same_plan


def validate_suite(path: Path) -> dict[str, Any]:
    path = path.resolve()
    suite = fields(read_json(path), "schema profile identity plans runs artifacts")
    require(suite["schema"] == PREFIX + "suite.v1" and suite["profile"] in ("smoke", "full"), "invalid-suite-schema")
    validate_identity(suite["identity"])
    plans = suite["plans"]
    require(isinstance(plans, dict) and 1 <= len(plans) <= len(KINDS) and set(plans) <= set(KINDS), "invalid-suite-plans")
    for kind, plan in plans.items():
        validate_plan(plan)
        require(plan["kind"] == kind and plan["profile"] == suite["profile"] and plan["repetition"] == 1, "suite-plan-mismatch")
    require(isinstance(suite["artifacts"], list) and len(suite["artifacts"]) <= MAX_ARTIFACTS, "artifact-count-limit")
    seen_artifacts = set()
    total_bytes = 0
    for item in suite["artifacts"]:
        artifact = verify_artifact(path.parent, item, maximum=1024**3)
        require(artifact not in seen_artifacts, "duplicate-artifact")
        seen_artifacts.add(artifact)
        total_bytes += uint(item["bytes"])
        require(total_bytes <= 2 * 1024**3, "suite-artifact-byte-limit")
    require(isinstance(suite["runs"], list) and len(suite["runs"]) <= 63, "invalid-suite-runs")
    seen_runs = set()
    seen_raw = set()
    records = []
    for run in suite["runs"]:
        fields(run, "kind repetition status reason report")
        kind, repetition = run["kind"], run["repetition"]
        require(kind in plans, "unplanned-run-kind")
        integer(repetition, 1, 21)
        require((kind, repetition) not in seen_runs, "duplicate-run")
        seen_runs.add((kind, repetition))
        require(run["status"] in ("passed", "failed"), "invalid-attempt-status")
        if run["status"] == "passed":
            require(run["reason"] is None and run["report"] is not None, "passed-attempt-without-report")
        else:
            text(run["reason"], 128)
        raw, validation_error, observed_host = None, None, None
        run_identity = suite["identity"]
        if run["report"] is not None:
            raw_path = verify_artifact(path.parent, run["report"])
            require(raw_path not in seen_raw, "raw-file-reused-for-run")
            seen_raw.add(raw_path)
            try:
                raw = read_raw(raw_path)
                header = raw["header"]
                identity_name = (raw_path.parent / "identity.json").relative_to(path.parent).as_posix()
                retained = {item["path"]: item for item in suite["artifacts"]}
                for item in raw["input_references"]:
                    name = (raw_path.parent / item["path"]).relative_to(path.parent).as_posix()
                    require(name in retained and all(retained[name][key] == item[key] for key in ("sha256", "bytes")),
                            "missing-retained-fixture-input")
                require(identity_name in retained, "missing-per-run-identity")
                run_identity = read_json(verify_artifact(path.parent, retained[identity_name]))
                validate_identity(run_identity)
                require(canonical(header["identity"]) == canonical(run_identity), "raw-per-run-identity-mismatch")
                require(all(canonical(run_identity[key]) == canonical(suite["identity"][key])
                            for key in ("source", "build", "binary", "fixtures")), "run-suite-identity-mismatch")
                require(same_plan(plans[kind], header["plan"], repetition), "raw-suite-plan-mismatch")
                require(raw["summary"]["status"] == run["status"], "raw-attempt-status-mismatch")
                if run["status"] == "passed":
                    observed_host = parent_receipts(path.parent, raw_path, suite["artifacts"], raw)
            except EvidenceError as error:
                if run["status"] == "passed":
                    raise
                validation_error = str(error)
                raw = None
        records.append({"attempt": run, "raw": raw, "validation_error": validation_error,
                        "identity": run_identity, "host_observations": observed_host})
    return {"document": suite, "runs": records}


def parent_receipts(root: Path, raw_path: Path, artifacts: list[Any], raw: dict[str, Any]) -> dict[str, Any]:
    expected = {name: (raw_path.parent / name).relative_to(root).as_posix()
                for name in ("process.json", "parent-cleanup.json", "host-after.json")}
    retained = {item["path"]: item for item in artifacts}
    require(all(path in retained for path in expected.values()), "missing-parent-receipt")
    process = fields(read_json(verify_artifact(root, retained[expected["process.json"]])),
                     "process_id start_time_ticks reaped output_closed exit_code")
    pid = integer(process["process_id"], 1)
    start = uint(process["start_time_ticks"])
    require(start > 0 and process["reaped"] is True and process["output_closed"] is True
            and type(process["exit_code"]) is int and process["exit_code"] == 0, "parent-did-not-reap-successful-collector")
    require(raw["samples"] and all(sample["resources"]["identity"] ==
            {"processId": pid, "startTimeTicks": str(start)} for sample in raw["samples"]), "crossed-parent-process-identity")
    cleanup = fields(read_json(verify_artifact(root, retained[expected["parent-cleanup.json"]])), "removed")
    require(cleanup["removed"] is True, "missing-parent-data-cleanup")
    after = read_json(verify_artifact(root, retained[expected["host-after.json"]]))
    identity_after = dict(raw["header"]["identity"], environment=after)
    validate_identity(identity_after)
    before = raw["header"]["identity"]["environment"]
    stable = canonical({key: value for key, value in before.items() if key != "load_before"}) == canonical(
        {key: value for key, value in after.items() if key != "load_before"})
    return {"before": before, "after": after, "stable_identity": stable}
