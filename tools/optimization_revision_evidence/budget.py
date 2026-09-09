"""Useful short-budget work with all offered outcomes and explicit resource scope."""
from decimal import Decimal

from tools.optimization_evidence.common import distribution, require, uint
from tools.optimization_revision_runner import budget as model


def failed_ownership(run, artifacts, builds, owners):
    from tools.optimization_evidence import resources
    if run["configuration"] is not None:
        require(run["data_removed"] is True, "budget-failed-data-not-removed")
        configuration(artifacts.json(run["configuration"]))
        prefix = run["configuration"]["path"].rsplit("/", 1)[0]
        seed_path = prefix + "/seed-cleanup.json"
        if seed_path in artifacts.rows:
            seed = artifacts.json(artifacts.rows[seed_path])["server"]
            owner = resources.process(seed, "lsf-seed", builds[run["variant"]]["executables"]["server"]["sha256"])
            require(owner not in owners and seed["reaped"] is True and seed["output_closed"] is True,
                    "budget-failed-seed-not-reaped")
            owners.add(owner)
    receipt = artifacts.json(run["server_process"]) if run["server_process"] is not None else None
    cleanup = artifacts.json(run["cleanup"]) if run["cleanup"] is not None else None
    if receipt is not None:
        owner = resources.process(receipt, "lsf-server", builds[run["variant"]]["executables"]["server"]["sha256"])
        require(owner not in owners and receipt["reaped"] is True and receipt["output_closed"] is True,
                "budget-failed-server-not-reaped")
        owners.add(owner)
        require(cleanup is not None and cleanup["server"] == receipt, "budget-crossed-failed-cleanup")
    if cleanup is not None:
        for client in cleanup["clients"]:
            owner = resources.process(client, "load-client", builds["harness"]["executables"]["client"]["sha256"])
            require(owner not in owners and client["reaped"] is True and client["output_closed"] is True,
                    "budget-failed-client-not-reaped")
            owners.add(owner)


def failed_batches(run, artifacts, builds, components, activation_ids, templates):
    """Replay complete client documents even when a later arm action failed."""
    from tools.optimization_evidence import client, resources
    if run["server_process"] is None:
        require(not run["batches"], "budget-client-without-server-receipt")
        return [], 0
    server = artifacts.json(run["server_process"])
    server_owner = (server["process_id"], server["start_time_ticks"])
    cleanup = artifacts.json(run["cleanup"])
    replayed, count = [], 0
    for batch, template in zip(run["batches"], templates):
        owner = artifacts.json(batch["client_process"])
        require(owner in cleanup["clients"], "budget-failed-batch-client-not-retained")
        client_owner = resources.process(owner, "load-client", builds["harness"]["executables"]["client"]["sha256"])
        value = client.replay(artifacts, batch, template["client_plan"], "lsf", server_owner, client_owner,
                              components, activation_ids)
        require(value["run_id"] == model.run_id(run["repetition"], run["variant"], batch["id"]),
                "crossed-failed-budget-run-id")
        value.update(id=batch["id"], cache_qualification="unavailable-failed-arm")
        value["resources"] = resources.resources(artifacts.json(batch["resources"]), server_owner, client_owner)
        count += uint(value["warmup"]["counts"]["attempts"]) + uint(value["measured"]["counts"]["attempts"])
        replayed.append(value)
    return replayed, count


def configuration(value):
    import copy
    from tools.optimization_evidence.suite import configuration as legacy
    require(value.get("workers") == {"runtime": 2, "control": 4}
            and value.get("cache") == {"entries": 4, "preparations": 4, "compilerWorkers": 2},
            "changed-budget-node-configuration")
    compatible = copy.deepcopy(value)
    compatible["workers"]["control"] = 2
    compatible["cache"] = {"entries": 4, "preparations": 1}
    legacy(compatible, "lsf")


def cache_warmth(value, identifier):
    before, after, change = (value[key] for key in ("before", "after", "delta"))
    require(uint(before["maximumConcurrentPreparations"]) == uint(after["maximumConcurrentPreparations"]) == 4,
            "budget-cache-preparation-bound")
    if identifier == "prewarm-echo":
        require(uint(before["entries"]) == 0 and uint(after["entries"]) == 1
                and uint(change["misses"]) == 1, "budget-prewarm-not-observed")
    else:
        require(uint(before["entries"]) == uint(after["entries"]) == 1
                and uint(change["misses"]) == 0, "budget-echo-was-not-resident")
    require(uint(change["evictions"]) == uint(change["invalidations"]) == 0,
            "budget-cache-residency-changed")


def aggregate(value):
    value["schema"] = "latent.optimization.budget-aggregate.v1"
    value["scope"] = "lsf-revisions-shared-external-client-short-budget-useful-work"
    value["comparisons"] = comparisons(value["runs"])
    value["timer_observation"] = {"status": "unavailable", "reason": "external-daemon-not-instrumented",
                                   "evidence": "separate-budget-lifecycle-experiment"}
    value["target"] = target(value["runs"], value["profile"], value["population_complete"])
    value["limitations"] = [
        "The prewarm case and each budget warmup remain retained and are excluded from the four measured populations.",
        "Both variants execute LSF with the identical client, payload, grants and one outstanding request.",
        "Useful success means a semantically successful response observed within the original offered deadline; every offered attempt remains in its denominator.",
        "Conditional successful-response latency excludes failures; all-offered, all-dispatched and outcome distributions remain alongside it.",
        "Throughput uses first scheduled offer to last completion, not reciprocal latencies or build time.",
        "External client receipt time does not reveal the manager terminal-publication time; internal deadline/cancel correctness requires the separate lifecycle experiment.",
        "External timer counts are unavailable; no OS or Tonic timer total is inferred from requests.",
        "Server/client CPU ticks and RSS are separately observed over the batch including warmup and observer overhead; neither is per-invocation CPU or instantaneous peak memory.",
        "Cgroup counters describe the shared runner, not exclusive service resources.",
        "Smoke remains incomplete evidence; seven full pairs are descriptive observations, not a significance test or production SLO."]
    return value


def comparisons(runs):
    indexed = {(row["repetition"], row["variant"]): row for row in runs if row["status"] == "passed"}
    result = []
    for ceiling in (1, 2, 5, 10):
        identifier, pairs, differences = f"budget-{ceiling}ms", [], []
        for repetition in range(1, 8):
            if any((repetition, variant) not in indexed for variant in ("control", "candidate")):
                continue
            selected = {variant: next(batch for batch in indexed[repetition, variant]["batches"]
                                      if batch["id"] == identifier)["measured"] for variant in ("control", "candidate")}
            latency = [selected[variant]["successful_response_latency_nanos"] for variant in ("control", "candidate")]
            difference = None if any(item is None for item in latency) else Decimal(latency[1]["median"]) - Decimal(latency[0]["median"])
            if difference is not None:
                differences.append(difference)
            pairs.append({"repetition": repetition, **selected,
                          "comparison_population": "successful-responses-only-conditional-on-success",
                          "candidate_minus_control_successful_median_nanos": None if difference is None else str(difference)})
        result.append({"id": identifier, "pairs": pairs, "successful_response_pairs": str(len(differences)),
                       "paired_successful_median_differences_nanos": distribution(differences) if differences else None})
    return result


def target(runs, profile, complete):
    arms = {}
    for variant in ("control", "candidate"):
        observations = []
        for row in runs:
            if row["variant"] != variant or row["status"] != "passed":
                continue
            metric = next(batch for batch in row["batches"] if batch["id"] == "budget-2ms")["measured"]
            observations.append({"repetition": row["repetition"], "offers": metric["counts"]["attempts"],
                                 "on_time_successes": metric["budget_successes"]})
        offers = sum(uint(row["offers"]) for row in observations)
        useful = sum(uint(row["on_time_successes"]) for row in observations)
        qualified = complete and profile == "full" and len(observations) == 7 and offers == 2800
        arms[variant] = {"offers": str(offers), "on_time_successes": str(useful), "per_process": observations,
                         "attained": (useful * 100 >= offers * 99) if qualified else None}
    return {"budget_millis": 2, "minimum_percent": "99", "population": "all-measured-2ms-offers",
            "outcome": "successful-and-client-observed-on-time", "arms": arms}
