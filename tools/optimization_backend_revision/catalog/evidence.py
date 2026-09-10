"""Closed catalog suite replay with same-root exit/reopen and profiler ownership."""
from pathlib import Path

from tools.artifact_identity_evidence.runs import allocation, probe_resources
from tools.optimization_cache_lookup.evidence import host_controls, tools as validate_tools
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import digest, fields, hash_file, read_json, require, uint, verify_artifact
from tools.optimization_evidence.resources import cgroup, clean, process
from tools.optimization_revision_evidence.identity import source
from . import aggregate, allocations, builds, data, events, fixtures, model
from .parse import parse

ROW_FIELDS = ("repetition variant shape mode sequence_ordinal case status reason command started_micros finished_micros plan identity "
              "data_owner reopen_input post_exit cleanup process raw log ready result probe_process resources cpu profile_refs "
              "host_before host_after cgroup_before cgroup_after")


def validate_command(row, binary, tools):
    argv = row["command"]
    offset = 3 if row["mode"] == "allocation" else 0
    require(isinstance(argv, list) and len(argv) == offset + 6 and all(isinstance(item, str) for item in argv)
            and argv[offset].endswith("/" + binary["path"])
            and argv[offset + 1:] == ["--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"],
            "catalog-child-command")
    if offset:
        root = argv[offset].removesuffix(binary["path"])
        require(argv[:2] == [tools["heaptrack"]["path"], "--output"]
                and argv[2] == root + row["log"]["path"].removesuffix("probe.log") + "heaptrack", "catalog-profiler-command")


def persistence(row, result, records, artifacts, selected, identity):
    marker = artifacts.json(row["data_owner"])
    data.validate_marker(marker, selected, identity["source"]["commit"])
    cleanup = artifacts.json(row["cleanup"])
    fields(cleanup, "removed data_identity sequence_ordinals close_walk filesystem_reserve")
    ordinal = row["sequence_ordinal"]
    ordinals = [ordinal] if row["mode"] == "allocation" else [ordinal - (row["mode"] == "reopen"), ordinal + (row["mode"] == "initial")]
    require(cleanup["removed"] is True and cleanup["data_identity"] == result["data_identity"]
            and cleanup["sequence_ordinals"] == ordinals,
            "catalog-parent-data-not-removed-or-crossed")
    walk = fields(cleanup["close_walk"], "scope regular_files directories_including_root logical_file_bytes allocated_file_bytes maximum_file_bytes "
                  "complete symlinks_or_special_files cross_device_entries")
    require(walk["scope"] == "one-post-exit-generated-root-walk-before-removal" and walk["complete"] is True
            and walk["symlinks_or_special_files"] is walk["cross_device_entries"] is False
            and 1 <= uint(walk["regular_files"]) <= data.MAX_TREE_FILES
            and 1 <= uint(walk["directories_including_root"]) <= data.MAX_TREE_DIRECTORIES
            and uint(walk["logical_file_bytes"]) <= data.MAX_TREE_BYTES and uint(walk["maximum_file_bytes"]) <= 1024**3,
            "catalog-close-walk-bound")
    if walk["allocated_file_bytes"] is not None:
        uint(walk["allocated_file_bytes"])
    reserve = fields(artifacts.json(cleanup["filesystem_reserve"]), "source available_bytes required_bytes scope")
    required = data.MAX_TREE_BYTES if selected["profile"] == "full" and row["mode"] != "allocation" else 0
    require(reserve["source"] == "statvfs-f_bavail-times-f_frsize"
            and reserve["scope"] == "native-filesystem-available-not-host-backing-capacity"
            and reserve["required_bytes"] == str(required) and uint(reserve["available_bytes"]) >= required,
            "catalog-filesystem-reserve-bound")
    if row["mode"] == "initial":
        require(row["reopen_input"] is None and row["post_exit"] is not None, "catalog-initial-reopen-receipt")
        receipt = artifacts.json(row["post_exit"])
        fields(receipt, "schema data_identity initial_process catalog initial_raw")
        require(receipt["schema"] == data.REOPEN_SCHEMA and receipt["data_identity"] == result["data_identity"]
                and receipt["initial_process"] == {key: row["process"][key] for key in ("process_id", "start_time_ticks")}
                and receipt["initial_raw"] == row["raw"], "catalog-post-exit-source-binding")
        persisted = fields(receipt["catalog"], "path bytes sha256")
        require(persisted["path"] == data.CATALOG_PATH and 0 < uint(persisted["bytes"]) <= 1024**3, "catalog-persisted-state-bound")
        digest(persisted["sha256"])
    elif row["mode"] == "reopen":
        require(records and records[-1]["mode"] == "initial" and records[-1]["status"] == "passed"
                and row["post_exit"] is None and row["reopen_input"] == records[-1]["post_exit"]
                and row["data_owner"] == records[-1]["data_owner"] and result["data_identity"] == records[-1]["data_identity"],
                "catalog-reopen-not-adjacent-same-root")
    else:
        require(row["post_exit"] is row["reopen_input"] is None, "catalog-profile-reopen-forbidden")


def validate_suite(path):
    path = Path(path)
    checksum = hash_file(path, model.MAX_DOCUMENT_BYTES)
    suite = read_json(path, model.MAX_DOCUMENT_BYTES)
    require(hash_file(path, model.MAX_DOCUMENT_BYTES) == checksum, "catalog-suite-changed-during-read")
    fields(suite, "schema profile plan builds runner_source runner_source_after status reason elapsed_nanos normal_elapsed_nanos "
                  "allocation_elapsed_nanos tools symbols runs artifacts")
    require(suite["schema"] == model.SCHEMA and suite["plan"] == model.suite_plan(suite["profile"]), "catalog-suite-plan-crossed")
    require(suite["status"] in ("passed", "failed")
            and suite["reason"] == (None if suite["status"] == "passed" else "collection-failed"), "catalog-suite-status")
    elapsed, normal, profiled = (uint(suite[key]) for key in ("elapsed_nanos", "normal_elapsed_nanos", "allocation_elapsed_nanos"))
    require(normal <= model.normal_seconds(suite["profile"]) * 10**9 and profiled <= model.ALLOCATION_SECONDS * 10**9
            and normal + profiled <= elapsed <= normal + profiled + 10**9, "catalog-independent-stage-time-bound")
    source(suite["runner_source"])
    require(suite["runner_source"]["clean"] is True and suite["runner_source"] == suite["runner_source_after"], "catalog-runner-source-crossed")
    build = read_json(verify_artifact(path.parent, suite["builds"], model.MAX_DOCUMENT_BYTES))
    binaries = {row["executables"]["backend"]["path"] for row in build["builds"].values()}
    artifacts = Artifacts(path.parent, suite["artifacts"], binaries)
    artifacts.path(suite["builds"])
    builds.validate(build, artifacts, suite["profile"])
    require(build["harness"]["source"] == suite["runner_source"], "catalog-build-runner-crossed")
    require({row["path"] for row in inventory(path.parent)} == set(artifacts.rows), "catalog-unregistered-artifact")
    fixture = fixtures.load(build["harness"]["echo"], artifacts)
    expected = model.population(suite["profile"])
    require(isinstance(suite["runs"], list) and len(suite["runs"]) <= len(expected), "catalog-owner-count")
    allocation_started = any(row.get("mode") == "allocation" for row in suite["runs"])
    validate_tools(suite["tools"], artifacts, suite["status"] == "passed" or allocation_started)
    require(isinstance(suite["symbols"], dict) and set(suite["symbols"]) <= {"control", "candidate"}
            and (not allocation_started or set(suite["symbols"]) == {"control", "candidate"}), "catalog-symbol-proof-set")
    for variant, proof in suite["symbols"].items():
        for case in model.CASES:
            allocations.proof(proof, build["builds"][variant]["executables"]["backend"], suite["tools"]["nm"], artifacts, case)
    records, owners, data_owners = [], set(), set()
    previous, stable_host, stable_cgroup, stable_engine = 0, None, None, None
    failed = suite["status"] == "failed"
    for index, row in enumerate(suite["runs"]):
        fields(row, ROW_FIELDS)
        selection = {key: row[key] for key in model.SELECTORS}
        require(selection == expected[index], "catalog-child-order")
        selected = model.plan(suite["profile"], **selection)
        identity = model.identity(build, row["variant"], row["host_before"])
        require(artifacts.json(row["plan"]) == selected and artifacts.json(row["identity"]) == identity,
                "catalog-plan-identity-crossed")
        start, finish = uint(row["started_micros"]), uint(row["finished_micros"])
        limit = model.PROFILE_SECONDS + 4 * model.REPORT_SECONDS + 10 if row["mode"] == "allocation" else model.run_seconds(suite["profile"], row["mode"]) + 10
        require(previous <= start <= finish and (finish - start) * 1000 <= elapsed and finish - start <= limit * 10**6,
                "catalog-owner-clock-or-overlap")
        previous = finish
        before, after = host_controls(row["host_before"]), host_controls(row["host_after"])
        stable_host = before if stable_host is None else stable_host
        require(before == after == stable_host, "catalog-host-controls-crossed")
        for name in ("cgroup_before", "cgroup_after"):
            cgroup(row[name])
            controls = {key: row[name][key] for key in ("scope", "process_membership", "resolution", "cpu.max", "memory.max")}
            stable_cgroup = controls if stable_cgroup is None else stable_cgroup
            require(controls == stable_cgroup, "catalog-cgroup-controls-crossed")
        require(row["status"] in ("passed", "failed")
                and row["reason"] == (None if row["status"] == "passed" else "collector-failed"), "catalog-child-status")
        binary = build["builds"][row["variant"]]["executables"]["backend"]
        result = {**selection, "status": row["status"], "source": identity["source"], "binary": identity["binary"],
                  "data_owner": row["data_owner"], "post_exit": row["post_exit"]}
        if row["status"] == "failed":
            failed = True
            if row["process"] is not None:
                key = process(row["process"], "identity-allocation" if row["mode"] == "allocation" else "artifact-identity-helper",
                              suite["tools"]["heaptrack"]["sha256"] if row["mode"] == "allocation" else binary["sha256"])
                require(key not in owners and row["process"]["reaped"] is True and row["process"]["output_closed"] is True,
                        "catalog-failed-owner-not-reaped")
                owners.add(key)
            if row["raw"] is not None:
                artifacts.path(row["raw"])
            require(row["cleanup"] is not None and artifacts.json(row["cleanup"])["removed"] is True,
                    "catalog-failed-data-owner-remains")
            result.update(validated_commands="0", validated_resolves="0", validated_invocations="0", attempt_count_complete=False,
                          raw_retained=row["raw"] is not None, native_cleanup_qualification="unavailable-failed-child")
        else:
            validate_command(row, binary, suite["tools"])
            if row["mode"] == "allocation":
                key, _ = probe_resources(row, binary, suite["tools"])
                require(row["cpu"] is None, "catalog-profiled-cpu-as-normal")
            else:
                key = process(row["process"], "artifact-identity-helper", binary["sha256"])
                require(clean(row["process"]) and all(row[name] is None for name in ("probe_process", "resources", "cpu", "profile_refs")),
                        "catalog-normal-owner-crossed")
                sidecar = row["log"]["path"] + ".process.json"
                require(sidecar in artifacts.rows and artifacts.json(artifacts.rows[sidecar]) == row["process"], "catalog-process-sidecar")
            require(key not in owners, "catalog-reused-process-identity")
            owners.add(key)
            owner = (key[0], uint(key[1]))
            raw = artifacts.json(row["raw"], model.MAX_DOCUMENT_BYTES)
            checked = parse(raw, selected, identity, fixture, row, artifacts)
            require(tuple(checked["process_identity"]) == owner and uint(checked["elapsed_nanos"]) <= (finish - start) * 1000 + 1000,
                    "catalog-raw-outside-owner")
            events.parse(row, artifacts, owner, raw)
            persistence(row, checked, records, artifacts, selected, identity)
            if row["mode"] != "reopen":
                nonce = checked["data_identity"]["marker"]["nonce"]
                require(nonce not in data_owners, "catalog-reused-data-root-nonce")
                data_owners.add(nonce)
            stable_engine = checked["effective_engine"] if stable_engine is None else stable_engine
            require(checked["effective_engine"] == stable_engine, "catalog-engine-policy-crossed")
            result.update(aggregate.summarize(checked), allocation_attribution=None, whole_process_allocations=None)
            if row["mode"] == "allocation":
                whole = allocation(row, suite, artifacts, maximum_folded_bytes=model.MAX_FOLDED_BYTES)
                result["whole_process_allocations"] = whole
                result["allocation_attribution"] = allocations.attribute(row, binary, suite["symbols"][row["variant"]],
                    suite["tools"]["nm"], artifacts, whole, model.counts(suite["profile"], "allocation")["measured_resolves"])
        records.append(result)
    complete = len(records) == len(expected) and not failed
    require(suite["status"] != "passed" or complete, "catalog-passed-suite-incomplete")
    return aggregate.aggregate(suite, checksum[0], build, records, complete, failed)
