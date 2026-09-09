"""Strict ownership suite replay, retaining failed runs without qualification."""
from pathlib import Path

from tools.artifact_identity_evidence.runs import allocation, probe_resources
from tools.optimization_cache_lookup.evidence import host_controls, tools as validate_tools
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import fields, hash_file, read_json, require, uint, verify_artifact
from tools.optimization_evidence.resources import cgroup, process
from tools.optimization_revision_evidence.identity import source
from . import aggregate, allocations, builds, events, fixtures, model
from .parse import parse

ROW_FIELDS = ("repetition variant mode shape status reason command started_micros finished_micros plan identity ready result raw "
              "process probe_process resources cpu profile_refs log cleanup host_before host_after cgroup_before cgroup_after")


def validate_suite(path):
    path = Path(path)
    checksum = hash_file(path, model.MAX_DOCUMENT_BYTES)
    suite = read_json(path, model.MAX_DOCUMENT_BYTES)
    require(hash_file(path, model.MAX_DOCUMENT_BYTES) == checksum, "ownership-suite-changed-during-read")
    fields(suite, "schema profile plan builds runner_source runner_source_after status reason elapsed_nanos tools symbols runs artifacts")
    require(suite["schema"] == model.SCHEMA and suite["plan"] == model.suite_plan(suite["profile"]), "ownership-suite-plan-changed")
    require(suite["status"] in ("passed", "failed") and suite["reason"] == (None if suite["status"] == "passed" else "collection-failed"),
            "ownership-suite-status")
    elapsed = uint(suite["elapsed_nanos"])
    require(elapsed <= model.STAGE_SECONDS * 10**9, "ownership-collection-stage-time-bound")
    source(suite["runner_source"])
    require(suite["runner_source"] == suite["runner_source_after"], "ownership-runner-source-changed")
    build = read_json(verify_artifact(path.parent, suite["builds"], model.MAX_DOCUMENT_BYTES))
    binaries = {row["executables"]["backend"]["path"] for row in build["builds"].values()}
    artifacts = Artifacts(path.parent, suite["artifacts"], binaries)
    artifacts.path(suite["builds"])
    builds.validate(build, artifacts, suite["profile"])
    require(build["harness"]["source"] == suite["runner_source"], "ownership-build-runner-crossed")
    require({row["path"] for row in inventory(path.parent)} == set(artifacts.rows), "ownership-unregistered-evidence-file")
    manifest_ref = build["fixture_generation"]["manifest"]
    manifest = fixtures.load(manifest_ref, artifacts, build["harness"]["components"])
    validate_tools(suite["tools"], artifacts, suite["status"] == "passed" or bool(suite["runs"]))
    require(isinstance(suite["symbols"], dict) and set(suite["symbols"]) <= {"control", "candidate"}
            and (not suite["runs"] or set(suite["symbols"]) == {"control", "candidate"}), "ownership-symbol-proof-set")
    for variant, proof in suite["symbols"].items():
        allocations.proofs(proof, build["builds"][variant]["executables"]["backend"], suite["tools"]["nm"], artifacts)
    expected = list(model.population(suite["profile"]))
    require(isinstance(suite["runs"], list) and len(suite["runs"]) <= len(expected), "ownership-suite-extra-runs")
    records, owners, previous, stable_host, stable_cgroup, stable_profile = [], set(), 0, None, None, None
    failed = suite["status"] == "failed"
    for ordinal, row in enumerate(suite["runs"]):
        fields(row, ROW_FIELDS)
        cell = (row["repetition"], row["variant"], row["mode"], row["shape"])
        require(cell == expected[ordinal], "ownership-suite-pair-or-shape-order")
        selected = model.plan(suite["profile"], row["repetition"], row["mode"], row["shape"])
        supplied = model.identity(build, row["variant"], row["host_before"])
        require(artifacts.json(row["plan"]) == selected and artifacts.json(row["identity"]) == supplied,
                "ownership-child-plan-or-identity-crossed")
        start, finish = uint(row["started_micros"]), uint(row["finished_micros"])
        require(previous <= start <= finish and (finish - start) * 1000 <= elapsed, "ownership-overlapping-processes")
        previous = finish
        before, after = host_controls(row["host_before"]), host_controls(row["host_after"])
        stable_host = before if stable_host is None else stable_host
        require(before == after == stable_host, "ownership-host-controls-changed")
        for name in ("cgroup_before", "cgroup_after"):
            cgroup(row[name])
            controls = {key: row[name][key] for key in ("scope", "process_membership", "resolution", "cpu.max", "memory.max")}
            stable_cgroup = controls if stable_cgroup is None else stable_cgroup
            require(controls == stable_cgroup, "ownership-cgroup-controls-changed")
        require(row["status"] in ("passed", "failed") and row["reason"] == (None if row["status"] == "passed" else "collector-failed"),
                "ownership-run-status")
        summary = {key: row[key] for key in ("repetition", "variant", "mode", "shape", "status")}
        binary = build["builds"][row["variant"]]["executables"]["backend"]
        if row["status"] == "failed":
            failed = True
            if row["process"] is not None:
                launcher = binary["sha256"] if row["mode"] == "normal" else suite["tools"]["heaptrack"]["sha256"]
                owner = process(row["process"], "identity-" + row["mode"], launcher)
                require(owner not in owners and row["process"]["reaped"] is True and row["process"]["output_closed"] is True,
                        "ownership-failed-process-not-cleaned")
                owners.add(owner)
                require(row["cleanup"] is not None and artifacts.json(row["cleanup"]) == {"removed": True},
                        "ownership-failed-data-directory-not-removed")
            if row["raw"] is not None:
                artifacts.path(row["raw"])
            summary.update(validated_invocations="0", raw_retained=row["raw"] is not None,
                           attempt_count_complete=False, native_cleanup_qualification="unavailable-failed-child")
        else:
            key, memory = probe_resources(row, binary, suite["tools"])
            require(key not in owners, "ownership-reused-process")
            owners.add(key)
            require(row["cleanup"] is not None and artifacts.json(row["cleanup"]) == {"removed": True}, "ownership-data-directory-not-removed")
            validate_command(row, binary, suite)
            ready, complete = events.parse(row, selected, manifest_ref, artifacts)
            raw = artifacts.json(row["raw"], model.MAX_DOCUMENT_BYTES)
            result = parse(raw, selected, supplied, manifest, manifest_ref["sha256"], artifacts, row["variant"])
            require(result["process_id"] == key[0] and uint(result["elapsed_nanos"]) <= uint(complete["elapsed_nanos"]),
                    "ownership-raw-process-or-clock-crossed")
            # Readiness follows fixture setup, and the first planned call follows
            # its explicit 100 ms hold. No population is hidden before ready.
            first = next(item for item in raw["samples"] if item["kind"] == "invoke")
            require(uint(first["construction_started_nanos"]) >= uint(ready["elapsed_nanos"]) + 100_000_000,
                    "ownership-first-call-before-readiness-hold")
            profile_key = result["engine_profile"], result["configuration_debug"]
            stable_profile = profile_key if stable_profile is None else stable_profile
            require(profile_key == stable_profile, "ownership-engine-config-controls-differ")
            summary.update(validated_invocations=result["work"]["invoke_attempts"], work=result["work"],
                           proofs=result["proofs"], factory_shutdown=result["factory_shutdown"],
                           compiler_after_shutdown=result["compiler_after_shutdown"],
                           prepared_runtimes_after_shutdown=result["prepared_runtimes_after_shutdown"],
                           raw_inputs_after_shutdown=result["raw_inputs_after_shutdown"],
                           process_identity={"process_id": key[0], "start_time_ticks": key[1]},
                           memory=memory, allocation_attribution=None, whole_process_allocations=None)
            if row["mode"] == "normal":
                require(row["profile_refs"] is None, "ownership-normal-child-was-profiled")
                cpu = fields(row["cpu"], "scope user_micros system_micros")
                require(cpu["scope"] == "whole-owned-process-rusage-children", "ownership-cpu-scope-changed")
                uint(cpu["user_micros"])
                uint(cpu["system_micros"])
                summary.update(cpu=cpu, timing=aggregate.normal(result))
            else:
                require(row["cpu"] is None, "ownership-profiled-cpu-presented-as-normal")
                whole = allocation(row, suite, artifacts)
                attributed = allocations.attribute(row, binary, suite["symbols"][row["variant"]], suite["tools"]["nm"], artifacts, whole)
                summary.update(cpu=None, timing=None, whole_process_allocations=whole, allocation_attribution=attributed)
        records.append(summary)
    complete = len(records) == len(expected) and not failed
    require(suite["status"] != "passed" or complete, "ownership-passed-suite-hides-incomplete-population")
    return aggregate.aggregate(suite, checksum[0], build, records, complete, failed)


def validate_command(row, binary, suite):
    argv = row["command"]
    prefix = 3 if row["mode"] == "allocation" else 0
    require(isinstance(argv, list) and len(argv) == prefix + 6 and all(isinstance(item, str) for item in argv)
            and argv[prefix].endswith("/" + binary["path"])
            and argv[prefix + 1:] == ["--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"],
            "ownership-probe-command-crossed")
    if prefix:
        root = argv[prefix].removesuffix(binary["path"])
        require(argv[:2] == [suite["tools"]["heaptrack"]["path"], "--output"]
                and argv[2] == root + row["log"]["path"].removesuffix("probe.log") + "heaptrack", "ownership-profiler-command-crossed")
