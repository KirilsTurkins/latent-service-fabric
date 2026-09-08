"""Replay every offered call with existing validators, then pair LSF revisions."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from tools.optimization_evidence import client, resources
from tools.optimization_evidence.artifacts import Artifacts
from tools.optimization_evidence.common import (
    DOCUMENT_BYTES, canonical, distribution, fields, hash_file, read_json, require, sha256, uint,
)
from tools.optimization_evidence.suite import BATCH_FIELDS, configuration, lifecycle, shutdown
from tools.optimization_runner.plans import SERVICES
from tools.optimization_revision_runner.build import validate_refs
from tools.optimization_revision_runner.model import plan, population, run_id
from . import cache, identity

RUN_FIELDS = ("repetition variant arm scenario status reason started_micros finished_micros batches "
              "server_process configuration cleanup lifecycle data_removed environment_before environment_after")


def validate_suite(path: Path) -> dict:
    path = Path(path)
    checksum = hash_file(path, DOCUMENT_BYTES)
    suite = read_json(path)
    require(hash_file(path, DOCUMENT_BYTES) == checksum, "revision-suite-changed-during-read")
    fields(suite, "schema profile plan requested_refs status reason elapsed_nanos measurement_elapsed_nanos identity cleanup runs artifacts")
    require(suite["schema"] == "latent.optimization.revision-suite.v1", "invalid-revision-suite-schema")
    require(suite["plan"] == plan(suite["profile"]), "changed-revision-population")
    validate_refs(suite["requested_refs"], suite["profile"])
    require(suite["status"] in ("passed", "failed")
            and suite["reason"] == (None if suite["status"] == "passed" else "collection-failed"), "revision-status")
    measured, elapsed = uint(suite["measurement_elapsed_nanos"]), uint(suite["elapsed_nanos"])
    maximum = (int(suite["plan"]["maximum_build_seconds"]) + int(suite["plan"]["maximum_run_seconds"])) * 10**9
    require(measured <= elapsed <= maximum and measured <= int(suite["plan"]["maximum_run_seconds"]) * 10**9,
            "revision-suite-exceeded-time-bound")
    builds = suite["identity"].get("builds", {})
    executable_paths = {row["path"] for build in builds.values() for row in build.get("executables", {}).values()}
    artifacts = Artifacts(path.parent, suite["artifacts"], executable_paths)
    require(sum(uint(row["bytes"]) for row in suite["artifacts"]) <= int(suite["plan"]["maximum_artifact_bytes"]),
            "revision-artifact-budget-exceeded")
    fields(suite["cleanup"], "owned_worktree_removed")
    require(type(suite["cleanup"]["owned_worktree_removed"]) is bool, "revision-cleanup-disposition")
    require(isinstance(suite["runs"], list), "invalid-revision-runs")
    expected = list(population(suite["profile"]))
    require(len(suite["runs"]) <= len(expected), "extra-revision-pairs")
    if suite["status"] == "failed" and set(builds) != {"control", "candidate", "harness"}:
        require(not suite["runs"], "measurements-with-incomplete-build-provenance")
        return aggregate(suite, checksum[0], [], set(), 0, True, False)
    identity.validate(suite["identity"], suite["requested_refs"], artifacts)
    require(suite["cleanup"]["owned_worktree_removed"] is True, "owned-build-worktree-not-removed")
    components = dict(zip(SERVICES, (row["sha256"] for row in suite["identity"]["components"]), strict=True))
    owners, activations, result = set(), set(), []
    failed, attempts, prior_end = suite["status"] == "failed", 0, 0
    for index, run in enumerate(suite["runs"]):
        fields(run, RUN_FIELDS)
        require((run["repetition"], run["variant"]) == expected[index] and run["arm"] == "lsf"
                and run["scenario"] == "cold-restart", "changed-revision-pair-order")
        require(run["status"] in ("passed", "failed")
                and run["reason"] == (None if run["status"] == "passed" else "collector-failed"), "revision-run-status")
        start, finish = uint(run["started_micros"]), uint(run["finished_micros"])
        require(prior_end <= start <= finish and (finish - start) * 1000 <= measured, "overlapping-revision-processes")
        prior_end = finish
        templates = suite["plan"]["cases"]
        require(isinstance(run["batches"], list) and len(run["batches"]) <= len(templates), "revision-batch-count")
        for batch, template in zip(run["batches"], templates):
            fields(batch, BATCH_FIELDS + " cache_observation")
            require(batch["id"] == template["id"], "changed-revision-case-order")
        if run["status"] == "failed":
            failed = True
            result.append({"repetition": run["repetition"], "variant": run["variant"], "status": "failed",
                           "validated_attempts": "0", "attempt_count_complete": False})
            continue
        require(len(run["batches"]) == len(templates) and run["data_removed"] is True, "incomplete-revision-run")
        before, after = (identity.environment(run[key]) for key in ("environment_before", "environment_after"))
        require(before == after == identity.environment(suite["identity"]["environment"]), "changed-revision-host-controls")
        executable = builds[run["variant"]]["executables"]["server"]
        receipt = artifacts.json(run["server_process"])
        server = unique_owner(receipt, "lsf-server", executable["sha256"], owners)
        prefix = run["server_process"]["path"].rsplit("/", 1)[0]
        require(prefix + "/seed-cleanup.json" in artifacts.rows, "missing-revision-seed-cleanup")
        seed = artifacts.json(artifacts.rows[prefix + "/seed-cleanup.json"])
        fields(seed, "server server_shutdown")
        unique_owner(seed["server"], "lsf-seed", executable["sha256"], owners)
        shutdown(seed["server_shutdown"], "lsf")
        configuration(artifacts.json(run["configuration"]), "lsf")
        lifecycle(run["lifecycle"], "lsf", finish - start)
        replayed, clients, cache_end = [], [], start
        for batch, template in zip(run["batches"], templates, strict=True):
            owner = artifacts.json(batch["client_process"])
            client_owner = unique_owner(owner, "load-client", builds["harness"]["executables"]["client"]["sha256"], owners)
            clients.append(owner)
            value = client.replay(artifacts, batch, template["client_plan"], "lsf", server, client_owner, components, activations)
            require(value["run_id"] == run_id(run["repetition"], run["variant"], batch["id"]), "crossed-revision-run-id")
            value["resources"] = resources.resources(artifacts.json(batch["resources"]), server, client_owner)
            value["cache"], cache_end = cache.validate(artifacts.json(batch["cache_observation"]), artifacts, server,
                                                     artifacts.json(batch["plan"]), batch["id"], start, finish, cache_end)
            value["id"] = batch["id"]
            attempts += int(value["warmup"]["counts"]["attempts"]) + int(value["measured"]["counts"]["attempts"])
            failed = failed or value["correctness_failures"] != "0"
            if not batch["id"].startswith("budget-"):
                failed = failed or value["measured"]["counts"]["successful"] != value["measured"]["counts"]["attempts"]
            replayed.append(value)
        cleanup = artifacts.json(run["cleanup"])
        fields(cleanup, "server clients server_shutdown")
        require(cleanup["server"] == receipt and cleanup["clients"] == clients, "crossed-revision-cleanup-owners")
        shutdown(cleanup["server_shutdown"], "lsf")
        result.append({"repetition": run["repetition"], "variant": run["variant"], "status": "passed",
                       "lifecycle": run["lifecycle"], "batches": replayed})
    complete = (suite["status"] == "passed" and len(result) == len(expected)
                and all(row["status"] == "passed" for row in result))
    require(suite["status"] != "passed" or complete, "passed-suite-hides-missing-pair")
    return aggregate(suite, checksum[0], result, owners, attempts, failed, complete)


def unique_owner(value, role, checksum, owners):
    owner = resources.process(value, role, checksum)
    require(owner not in owners and resources.clean(value), "reused-or-unreclaimed-revision-process")
    owners.add(owner)
    return owner


def aggregate(suite, checksum, runs, owners, attempts, failed, complete):
    return {"schema": "latent.optimization.revision-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else ("complete" if complete and suite["profile"] == "full" else "incomplete"),
            "scope": "lsf-before-after-warm-acquisition-with-shared-external-client",
            "suite_sha256": checksum, "plan_sha256": sha256(canonical(suite["plan"])),
            "population_complete": complete, "attempt_count_complete": complete,
            "validated_attempts": str(attempts), "validated_processes": str(len(owners)),
            "identity": suite["identity"], "runs": runs, "comparisons": comparisons(runs, suite["plan"]["cases"]),
            "limitations": [
                "Smoke is incomplete evidence, even when its fixed population passes.",
                "Both variants execute LSF; the shared client and CLI are built from the declared harness revision.",
                "Warmup remains in raw counts and is excluded from measured latency populations.",
                "Successful-response latency contrasts are conditional on success; inspect all offered outcomes and budget misses.",
                "Throughput uses first scheduled offer through last completed attempt, excluding harness work outside that interval; it is never a sum of reciprocal call latencies.",
                "Cache snapshots include warmup and node-get observation overhead outside request timers; they are not per-call I/O counters.",
                "Cold first response includes client launch/connect and the before-batch inventory observation, not isolated preparation.",
                "Validated process counts cover seed servers, measured servers and load clients; provisioning/node-get CLI helpers are separate overhead.",
                "RSS is sampled with a live completion witness, not an instantaneous peak; client and server observations remain separate.",
                "Cgroup readings describe the shared runner cgroup, not isolated server resource use.",
                "Seven pairs are descriptive observations, not statistical significance or an SLO.",
                "This nine-case profile does not claim the original sixteen-case native comparison or Phase 1 heavy scale/soak gate."]}


def comparisons(runs, cases):
    indexed = {(row["repetition"], row["variant"]): row for row in runs if row["status"] == "passed"}
    result = []
    for index, case in enumerate(cases):
        pairs, differences = [], []
        for repetition in range(1, 8):
            if any((repetition, arm) not in indexed for arm in ("control", "candidate")):
                continue
            selected = {arm: indexed[repetition, arm]["batches"][index]["measured"] for arm in ("control", "candidate")}
            left, right = (selected[arm]["successful_response_latency_nanos"] for arm in ("control", "candidate"))
            difference = None if left is None or right is None else Decimal(right["median"]) - Decimal(left["median"])
            if difference is not None:
                differences.append(difference)
            pairs.append({"repetition": repetition, **selected,
                          "comparison_population": "successful-responses-only-conditional-on-success",
                          "candidate_minus_control_successful_median_nanos": None if difference is None else str(difference)})
        result.append({"id": case["id"], "pairs": pairs, "successful_response_pairs": str(len(differences)),
                       "paired_successful_median_differences_nanos": distribution(differences) if differences else None})
    return result
