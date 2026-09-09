"""Strict same-current-collector replay over the independently supervised arms."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from tools.optimization_evidence.artifacts import Artifacts as BaseArtifacts
from tools.optimization_evidence.common import (
    DOCUMENT_BYTES, canonical, distribution, fields, hash_file, read_json, require, sha256, uint, verify_artifact,
)
from tools.optimization_evidence.resources import process, clean, cgroup
from tools.optimization_revision_evidence.identity import environment, source
from tools.phase1_paired.candidate import parse
from tools.phase1_paired.aggregate import delta
from . import builds as build_check, model
from .cold import model as cold_model
from .cache import model as cache_model


class Artifacts(BaseArtifacts):
    def nested(self, parent, row):
        path = verify_artifact(parent, row, DOCUMENT_BYTES)
        name = path.relative_to(self.root.resolve()).as_posix()
        require(self.rows.get(name) == dict(row, path=name), "unregistered-backend-nested-artifact")
        return path


def artifact_set(root, builds, rows=None):
    if rows is None:
        from .collect import inventory
        rows = inventory(root)
    binaries = {build["executables"]["backend"]["path"] for build in builds["builds"].values()}
    if builds["schema"] == "latent.optimization.cache-builds.v1":
        from tools.optimization_cache_lookup.files import Artifacts as CacheArtifacts
        return CacheArtifacts(root, rows, binaries)
    require(sum(uint(row["bytes"]) for row in rows) <= 2 * 1024**3, "backend-artifact-byte-bound")
    return Artifacts(root, rows, binaries)


def validate_suite(path):
    path = Path(path)
    checksum = hash_file(path, DOCUMENT_BYTES)
    suite = read_json(path)
    require(hash_file(path, DOCUMENT_BYTES) == checksum, "backend-suite-changed-during-read")
    fields(suite, "schema profile plan builds runner_source runner_source_after status reason elapsed_nanos runs artifacts")
    cold = suite["schema"] == "latent.optimization.cold-suite.v1"
    cache = suite["schema"] == "latent.optimization.cache-behavior-suite.v1"
    selected_model = cache_model if cache else cold_model if cold else model
    require(suite["schema"] in ("latent.optimization.backend-revision-suite.v1","latent.optimization.cold-suite.v1",
                                "latent.optimization.cache-behavior-suite.v1")
            and suite["profile"] in ("smoke", "full") and suite["plan"] == selected_model.plan(suite["profile"]),
            "changed-backend-suite-plan")
    require(suite["status"] in ("passed", "failed")
            and suite["reason"] == (None if suite["status"] == "passed" else "collection-failed"), "backend-suite-status")
    wall = (3600 if cache else 4500 if cold else 9000) if suite["profile"] == "full" else (600 if cache else 300)
    require(uint(suite["elapsed_nanos"]) <= wall * 10**9,
            "backend-suite-wall-bound")
    source(suite["runner_source"])
    require(suite["runner_source"] == suite["runner_source_after"], "backend-runner-source-changed")
    build_path = verify_artifact(path.parent, suite["builds"], DOCUMENT_BYTES)
    builds = read_json(build_path)
    artifacts = artifact_set(path.parent, builds, suite["artifacts"])
    artifacts.path(suite["builds"])
    if cache:
        from tools.optimization_cache_lookup.builds import validate as validate_builds
        from tools.optimization_cache_lookup.files import inventory
        validate_builds(builds, artifacts, suite["profile"], "behavior")
        require({row["path"] for row in inventory(path.parent)} == set(artifacts.rows), "cache-unregistered-evidence-file")
    else:
        build_check.validate_experiment(builds, artifacts, suite["profile"],"cold" if cold else "warm")
    require(builds["harness"]["source"] == suite["runner_source"], "backend-harness-source-mismatch")
    expected = list(model.population(suite["profile"]))
    require(isinstance(suite["runs"], list) and len(suite["runs"]) <= len(expected), "backend-run-count")
    owners, records, prior, stable_host = set(), [], 0, None
    failed = suite["status"] == "failed"
    for ordinal, row in enumerate(suite["runs"]):
        fields(row, "repetition variant status reason command started_micros finished_micros identity plan process raw log cleanup "
                    "host_before host_after cgroup_before cgroup_after")
        require((row["repetition"], row["variant"]) == expected[ordinal], "changed-backend-pair-order")
        require(row["status"] in ("passed", "failed")
                and row["reason"] == (None if row["status"] == "passed" else "collector-failed"), "backend-run-status")
        start, finish = uint(row["started_micros"]), uint(row["finished_micros"])
        require(prior <= start <= finish and (finish - start) * 1000 <= uint(suite["elapsed_nanos"]), "overlapping-backend-arms")
        prior = finish
        selected = artifacts.json(row["plan"])
        expected_plan = selected_model.plan(suite["profile"],row["repetition"],row["variant"]) if cold or cache else model.plan(suite["profile"],row["repetition"])
        require(selected == expected_plan, "changed-backend-run-plan")
        identity = artifacts.json(row["identity"])
        require(identity == model.identity(builds, row["variant"], row["host_before"]), "crossed-backend-identity")
        if cold or cache:
            before,after = ({key:item for key,item in row[name].items() if key != "clock_ticks_per_second"}
                            for name in ("host_before","host_after"))
            before,after = environment(before),environment(after)
            ticks = row["host_before"].get("clock_ticks_per_second")
            require(type(ticks) is int and 1 <= ticks <= 1_000_000
                    and row["host_after"].get("clock_ticks_per_second") == ticks, "cold-host-tick-resolution")
            before["clock_ticks_per_second"] = after["clock_ticks_per_second"] = ticks
        else:
            before, after = environment(row["host_before"]), environment(row["host_after"])
        stable_host = before if stable_host is None else stable_host
        require(before == after == stable_host, "backend-host-controls-changed")
        for name in ("cgroup_before", "cgroup_after"):
            cgroup(row[name])
        if all(row[name]["resolution"]["status"] == "resolved" for name in ("cgroup_before", "cgroup_after")):
            require(row["cgroup_before"]["resolution"] == row["cgroup_after"]["resolution"]
                    and row["cgroup_before"]["process_membership"] == row["cgroup_after"]["process_membership"],
                    "backend-cgroup-membership-changed")
        command = row["command"]
        require(isinstance(command, list) and len(command) == 6
                and command[1:] == ["--exact", selected_model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"],
                "changed-backend-collector-command")
        binary = builds["builds"][row["variant"]]["executables"]["backend"]
        require(isinstance(command[0], str) and command[0].endswith("/" + binary["path"]), "crossed-backend-command-binary")
        if row["status"] == "failed":
            if cache and row["process"] is not None:
                receipt = artifacts.json(row["process"])
                process(receipt, "artifact-identity-helper", identity["binary"]["sha256"])
                require(receipt["reaped"] is True and receipt["output_closed"] is True, "cache-failed-child-not-reaped")
            if cache and row["cleanup"] is not None:
                require(artifacts.json(row["cleanup"]) == {"removed": True}, "cache-failed-data-not-removed")
            failed = True
            records.append({"repetition": row["repetition"], "variant": row["variant"], "status": "failed"})
            continue
        receipt = artifacts.json(row["process"])
        owner = process(receipt, "artifact-identity-helper", identity["binary"]["sha256"])
        require(owner not in owners and clean(receipt), "backend-owner-reused-or-not-clean")
        owners.add(owner)
        require(artifacts.json(row["cleanup"]) == {"removed": True}, "backend-parent-data-not-removed")
        artifacts.path(row["log"])
        raw_path = artifacts.path(row["raw"])
        raw = artifacts.json(row["raw"])
        if cache:
            from .cache.parse import parse as parse_cache
            parsed = parse_cache(raw,selected,identity,artifacts,raw_path,builds["harness"]["echo"],row["variant"])
        elif cold:
            from .cold.parse import parse as parse_cold
            parsed = parse_cold(raw,selected,identity,artifacts,raw_path,builds["harness"]["echo"],row["variant"])
        else:
            parsed = parse(raw, selected, identity, artifacts, raw_path, revision=True)
        require(tuple(parsed["process_identity"]) == (owner[0], int(owner[1])), "backend-probe-is-not-supervised-child")
        parsed["process_identity"] = {"process_id": owner[0], "start_time_ticks": owner[1]}
        records.append({"repetition": row["repetition"], "variant": row["variant"], "status": "passed", **parsed})
    complete = suite["status"] == "passed" and len(records) == len(expected) and not failed
    require(suite["status"] != "passed" or complete, "passed-backend-suite-hides-failed-or-missing-arm")
    if cache:
        from .cache.aggregate import aggregate as aggregate_cache
        return aggregate_cache(suite,checksum[0],builds,records,complete,failed)
    if cold:
        from .cold.aggregate import aggregate as aggregate_cold
        return aggregate_cold(suite,checksum[0],builds,records,complete,failed)
    return aggregate(suite, checksum[0], builds, records, complete, failed)


def aggregate(suite, checksum, builds, records, complete, failed):
    indexed = {(row["repetition"], row["variant"]): row for row in records if row["status"] == "passed"}
    pairs = []
    for repetition in range(1, 8):
        if any((repetition, arm) not in indexed for arm in ("control", "candidate")):
            continue
        left = {row["name"]: row for row in indexed[repetition, "control"]["metrics"]}
        metrics = []
        for right in indexed[repetition, "candidate"]["metrics"]:
            prior = left[right["name"]]
            require(prior["boundary"] == right["boundary"] and prior["unit"] == right["unit"], "backend-metric-boundary-mismatch")
            metrics.append({"name": right["name"], "unit": right["unit"], "boundary": right["boundary"],
                            "control": prior["statistics"], "candidate": right["statistics"],
                            "contrasts": {q: delta(Decimal(right["statistics"][q]), Decimal(prior["statistics"][q]))
                                          for q in ("median", "p95", "p99")}})
        pairs.append({"repetition": repetition, "metrics": metrics})
    across = []
    if pairs:
        for index, metric in enumerate(pairs[0]["metrics"]):
            rows = [pair["metrics"][index] for pair in pairs]
            across.append({"name": metric["name"], "unit": metric["unit"], "boundary": metric["boundary"],
                           "paired_median_differences": distribution([Decimal(row["contrasts"]["median"]["absolute"]) for row in rows]),
                           "control_process_medians": distribution([Decimal(row["control"]["median"]) for row in rows]),
                           "candidate_process_medians": distribution([Decimal(row["candidate"]["median"]) for row in rows])})
    return {"schema": "latent.optimization.backend-revision-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else ("complete" if complete and suite["profile"] == "full" else "incomplete"),
            "suite_sha256": checksum, "builds": builds, "population_complete": complete,
            "validated_calls": str(sum(int(row["samples"]) for row in records if row["status"] == "passed")),
            "attempt_count_complete": complete, "runs": records, "pairs": pairs, "across_pairs": across,
            "limitations": ["First real RPC, including preparation, belongs to the declared warmup prefix; all later measured calls are retained.",
                            "Backend stage timers begin after manager materialization/preparation; subtracting them from RPC latency does not isolate hashing.",
                            "Guest call includes canonical post-return; host-call timing is a subset and is never added to guest call.",
                            "Both arms use the same current libtest/RPC diagnostic; per-call probes affect spacing and process RSS.",
                            "This diagnostic is separate from the external-client small-call reference and supplies no throughput or RSS causal claim.",
                            "Seven pairs provide descriptive variability; smoke never completes the full population."]}
