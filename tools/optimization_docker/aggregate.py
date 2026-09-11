"""Descriptive paired tables from validated Docker evidence; no observations run here."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import csv
import io
import json
from pathlib import Path

from tools.optimization_evidence.common import (
    canonical, decimal_string, distribution, integer, ratio, require, sha256, uint,
)
from . import model

SCHEMA = model.PREFIX + "aggregate.v1"
STAGES = ("ready", "served", "final")
PROCESS_METRICS = {"rss_bytes": "bytes", "threads": "count", "fd_count": "count", "listener_count": "count"}
CGROUP_METRICS = {
    "memory.current": ("memory_current_bytes", "bytes"),
    "memory.peak": ("sum_leaf_lifetime_memory_peak_bytes", "bytes"),
    "memory.swap.current": ("memory_swap_current_bytes", "bytes"),
    "pids.current": ("pids_current", "count"),
}
CPU_METRICS = {
    "usage_usec": "us", "user_usec": "us", "system_usec": "us", "nr_periods": "count",
    "nr_throttled": "count", "throttled_usec": "us",
}


def _difference(before, after):
    return None if before is None or after is None else decimal_string(Decimal(after) - Decimal(before))


def _span(before, after):
    start, end = uint(before), uint(after)
    require(start <= end, "docker-aggregate-clock-order")
    return str(end - start)


def _sum(values):
    """A partial cohort cannot silently become a smaller complete cohort."""
    require(bool(values), "docker-aggregate-empty-cohort")
    return None if any(value is None for value in values) else str(sum(uint(value) for value in values))


def _get(value, *path):
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _stats_number(value, *path):
    value = _get(value, *path)
    return None if value is None else str(integer(value))


def comparisons(rows, dimensions, units):
    """Pair first, then summarize differences; never subtract arm medians."""
    groups = defaultdict(dict)
    for row in rows:
        key = tuple(row[name] for name in dimensions)
        pair = integer(row["pair"], 0, 6)
        arm = row["arm"]
        require(arm in ("lsf", "native") and (pair, arm) not in groups[key], "docker-aggregate-duplicate-arm")
        groups[key][pair, arm] = row
    result = []
    for key, entries in sorted(groups.items()):
        pairs = sorted({pair for pair, _ in entries})
        require(all((pair, arm) in entries for pair in pairs for arm in ("lsf", "native")),
                "docker-aggregate-unmatched-pair")
        for metric, unit in units.items():
            observations = []
            for pair in pairs:
                left, right = entries[pair, "native"], entries[pair, "lsf"]
                require(metric in left["metrics"] and metric in right["metrics"], "docker-aggregate-missing-metric")
                baseline, candidate = left["metrics"][metric], right["metrics"][metric]
                delta = _difference(baseline, candidate)
                observations.append({"pair": pair, "first_arm": "native" if left["group"] < right["group"] else "lsf",
                                     "native_group": left["group"], "lsf_group": right["group"],
                                     "native": baseline, "lsf": candidate, "lsf_minus_native": delta,
                                     "percent_of_native": None if delta is None else ratio(Decimal(delta) * 100, Decimal(baseline))})
            result.append({**dict(zip(dimensions, key)), "metric": metric, "unit": unit,
                           "pairs": observations, **_paired_summary(observations),
                           "order_strata": {arm: _paired_summary([row for row in observations if row["first_arm"] == arm])
                                            for arm in ("lsf", "native")}})
    return result


def _paired_summary(rows):
    available = [row for row in rows if row["lsf_minus_native"] is not None]
    deltas = [Decimal(row["lsf_minus_native"]) for row in available]
    return {"pair_count": len(rows), "available_pairs": len(available), "unavailable_pairs": len(rows) - len(available),
            "native": distribution([Decimal(row["native"]) for row in available]) if available else None,
            "lsf": distribution([Decimal(row["lsf"]) for row in available]) if available else None,
            "paired_difference": distribution(deltas) if deltas else None,
            "lower": sum(value < 0 for value in deltas), "equal": sum(value == 0 for value in deltas),
            "higher": sum(value > 0 for value in deltas)}


def phase_rows(clients):
    rows, units = [], {}
    for client in clients:
        evidence = client["evidence"]
        for observed in evidence["phases"]:
            phase, summary = observed["phase"], observed["metrics"]
            counts = summary["counts"]
            metrics = {key: summary[key] for key in ("successes_per_second", "attempts_per_second",
                       "successful_response_fraction", "budget_successes", "budget_misses")}
            units.update({key: "responses/s" if key == "successes_per_second" else "offers/s"
                          if key == "attempts_per_second" else "fraction" if key == "successful_response_fraction"
                          else "count" for key in metrics})
            metrics["phase_span_successes_per_second"] = ratio(uint(counts["successful"]) * 10**9,
                                                               uint(observed["phase_elapsed_nanos"]))
            metrics["phase_span_attempts_per_second"] = ratio(uint(counts["attempts"]) * 10**9,
                                                              uint(observed["phase_elapsed_nanos"]))
            units.update(phase_span_successes_per_second="responses/s", phase_span_attempts_per_second="offers/s")
            for name in ("all_dispatched_latency_nanos", "successful_response_latency_nanos",
                         "all_offered_elapsed_nanos", "dispatch_lag_nanos", "overshoot_nanos"):
                for quantile in ("minimum", "median", "p95", "p99", "maximum"):
                    metric = name + "." + quantile
                    metrics[metric] = None if summary[name] is None else summary[name][quantile]
                    units[metric] = "ns"
            rows.append({"pair": evidence["pair"], **{key: observed[key] for key in ("group", "arm", "density")},
                         "phase": phase["ordinal"], "phase_name": phase["name"], "phase_kind": phase["kind"],
                         "function": phase["function"], "concurrency": phase["concurrency"],
                         "phase_elapsed_nanos": observed["phase_elapsed_nanos"], "counts": counts,
                         "observed_metrics": summary, "metrics": metrics})
    return rows, units


def _resource_point(owners, index):
    ids = [owner["resources"]["container_id"] for owner in owners]
    require(len(ids) == len(set(ids)), "docker-aggregate-duplicate-cgroup-owner")
    samples = [owner["resources"]["snapshots"][index] for owner in owners]
    require(all(row["snapshot_index"] == index + 1 for row in samples), "docker-aggregate-snapshot-order")
    metrics, units, unavailable = {}, {}, {}

    def add(name, values, unit, reasons):
        metrics[name], units[name] = _sum(values), unit
        unavailable[name] = [{"container_id": container_id, "reason": reason or "field-unavailable"}
                             for container_id, value, reason in zip(ids, values, reasons) if value is None]

    for process in ("child", "wrapper"):
        for field, unit in PROCESS_METRICS.items():
            reason = {"rss_bytes": "rss_unavailable_reason", "threads": "threads_unavailable_reason",
                      "fd_count": "fd_unavailable_reason", "listener_count": "listeners_unavailable_reason"}[field]
            add(process + "." + field, [row[process][field] for row in samples], unit,
                [row[process][reason] for row in samples])
    for field, (name, unit) in CGROUP_METRICS.items():
        add("cgroup." + name, [row["cgroup"][field] for row in samples], unit,
            [row["cgroup"]["unavailable_reasons"][field] for row in samples])
    for field, unit in CPU_METRICS.items():
        add("cgroup.cpu." + field, [_get(row["cgroup"], "cpu_stat", field) for row in samples], unit,
            [row["cgroup"]["unavailable_reasons"]["cpu.stat"] for row in samples])
    return {"metrics": metrics, "unavailable_components": unavailable,
            "leaf_cgroup_container_ids": ids, "processes_per_kind": len(ids)}, units


def resource_rows(groups):
    points, windows, units = [], [], None
    for group in groups:
        owners = group["owners"]
        require(len(owners) == (1 if group["arm"] == "lsf" else group["density"]), "docker-aggregate-cohort-size")
        require(len(group["windows"]) == 3, "docker-aggregate-window-count")
        identity = {key: group[key] for key in ("pair", "group", "arm", "density")}
        observed = []
        for index in range(6):
            point, units = _resource_point(owners, index)
            row = {**identity, "stage": STAGES[index // 2], "point": "before" if index % 2 == 0 else "after", **point}
            points.append(row)
            observed.append(row)
        for index, window in enumerate(group["windows"]):
            require(window["stage"] == STAGES[index], "docker-aggregate-window-order")
            before, after = observed[index * 2:index * 2 + 2]
            intervals = []
            for owner in owners:
                snapshots = owner["resources"]["snapshots"]
                intervals.append({"container_id": owner["resources"]["container_id"],
                                  "before_capture": {key: snapshots[index * 2]["cgroup"][key]
                                                     for key in ("started_nanos", "finished_nanos")},
                                  "after_capture": {key: snapshots[index * 2 + 1]["cgroup"][key]
                                                    for key in ("started_nanos", "finished_nanos")}})
            windows.append({**identity, "stage": window["stage"],
                            "parent_sleep_nanos": _span(window["sleep_begin_nanos"], window["sleep_end_nanos"]),
                            "parent_window_nanos": _span(window["started_nanos"], window["finished_nanos"]),
                            "capture_intervals": intervals,
                            "metrics": {name: _difference(before["metrics"][name], after["metrics"][name]) for name in units},
                            "before": before["metrics"], "after": after["metrics"]})
    return points, windows, units or {}


def lifecycle_rows(groups, clients):
    client_by_pair = {row["evidence"]["pair"]: row for row in clients}
    owners, cohorts = [], []
    for group in groups:
        identity = {key: group[key] for key in ("pair", "group", "arm", "density")}
        client = client_by_pair[group["pair"]]
        first = next(row for row in client["evidence"]["first_responses"] if row["group"] == group["group"])
        commands = client["parent"]["commands"]
        command_index = next(index for index, row in enumerate(commands)
                             if (value := json.loads(row["line"]))["command"] == "phase"
                             and value["group"] == group["group"] and value["phase"] == 0)
        ack = next(row for row in client["parent"]["acknowledgements"]
                   if row["ack"]["event"] == "first-response" and row["ack"]["command_ordinal"] == command_index)
        first_observed = ack["received_nanos"]
        starts, ready_times, first_owner = [], [], None
        for owner in group["owners"]:
            parent = owner["parent"]
            ready_observed = next(row["observed_nanos"] for row in parent["event_observations"] if row["sequence"] == 1)
            start = parent["start"]["started_nanos"]
            starts.append(uint(start))
            ready_times.append(uint(ready_observed))
            if parent["owner_ref"] == first["owner_ref"]:
                first_owner = parent
            owners.append({**identity, "container_id": parent["container_id"], "owner_ref": parent["owner_ref"],
                           "app_process_id": parent["app_process_id"], "start_api_begin_nanos": start,
                           "start_api_end_nanos": parent["start"]["finished_nanos"], "ready_observed_nanos": ready_observed,
                           "start_api_elapsed_nanos": _span(start, parent["start"]["finished_nanos"]),
                           "start_to_ready_observed_upper_nanos": _span(start, ready_observed)})
        require(first_owner is not None, "docker-aggregate-first-response-owner")
        cohorts.append({**identity, "first_response": first, "first_response_ack_received_nanos": first_observed,
                        "first_target_container_id": first_owner["container_id"],
                        "metrics": {
                            "cohort_first_start_to_last_ready_observed_upper_nanos": _span(str(min(starts)), str(max(ready_times))),
                            "cohort_first_start_to_first_response_observed_upper_nanos": _span(str(min(starts)), first_observed),
                            "first_target_start_to_first_response_observed_upper_nanos": _span(first_owner["start"]["started_nanos"], first_observed),
                            "last_ready_observation_to_first_response_ack_nanos": _span(str(max(ready_times)), first_observed),
                            "first_phase_command_to_first_response_ack_nanos": _span(commands[command_index]["sent_nanos"], first_observed)}})
    return owners, cohorts


def client_rows(clients):
    points, intervals = [], []
    for client in clients:
        parent, evidence = client["parent"], client["evidence"]
        observations = parent["observations"]
        current = {}
        for item in observations:
            stats = item["stats"]
            metrics = {"cpu_total_nanos": _stats_number(stats, "cpu_stats", "cpu_usage", "total_usage"),
                       "cpu_user_nanos": _stats_number(stats, "cpu_stats", "cpu_usage", "usage_in_usermode"),
                       "cpu_system_nanos": _stats_number(stats, "cpu_stats", "cpu_usage", "usage_in_kernelmode"),
                       "memory_usage_bytes": _stats_number(stats, "memory_stats", "usage"),
                       "reported_memory_max_usage_bytes": _stats_number(stats, "memory_stats", "max_usage"),
                       "pids_current": _stats_number(stats, "pids_stats", "current")}
            row = {"pair": evidence["pair"], "container_id": parent["container_id"], "stage": item["stage"],
                   "observed_nanos": item["observed_nanos"], "metrics": metrics,
                   "unavailable_metrics": [key for key, value in metrics.items() if value is None]}
            points.append(row)
            current[item["stage"]] = row
        for group in model.groups(evidence["profile"], evidence["pair"]):
            for start, end in (("ready", "served"), ("served", "final"), ("ready", "final")):
                before, after = (current[f"group-{group['ordinal']}-{stage}"] for stage in (start, end))
                intervals.append({"pair": evidence["pair"], "group": group["ordinal"], "arm": group["arm"],
                                  "density": group["density"], "from_stage": start, "to_stage": end,
                                  "parent_observation_elapsed_nanos": _span(before["observed_nanos"], after["observed_nanos"]),
                                  "metrics": {key: _difference(before["metrics"][key], after["metrics"][key])
                                              for key in ("cpu_total_nanos", "cpu_user_nanos", "cpu_system_nanos")},
                                  "memory_before_bytes": before["metrics"]["memory_usage_bytes"],
                                  "memory_after_bytes": after["metrics"]["memory_usage_bytes"]})
    return points, intervals


def _background(derived):
    environment = derived["environment"]
    controller = environment["controller"]
    observations = list(environment["observations"])
    for group in derived["groups"]:
        observations.extend((group["environment_before"], group["environment_after"]))
    return {"scope": "shared-Linux-VM-and-Docker-controller-not-attributed-to-either-arm",
            "engine_version": environment["engine_version"], "engine_info": environment["engine_info"],
            "controller_platform": environment["controller_platform"],
            "controller": {"container_id": controller["Id"], "image_id": controller["Image"],
                           "name": controller["Name"], "host_pid_at_inspection": controller["State"]["Pid"],
                           "cpu_memory": None, "unavailable_reason": "controller-process-cost-not-separately-sampled"},
            "observations": [{"stage": row["stage"], "observed_nanos": row["observed_nanos"],
                              "sha256": sha256(canonical(row))} for row in observations],
            "raw_observation_location": "original-suite-environment-and-group-receipts",
            "background_subtraction": None}


def aggregate(derived):
    """Accept only the complete offline replay result, including complete smoke."""
    require(derived["status"] == "passed", "docker-aggregate-unvalidated-input")
    profile = derived["profile"]
    plan = model.plan(profile)
    require(canonical(derived["plan"]) == canonical(plan), "docker-aggregate-plan")
    clients, groups = derived["clients"], derived["groups"]
    repetitions = model.repetitions(profile)
    require(len(clients) == repetitions and len(groups) == repetitions * 6,
            "docker-aggregate-incomplete-population")
    require([row["evidence"]["pair"] for row in clients] == list(range(repetitions)), "docker-aggregate-client-order")
    expected = [(pair, group["ordinal"], group["arm"], group["density"])
                for pair in range(repetitions) for group in model.groups(profile, pair)]
    require([tuple(row[key] for key in ("pair", "group", "arm", "density")) for row in groups] == expected,
            "docker-aggregate-group-order")
    require(all(row["evidence"]["profile"] == profile and row["evidence"]["status"] == "complete" for row in clients)
            and sum(uint(row["evidence"]["offers"]) for row in clients) == uint(plan["logical_offers"]),
            "docker-aggregate-offer-population")
    expected_counts = {"offers": plan["logical_offers"], "successful": plan["logical_offers"],
                       "seed_management_rpcs": str(plan["seed_management_rpcs"]), "seed_invokes": "0",
                       "measured_application_owners": str(44 * repetitions), "client_owners": str(repetitions),
                       "all_containers_removed": str(45 * repetitions + 3)}
    require(all(derived["counts"][name] == value for name, value in expected_counts.items()),
            "docker-aggregate-count-population")
    require(uint(derived["counts"]["api_calls"]) <= 20_000, "docker-aggregate-api-bound")
    phases, phase_units = phase_rows(clients)
    require(len(phases) == repetitions * 30, "docker-aggregate-phase-population")
    points, windows, resource_units = resource_rows(groups)
    owners, cohorts = lifecycle_rows(groups, clients)
    client_points, client_intervals = client_rows(clients)
    lifecycle_units = {name: "ns" for name in cohorts[0]["metrics"]}
    client_units = {name: "ns" for name in client_intervals[0]["metrics"]}
    result = {"schema": SCHEMA, "status": "complete", "profile": profile, "plan": plan,
              "completed_paired_run": True, "full_population_completed": profile == "full",
              "acceptance_qualified": profile == "full", "logical_offers": plan["logical_offers"],
              "validated_pairs": repetitions, "source": derived["source"], "build_source": derived["build_source"],
              "suite_sha256": derived["suite_sha256"], "images": derived["images"], "counts": derived["counts"],
              "collection_elapsed_nanos": _span(derived["started_nanos"], derived["finished_nanos"]),
              "collection_scope": "seed-setup-paired-clients-parent-observation-and-cleanup",
              "phase_rows": phases,
              "phase_comparisons": comparisons(phases, ("density", "phase_name", "phase_kind", "function", "concurrency"), phase_units),
              "resource_points": points,
              "resource_comparisons": comparisons(points, ("density", "stage", "point"), resource_units),
              "idle_windows": windows,
              "idle_window_comparisons": comparisons(windows, ("density", "stage"), resource_units),
              "lifecycle_owners": owners, "lifecycle_cohorts": cohorts,
              "lifecycle_comparisons": comparisons(cohorts, ("density",), lifecycle_units),
              "client_resource_points": client_points, "client_intervals": client_intervals,
              "client_cpu_comparisons": comparisons(client_intervals, ("density", "from_stage", "to_stage"), client_units),
              "background": _background(derived),
              "units": {"phase_metrics": phase_units, "resource_metrics": resource_units,
                        "lifecycle_metrics": lifecycle_units, "client_interval_metrics": client_units},
              "limitations": [
                  "Seven full pairs and their order strata are descriptive; no confidence interval or universal deployment claim is inferred.",
                  "First-per-service, warmup and measured phases stay separate; distributions are not pooled across phases, densities or pairs.",
                  "Successful latency is conditional on success; all-dispatched latency and all-offered outcomes retain their separate denominators.",
                  "Attempt throughput spans first scheduled offer to last completion; phase-span throughput also includes phase validation and output work.",
                  "Each process RSS is counted in its own namespace; summing RSS may double-count shared physical pages and is not PSS.",
                  "Each container leaf cgroup is charged once, covering child plus wrapper; process sums are not added to cgroup totals.",
                  "A sum of leaf lifetime memory peaks is not a simultaneous cohort peak; no within-invocation memory maximum is sampled.",
                  "Idle CPU changes cover actual snapshot brackets and observer activity around the requested 250 ms sleep; they are not exact 250 ms utilization.",
                  "Container-start and first-response values are observed upper bounds on the parent clock, with images already present.",
                  "Sequential native cohort provisioning, channel connection, and intentional ready/served 250 ms barriers remain in lifecycle observations.",
                  "The paused lifecycle is not an ideal cold invocation; parent, wrapper and client clock origins are never subtracted from one another.",
                  "Client CPU intervals include client validation/output and barrier waits; application-plus-wrapper cgroup CPU remains separate.",
                  "Separate child/wrapper CPU, exact controller process cost and shared-VM background attribution are unavailable; no background subtraction is applied.",
                  "Any missing component makes its cohort metric unavailable; missing values are not zero and unavailable pairs remain listed."]}
    require(len(canonical(result)) + 1 <= model.MAX_HELPER_BYTES, "docker-aggregate-byte-bound")
    return result


def _csv_bytes(rows):
    """Keep decimal strings exact and represent unavailable CSV cells as null."""
    flattened = []
    for row in rows:
        flat = {}
        for key, value in row.items():
            if key == "metrics":
                flat.update({"metric." + name: item for name, item in value.items()})
            else:
                flat[key] = value
        flattened.append(flat)
    names = list(dict.fromkeys(key for row in flattened for key in row))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    for row in flattened:
        writer.writerow({key: "null" if value is None else json.dumps(value, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")) if isinstance(value, (dict, list, bool)) else value
                         for key, value in row.items()})
    return output.getvalue().encode("utf-8")


def write(derived, directory):
    """Write a fresh report directory; never overwrite a prior report or raw root."""
    result = aggregate(derived)
    outputs = {"aggregate.json": canonical(result) + b"\n"}
    for name in ("phase_rows", "phase_comparisons", "resource_points", "resource_comparisons", "idle_windows",
                 "idle_window_comparisons", "lifecycle_owners", "lifecycle_cohorts", "lifecycle_comparisons",
                 "client_resource_points", "client_intervals", "client_cpu_comparisons"):
        outputs[name.replace("_", "-") + ".csv"] = _csv_bytes(result[name])
    require(all(len(data) <= model.MAX_HELPER_BYTES for data in outputs.values()), "docker-aggregate-output-bound")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    references = []
    for name, data in outputs.items():
        with (directory / name).open("xb") as output:
            output.write(data)
        references.append({"path": name, "bytes": str(len(data)), "sha256": sha256(data)})
    manifest = {"schema": model.PREFIX + "aggregate-files.v1", "suite_sha256": result["suite_sha256"],
                "profile": result["profile"], "csv_null": "literal-null", "files": references}
    with (directory / "manifest.json").open("xb") as output:
        output.write(canonical(manifest) + b"\n")
    return result
