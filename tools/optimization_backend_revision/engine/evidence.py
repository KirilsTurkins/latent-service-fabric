"""Closed five-row source/configuration population with owned-process replay."""
from pathlib import Path

from tools.optimization_cache_lookup.evidence import host_controls
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import fields, hash_file, read_json, require, uint, verify_artifact
from tools.optimization_evidence.resources import cgroup, clean, process
from tools.optimization_revision_evidence.identity import source
from . import aggregate, builds, fixtures, model

MAX_AGGREGATE_BYTES = 8 * 1024**2
ROW_FIELDS = ("repetition sequence_ordinal variant engine_profile_id status reason command started_micros finished_micros "
              "identity plan process raw log cleanup host_before host_after cgroup_before cgroup_after")


def validate_suite(path):
    from .parse import parse
    path = Path(path)
    checksum = hash_file(path, MAX_AGGREGATE_BYTES)
    suite = read_json(path, MAX_AGGREGATE_BYTES)
    require(hash_file(path, MAX_AGGREGATE_BYTES) == checksum, "engine-suite-changed-during-read")
    fields(suite, "schema profile plan builds runner_source runner_source_after status reason elapsed_nanos runs artifacts")
    require(suite["schema"] == model.SCHEMA and suite["plan"] == model.suite_plan(suite["profile"]),
            "engine-suite-plan-crossed")
    require(suite["status"] in ("passed", "failed")
            and suite["reason"] == (None if suite["status"] == "passed" else "collection-failed"), "engine-suite-status")
    elapsed = uint(suite["elapsed_nanos"])
    require(elapsed <= model.SUITE_SECONDS * 10**9, "engine-suite-time-bound")
    source(suite["runner_source"])
    require(suite["runner_source"]["clean"] is True and suite["runner_source"] == suite["runner_source_after"],
            "engine-runner-source-crossed")
    build = read_json(verify_artifact(path.parent, suite["builds"], MAX_AGGREGATE_BYTES))
    artifacts = Artifacts(path.parent, suite["artifacts"])
    artifacts.path(suite["builds"])
    builds.validate(build, artifacts, suite["profile"])
    require(build["harness"]["source"] == suite["runner_source"], "engine-runner-build-crossed")
    require({row["path"] for row in inventory(path.parent)} == set(artifacts.rows), "engine-unregistered-artifact")
    manifest = fixtures.load(build["fixtures"], artifacts, build["harness"]["components"])
    expected = model.population(suite["profile"])
    require(isinstance(suite["runs"], list) and len(suite["runs"]) <= len(expected), "engine-owner-count")
    records, owners = [], set()
    prior, stable_host, stable_cgroup = 0, None, None
    failed = suite["status"] == "failed"
    for ordinal, row in enumerate(suite["runs"]):
        fields(row, ROW_FIELDS)
        selection = {key: row[key] for key in expected[ordinal]}
        require(selection == expected[ordinal], "engine-owner-order-or-profile-crossed")
        require(type(row["repetition"]) is int and type(row["sequence_ordinal"]) is int,
                "engine-owner-ordinal-type")
        selected = model.plan(suite["profile"], **selection)
        supplied = model.identity(build, row["variant"], row["host_before"])
        require(artifacts.json(row["plan"]) == selected and artifacts.json(row["identity"]) == supplied,
                "engine-owner-plan-or-identity-crossed")
        start, finish = uint(row["started_micros"]), uint(row["finished_micros"])
        require(prior <= start <= finish and (finish - start) * 1000 <= elapsed
                and finish - start <= (model.MAX_SECONDS + 10) * 1_000_000, "engine-overlapping-or-unbounded-owners")
        prior = finish
        before, after = host_controls(row["host_before"]), host_controls(row["host_after"])
        stable_host = before if stable_host is None else stable_host
        require(before == after == stable_host, "engine-host-controls-crossed")
        for name in ("cgroup_before", "cgroup_after"):
            cgroup(row[name])
            controls = {key: row[name][key] for key in ("scope", "process_membership", "resolution", "cpu.max", "memory.max")}
            stable_cgroup = controls if stable_cgroup is None else stable_cgroup
            require(controls == stable_cgroup, "engine-cgroup-controls-crossed")
        require(row["status"] in ("passed", "failed")
                and row["reason"] == (None if row["status"] == "passed" else "collector-failed"), "engine-owner-status")
        binary = build["builds"][row["variant"]]["executables"]["backend"]
        argv = row["command"]
        require(isinstance(argv, list) and len(argv) == 6 and isinstance(argv[0], str)
                and argv[0].endswith("/" + binary["path"])
                and argv[1:] == ["--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"],
                "engine-collector-command-crossed")
        record = {**selection, "status": row["status"], "source": supplied["source"], "binary": supplied["binary"]}
        owner = None
        if row["process"] is not None:
            receipt = artifacts.json(row["process"])
            observed_owner = process(receipt, "artifact-identity-helper", binary["sha256"])
            owner = (observed_owner[0], uint(observed_owner[1]))
            require(owner not in owners and receipt["reaped"] is True and receipt["output_closed"] is True,
                    "engine-owner-not-reaped-or-reused")
            owners.add(owner)
            require(row["log"] is not None and row["process"]["path"] == row["log"]["path"] + ".process.json",
                    "engine-process-sidecar-crossed")
            artifacts.path(row["log"])
        require(row["cleanup"] is not None and artifacts.json(row["cleanup"]) == {"removed": True},
                "engine-owned-data-not-removed")
        if row["status"] == "failed":
            failed = True
            if row["raw"] is not None:
                artifacts.path(row["raw"])
            record.update(validated_attempts="0", validated_commands="0", attempt_count_complete=False,
                          raw_retained=row["raw"] is not None, native_cleanup_qualification="unavailable-failed-child")
        else:
            require(owner is not None and clean(receipt) and row["raw"] is not None, "engine-success-without-clean-process")
            raw_path = artifacts.path(row["raw"])
            require(raw_path.name == "engine.json", "engine-raw-filename")
            result = parse(read_json(raw_path, model.MAX_DOCUMENT_BYTES), selected, supplied, manifest,
                           build["fixtures"], artifacts, raw_path.parent)
            require(tuple(result["process_identity"]) == owner, "engine-raw-process-crossed")
            require(uint(result["elapsed_nanos"]) <= (finish - start) * 1000 + 1000, "engine-raw-outside-owned-process")
            record.update(aggregate.summarize(result))
        records.append(record)
    complete = len(records) == len(expected) and not failed
    require(suite["status"] != "passed" or complete, "engine-passed-suite-incomplete")
    return aggregate.aggregate(suite, checksum[0], build, records, complete, failed)
