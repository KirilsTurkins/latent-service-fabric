"""Observed ownership plateaus are distinct from metadata growth and hot-path speed."""
from __future__ import annotations

from tools.phase2_operator_process import require
from tools.phase3_resource_profile import ACTIVE_COUNTERS, integer, quiescent, summary


def complete_populations(profile, catalog):
    populations = catalog["dormantPopulations"]
    return (len(populations) == len(profile["dormantSteps"])
            and len({integer(entry["dormantAdded"]) for entry in populations}) > 1
            and all(entry["refusal"] is None and integer(entry["dormantRequested"]) == requested
                    and integer(entry["dormantAdded"]) == requested
                    and integer(entry["deployments"]) == requested + 3
                    for entry, requested in zip(populations, profile["dormantSteps"])))


def churn_outcomes(cycles):
    counts = {kind: {"arrivals": 0, "successfulProviderWork": 0,
                     "providerDiagnostic": 0, "otherFailureOrUnfinished": 0}
              for kind in ("http", "blob")}
    for cycle in cycles:
        for row in cycle["arrivals"]:
            kind = "http" if row["ordinal"] % 2 == 0 else "blob"
            observed = counts[kind]
            observed["arrivals"] += 1
            result = row.get("result", {})
            if row.get("providerDiagnostic"):
                observed["providerDiagnostic"] += 1
            elif (row["disposition"] == "completed" and result.get("category") == "success"
                  and result.get("value") == ["2201" if kind == "http" else "4"]):
                observed["successfulProviderWork"] += 1
            else:
                observed["otherFailureOrUnfinished"] += 1
    return counts


def analyze(result):
    samples = result["samples"]
    dormant = [sample for sample in samples if sample["phase"] == "dormant"]
    recovery = [sample for sample in samples if sample["phase"] == "recovery"]
    require(dormant and recovery, "resource-analysis-empty")
    os_ranges = {}
    for phase in ("fixed", "dormant", "warm", "active", "recovery", "unrouted"):
        selected = [sample for sample in samples if sample["phase"] == phase]
        require(bool(selected), "resource-analysis-missing-phase")
        os_ranges[phase] = {key: summary([sample["os"]["metrics"][key] for sample in selected])
                            for key in ("processes", "threads", "handles", "sockets", "listeners", "rssBytes")}
    fixed_counts = {}
    for key in ("processes", "threads", "listeners"):
        counts = [sample["os"]["metrics"][key] for sample in dormant]
        fixed_counts[key] = len(set(counts)) == 1
    provider_counts = [integer(sample["capabilities"]["nodeUsage"]["counters"]["broker_providers"])
                       for sample in dormant + recovery]
    checks = {"requestedDormantPopulationsAdmitted": complete_populations(result["profile"], result["catalog"]),
              "dormantProcessesPlateau": fixed_counts["processes"],
              "dormantThreadsPlateau": fixed_counts["threads"],
              "dormantListenersPlateau": fixed_counts["listeners"],
              "providerObjectsPlateau": len(set(provider_counts)) == 1 and provider_counts[0] > 0,
              "activeOwnershipReturns": all(quiescent(sample) for sample in recovery),
              "activeProviderObserved": any(sample["capabilities"] is not None and
                  integer(sample["capabilities"]["nodeUsage"]["counters"]["broker_calls"]) > 0
                  for sample in samples if sample["phase"] == "active")}
    ownership_ranges = {key: summary([integer(sample["capabilities"]["nodeUsage"]["counters"][key])
                                    for sample in recovery]) for key in ACTIVE_COUNTERS}
    timings = {}
    for kind in ("http", "blob"):
        for heat in ("cold", "warm"):
            values = [int(call["elapsedNanos"]) for call in result["calls"]
                      if call["kind"] == kind and call["heat"] == heat and call["outcome"] in ("success", "recovery")]
            timings[kind + "-" + heat] = summary(values)
    result["checks"] = checks
    result["analysis"] = {"osRanges": os_ranges, "recoveryOwnershipRanges": ownership_ranges,
                           "churnOutcomes": churn_outcomes(result["cycles"]),
                           "latencyNanos": timings,
                           "latencyScope": "CLI-process-spawn-through-RPC-and-actual-process-reap",
                           "rssPlateauAssertion": None,
                           "rssInterpretation": "report-observed-range-not-exact-allocator-return",
                           "serviceMetadataIncludedInDormantDelta": True,
                           "universalPerformanceClaim": False}
    require(all(checks.values()), "resource-plateau-check-failed")
