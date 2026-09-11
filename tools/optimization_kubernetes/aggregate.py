"""Descriptive Kubernetes pairs and the separately collected original Docker pairs."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path

from tools.optimization_docker import aggregate as docker
from tools.optimization_evidence.common import (
    canonical, distribution, integer, ratio, require, sha256, uint,
)
from . import model

SCHEMA = model.PREFIX + "aggregate.v1"
PHASE_DIMENSIONS = ("density", "phase_name", "phase_kind", "function", "concurrency")
SPREAD_FIELDS = ("count", "minimum", "median", "maximum", "median_absolute_deviation")
CROSS_PHASE = ("successful_response_latency_nanos.median", "successful_response_latency_nanos.p99",
    "all_dispatched_latency_nanos.median", "all_dispatched_latency_nanos.p99",
    "all_offered_elapsed_nanos.p99", "dispatch_lag_nanos.p99", "successful_response_fraction",
    "successes_per_second", "phase_span_successes_per_second")
CROSS_RESOURCE = ("child.rss_bytes", "wrapper.rss_bytes", "child.threads", "wrapper.threads",
    "cgroup.memory_current_bytes", "cgroup.pids_current", "cgroup.cpu.usage_usec", "cgroup.cpu.throttled_usec")
CROSS_WINDOW = ("cgroup.cpu.usage_usec", "cgroup.cpu.user_usec", "cgroup.cpu.system_usec",
                "cgroup.cpu.throttled_usec")
TABLES = ("phase_rows", "phase_comparisons", "resource_points", "resource_comparisons", "idle_windows",
    "idle_window_comparisons", "lifecycle_owners", "lifecycle_cohorts", "lifecycle_comparisons",
    "client_resource_points", "client_intervals", "client_cpu_comparisons", "platform_comparisons",
    "node_resource_points", "node_resource_intervals", "cpu_limit_cohorts")


def _spread(values):
    result = distribution([Decimal(value) for value in values]) if values else None
    return None if result is None else {key: result[key] for key in SPREAD_FIELDS}


def _compact(rows):
    """Keep every pair; reduce only redundant summary columns in the bounded JSON."""
    result = []
    for row in rows:
        value = dict(row)
        for key in ("native", "lsf", "paired_difference"):
            summary = value[key]
            value[key] = None if summary is None else {name: summary[name] for name in SPREAD_FIELDS}
        value["order_strata"] = _compact_summary_strata(row["order_strata"])
        result.append(value)
    return result


def _compact_summary_strata(strata):
    result = {}
    for arm, summary in strata.items():
        result[arm] = {key: ({name: value[name] for name in SPREAD_FIELDS} if value is not None else None)
                       if key in ("native", "lsf", "paired_difference") else value
                       for key, value in summary.items()}
    return result


def platform_comparisons(kubernetes, original, dimensions, units, *, family):
    """Match recorded pair indices; the platforms were separate campaigns."""
    indexed = []
    for rows in (original, kubernetes):
        current = {}
        for row in rows:
            key = (integer(row["pair"], 0, 6), *(row[name] for name in dimensions))
            require(key not in current, "kubernetes-aggregate-duplicate-platform-row")
            current[key] = row
        indexed.append(current)
    before, after = indexed
    require(before.keys() == after.keys(), "kubernetes-aggregate-unmatched-platform-population")
    grouped = defaultdict(list)
    for key in sorted(before):
        left, right = before[key], after[key]
        require(type(left["group"]) is int and type(right["group"]) is int
                and left["group"] == right["group"], "kubernetes-aggregate-platform-order")
        if family == "phase":
            require(canonical(left["counts"]) == canonical(right["counts"]),
                    "kubernetes-aggregate-platform-outcome-population")
        grouped[key[1:]].append((key[0], left, right))
    result = []
    for key, pairs in sorted(grouped.items()):
        for metric, unit in units.items():
            observations = []
            for pair, left, right in pairs:
                baseline, candidate = left["metrics"][metric], right["metrics"][metric]
                delta = docker._difference(baseline, candidate)
                observations.append({"pair": pair, "docker_group": left["group"], "kubernetes_group": right["group"],
                    "docker": baseline, "kubernetes": candidate, "kubernetes_minus_docker": delta,
                    "percent_of_docker": None if delta is None else ratio(Decimal(delta) * 100, Decimal(baseline))})
            available = [row for row in observations if row["kubernetes_minus_docker"] is not None]
            deltas = [Decimal(row["kubernetes_minus_docker"]) for row in available]
            result.append({"family": family, **dict(zip(dimensions, key)), "metric": metric, "unit": unit,
                "pair_count": len(observations), "available_pairs": len(available),
                "unavailable_pairs": len(observations) - len(available), "pairs": observations,
                "docker": _spread([row["docker"] for row in available]),
                "kubernetes": _spread([row["kubernetes"] for row in available]),
                "paired_difference": _spread(deltas), "lower": sum(value < 0 for value in deltas),
                "equal": sum(value == 0 for value in deltas), "higher": sum(value > 0 for value in deltas)})
    return result


def lifecycle_rows(groups, clients):
    by_pair = {row["evidence"]["pair"]: row for row in clients}
    owners, cohorts = [], []
    for group in groups:
        identity = {key: group[key] for key in ("pair", "group", "arm", "density")}
        client = by_pair[group["pair"]]
        first, = [row for row in client["evidence"]["first_responses"] if row["group"] == group["group"]]
        commands = client["parent"]["commands"]
        ordinal, = [index for index, row in enumerate(commands) if (value := json.loads(row["line"]))["command"] == "phase"
                    and value["group"] == group["group"] and value["phase"] == 0]
        ack, = [row for row in client["parent"]["acknowledgements"]
                if row["ack"]["event"] == "first-response" and row["ack"]["command_ordinal"] == ordinal]
        observed = ack["received_nanos"]
        require(uint(group["graph_ready_nanos"]) <= uint(group["proxy_ready_nanos"])
                <= uint(commands[ordinal]["sent_nanos"]), "kubernetes-aggregate-proxy-readiness-order")
        starts, ready_times, first_owner = [], [], None
        for owner in group["owners"]:
            parent, life = owner["parent"], owner["lifecycle"]
            ready, = [row["observed_nanos"] for row in parent["event_observations"] if row["sequence"] == 1]
            start, end = life["create_started_nanos"], life["create_finished_nanos"]
            require(uint(start) <= uint(end) <= uint(ready) <= uint(group["graph_ready_nanos"]),
                    "kubernetes-aggregate-lifecycle-order")
            starts.append(uint(start))
            ready_times.append(uint(ready))
            if parent["owner_ref"] == first["owner_ref"]:
                require(first_owner is None, "kubernetes-aggregate-duplicate-first-owner")
                first_owner = owner
            owners.append({**identity, "pod_uid": parent["pod_ready"]["metadata"]["uid"],
                "container_id": parent["container_id"], "owner_ref": parent["owner_ref"],
                "app_process_id": parent["app_process_id"], "create_api_begin_nanos": start,
                "create_api_end_nanos": end, "ready_observed_nanos": ready,
                "create_api_elapsed_nanos": docker._span(start, end),
                "create_to_ready_observed_upper_nanos": docker._span(start, ready)})
        require(first_owner is not None, "kubernetes-aggregate-first-response-owner")
        cohorts.append({**identity, "first_response": first, "first_response_ack_received_nanos": observed,
            "first_target_container_id": first_owner["parent"]["container_id"],
            "start_boundary": "parent-begin-Pod-create-API", "metrics": {
                "cohort_first_request_to_last_ready_observed_upper_nanos": docker._span(str(min(starts)), str(max(ready_times))),
                "cohort_first_request_to_first_response_observed_upper_nanos": docker._span(str(min(starts)), observed),
                "first_target_request_to_first_response_observed_upper_nanos": docker._span(
                    first_owner["lifecycle"]["create_started_nanos"], observed),
                "last_ready_observation_to_first_response_ack_nanos": docker._span(str(max(ready_times)), observed),
                "first_phase_command_to_first_response_ack_nanos": docker._span(commands[ordinal]["sent_nanos"], observed),
                "cohort_first_request_to_service_graph_ready_nanos": docker._span(str(min(starts)), group["graph_ready_nanos"]),
                "cohort_first_request_to_service_forwarding_ready_nanos": docker._span(str(min(starts)), group["proxy_ready_nanos"])}})
    return owners, cohorts


def client_rows(clients):
    points, intervals = [], []
    for client in clients:
        evidence, current = client["evidence"], {}
        for item in client["resources"]:
            stats = item["derived_stats"]
            if stats is None:
                require(item["stage"] == "final" and item["unavailable_reason"] is not None,
                        "kubernetes-aggregate-client-stats-absent")
                container_id = client["parent"]["final"]["observation"]["container_id"]
                cpu_timestamp = memory_timestamp = None
                metrics = {"cpu_total_nanos": None, "memory_working_set_bytes": None}
            else:
                container_id = stats["container_id"]
                cpu_timestamp, memory_timestamp = stats["cpu_timestamp_nanos"], stats["memory_timestamp_nanos"]
                metrics = {"cpu_total_nanos": stats["cpu_usage_nanos"],
                           "memory_working_set_bytes": stats["memory_working_set_bytes"]}
            for value in metrics.values():
                if value is not None:
                    uint(value)
            row = {"pair": evidence["pair"], "stage": item["stage"], "observed_nanos": item["observed_nanos"],
                "container_id": container_id, "metrics": metrics,
                "cpu_timestamp_nanos": cpu_timestamp, "memory_timestamp_nanos": memory_timestamp,
                "unavailable_reason": item["unavailable_reason"]}
            require(item["stage"] not in current, "kubernetes-aggregate-client-stage-duplicate")
            points.append(row)
            current[item["stage"]] = row
        for group in model.groups(evidence["profile"], evidence["pair"]):
            for start, end in (("ready", "served"), ("served", "final"), ("ready", "final")):
                before, after = (current[f"group-{group['ordinal']}-{stage}"] for stage in (start, end))
                delta = docker._difference(before["metrics"]["cpu_total_nanos"], after["metrics"]["cpu_total_nanos"])
                require(delta is None or Decimal(delta) >= 0, "kubernetes-aggregate-client-cpu-regression")
                intervals.append({"pair": evidence["pair"], "group": group["ordinal"], "arm": group["arm"],
                    "density": group["density"], "from_stage": start, "to_stage": end,
                    "parent_observation_elapsed_nanos": docker._span(before["observed_nanos"], after["observed_nanos"]),
                    "metrics": {"cpu_total_nanos": delta},
                    "memory_working_set_before_bytes": before["metrics"]["memory_working_set_bytes"],
                    "memory_working_set_after_bytes": after["metrics"]["memory_working_set_bytes"]})
    return points, intervals


def node_rows(background):
    """Outer node usage contains inner Pods; it is never added to leaf usage."""
    points, intervals, previous = [], [], {}
    for observation in background:
        for item in observation["observations"]:
            stats = item["stats"]
            row = {"stage": observation["stage"], "role": item["role"], "container_id": item["container_id"],
                "observed_nanos": item["observed_nanos"], "raw_sha256": sha256(canonical(item)), "metrics": {
                    "cpu_total_nanos": _node_counter(stats, "cpu_stats", "cpu_usage", "total_usage"),
                    "memory_usage_bytes": _node_counter(stats, "memory_stats", "usage")}}
            if row["role"] in previous:
                before = previous[row["role"]]
                require(before["container_id"] == row["container_id"], "kubernetes-aggregate-node-replaced")
                delta = docker._difference(before["metrics"]["cpu_total_nanos"], row["metrics"]["cpu_total_nanos"])
                require(delta is None or Decimal(delta) >= 0, "kubernetes-aggregate-node-cpu-regression")
                intervals.append({"role": row["role"], "container_id": row["container_id"],
                    "from_stage": before["stage"], "to_stage": row["stage"],
                    "parent_observation_elapsed_nanos": docker._span(before["observed_nanos"], row["observed_nanos"]),
                    "metrics": {"cpu_total_nanos": delta}})
            previous[row["role"]] = row
            points.append(row)
    return points, intervals


def _node_counter(stats, *path):
    value = docker._get(stats, *path)
    return None if value is None else str(integer(value, 0, 2**64 - 1))


def _docker_lifecycle(rows):
    aliases = {
        "cohort_first_start_to_last_ready_observed_upper_nanos": "cohort_first_request_to_last_ready_observed_upper_nanos",
        "cohort_first_start_to_first_response_observed_upper_nanos": "cohort_first_request_to_first_response_observed_upper_nanos",
        "first_target_start_to_first_response_observed_upper_nanos": "first_target_request_to_first_response_observed_upper_nanos"}
    return [{**row, "start_boundary": "parent-begin-Docker-container-start-API",
             "metrics": {aliases.get(name, name): value for name, value in row["metrics"].items()}} for row in rows]


def cpu_limit_cohorts(groups):
    """Keep requested CPU and kernel-enforced capacity separate from CPU usage."""
    rows = []
    for group in groups:
        count = group["density"] if group["arm"] == "native" else 1
        require(len(group["owners"]) == count, "kubernetes-aggregate-cpu-owner-population")
        requested = effective = Fraction(0)
        for owner in group["owners"]:
            snapshots = owner["resources"]["snapshots"]
            require(len(snapshots) == 6, "kubernetes-aggregate-cpu-snapshot-population")
            observed = []
            for snapshot in snapshots:
                limits = snapshot["provider"]["cgroup"]
                values = []
                for key in ("requested_cpu", "effective_cpu"):
                    value = limits[key]
                    quota, period = uint(value["quota"]), uint(value["period"])
                    require(quota > 0 and period > 0, "kubernetes-aggregate-cpu-finite")
                    values.append(Fraction(quota, period))
                require(type(limits["effective_cpu_matches_requested"]) is bool
                        and limits["effective_cpu_matches_requested"] == (values[0] == values[1]),
                        "kubernetes-aggregate-cpu-match-flag")
                observed.append(tuple(values))
            require(all(value == observed[0] for value in observed), "kubernetes-aggregate-cpu-limit-changed")
            requested += observed[0][0]
            effective += observed[0][1]
        require(requested == 4, "kubernetes-aggregate-cpu-requested-total")
        delta = effective - requested
        percent = delta * 100 / requested
        rows.append({**{key: group[key] for key in ("pair", "group", "arm", "density")},
            "application_owners": count, "snapshots_per_owner": 6,
            "scope": "sum-of-owner-effective-caps-not-cpu-usage",
            "requested_millicpus": ratio(requested.numerator * 1000, requested.denominator),
            "effective_millicpus": ratio(effective.numerator * 1000, effective.denominator),
            "effective_minus_requested_millicpus": ratio(delta.numerator * 1000, delta.denominator),
            "percent_above_requested": ratio(percent.numerator, percent.denominator),
            "effective_cpu_matches_requested": effective == requested})
    return rows


def _aggregate(derived, original):
    require(derived["status"] == "passed", "kubernetes-aggregate-unvalidated-input")
    profile = derived["profile"]
    plan = model.plan(profile, owner=derived["owner"], startup_protocol=model.suite_startup_protocol(derived))
    require(canonical(derived["plan"]) == canonical(plan), "kubernetes-aggregate-plan")
    require(original["profile"] == "full" and original["acceptance_qualified"] is True
            and original["full_population_completed"] is True, "kubernetes-aggregate-original-full-required")
    require(canonical(derived["build_source"]) == canonical(original["build_source"]),
            "kubernetes-aggregate-original-build-crossed")
    require(derived["docker_suite"]["sha256"] == original["suite_sha256"],
            "kubernetes-aggregate-original-suite-crossed")
    clients, groups = derived["clients"], derived["groups"]
    repetitions = model.repetitions(profile)
    require(len(clients) == repetitions and len(groups) == repetitions * 6
            and [row["evidence"]["pair"] for row in clients] == list(range(repetitions)),
            "kubernetes-aggregate-incomplete-population")
    expected = [[pair, row["ordinal"], row["arm"], row["density"]]
                for pair in range(repetitions) for row in model.groups(profile, pair)]
    require(canonical([[row[key] for key in ("pair", "group", "arm", "density")] for row in groups]) == canonical(expected),
            "kubernetes-aggregate-group-order")
    offers = plan["workload"]["logical_offers"]
    require(all(row["evidence"]["profile"] == profile and row["evidence"]["status"] == "complete" for row in clients)
            and sum(uint(row["evidence"]["offers"]) for row in clients) == uint(offers),
            "kubernetes-aggregate-offer-population")
    for name, value in {"offers": offers, "successful": offers, "seed_management_rpcs": "0", "seed_invokes": "0",
                        "measured_application_owners": 44 * repetitions, "client_owners": repetitions}.items():
        require(canonical(derived["counts"][name]) == canonical(value), "kubernetes-aggregate-count-population")
    phases, phase_units = docker.phase_rows(clients)
    require(len(phases) == repetitions * 30, "kubernetes-aggregate-phase-population")
    points, windows, resource_units = docker.resource_rows(groups)
    owners, cohorts = lifecycle_rows(groups, clients)
    client_points, client_intervals = client_rows(clients)
    node_points, node_intervals = node_rows(derived["background"])
    cpu_limits = cpu_limit_cohorts(groups)
    lifecycle_units = {name: "ns" for name in cohorts[0]["metrics"]}
    client_units = {"cpu_total_nanos": "ns"}
    cross = []
    if profile == original["profile"]:
        for family, rows, prior, dimensions, units in (
            ("phase", phases, original["phase_rows"], PHASE_DIMENSIONS, {key: phase_units[key] for key in CROSS_PHASE}),
            ("resource", points, original["resource_points"], ("density", "stage", "point"),
             {key: resource_units[key] for key in CROSS_RESOURCE}),
            ("idle-window", windows, original["idle_windows"], ("density", "stage"),
             {key: resource_units[key] for key in CROSS_WINDOW}),
            ("lifecycle", cohorts, _docker_lifecycle(original["lifecycle_cohorts"]), ("density",),
             {key: "ns" for key in cohorts[0]["metrics"] if key not in (
                 "cohort_first_request_to_service_graph_ready_nanos", "cohort_first_request_to_service_forwarding_ready_nanos")}),
            ("client-cpu", client_intervals, original["client_intervals"], ("density", "from_stage", "to_stage"), client_units)):
            cross.extend(platform_comparisons(rows, prior, ("arm", *dimensions), units, family=family))
    original_bytes = canonical(original) + b"\n"
    result = {"schema": SCHEMA, "status": "complete", "profile": profile, "plan": plan,
        "completed_paired_run": True, "full_population_completed": profile == "full", "acceptance_qualified": profile == "full",
        "acceptance_scope": "complete-descriptive-deployment-comparison",
        "exact_effective_cpu_match": all(row["effective_cpu_matches_requested"] for row in cpu_limits),
        "logical_offers": offers, "validated_pairs": repetitions, "source": derived["source"],
        "build_source": derived["build_source"], "suite_sha256": derived["suite_sha256"],
        "images": derived["images"], "counts": derived["counts"],
        "collection_elapsed_nanos": docker._span(derived["started_nanos"], derived["finished_nanos"]),
        "collection_scope": "owned-namespace-fixture-copy-paired-clients-parent-observation-and-cleanup",
        "original_docker": {"path": "docker-aggregate.json", "bytes": str(len(original_bytes)),
            "sha256": sha256(original_bytes), "suite_sha256": original["suite_sha256"], "source": original["source"],
            "build_source": original["build_source"], "profile": original["profile"],
            "logical_offers": original["logical_offers"], "validated_pairs": original["validated_pairs"]},
        "platform_comparison_status": "available" if cross else "unavailable-different-workload-populations",
        "platform_comparison_scope": "same-arm-and-pair-index-separate-campaigns-not-isolated-ClusterIP-overhead",
        "phase_rows": phases, "phase_comparisons": _compact(docker.comparisons(phases, PHASE_DIMENSIONS, phase_units)),
        "resource_points": points, "resource_comparisons": _compact(docker.comparisons(points, ("density", "stage", "point"), resource_units)),
        "idle_windows": windows, "idle_window_comparisons": _compact(docker.comparisons(windows, ("density", "stage"), resource_units)),
        "lifecycle_owners": owners, "lifecycle_cohorts": cohorts,
        "lifecycle_comparisons": _compact(docker.comparisons(cohorts, ("density",), lifecycle_units)),
        "client_resource_points": client_points, "client_intervals": client_intervals,
        "client_cpu_comparisons": _compact(docker.comparisons(client_intervals, ("density", "from_stage", "to_stage"), client_units)),
        "platform_comparisons": cross, "node_resource_points": node_points, "node_resource_intervals": node_intervals,
        "cpu_limit_cohorts": cpu_limits,
        "units": {"phase_metrics": phase_units, "resource_metrics": resource_units, "lifecycle_metrics": lifecycle_units,
                  "client_interval_metrics": client_units,
                  "client_point_metrics": {"cpu_total_nanos": "ns", "memory_working_set_bytes": "bytes"},
                  "node_metrics": {"cpu_total_nanos": "ns", "memory_usage_bytes": "bytes"}},
        "limitations": [
            "Seven full pairs are descriptive; same pair indices across separate Docker/Kubernetes campaigns are not randomized platform pairs.",
            "First, warmup and measured phases remain separate; arm summaries describe per-pair statistics, not pooled offer latencies.",
            "ClusterIP routing, Pod scheduling, startup probes, CNI, containerd, node services and observation differences remain in the platform contrast.",
            "Declared aggregate CPU/memory matches, with partitioned native per-service quotas versus pooled LSF resources; global C4 cannot borrow idle native partitions.",
            "Kernel CPU caps are reported separately in cpu_limit_cohorts. The systemd D32 native 125m request can enforce 130m per owner: 4.16 versus 4.0 CPUs (+4%). This is not an exactly matched effective CPU experiment, and caps are not measured CPU usage.",
            "Pod creation and Docker container start are different parent-observed lifecycle boundaries, with images already present.",
            "Kubernetes submits the cohort before waiting for readiness; original Docker provisioning is sequential. Both include connections and intentional 250ms barriers.",
            "Endpoint readiness and observed worker Service forwarding rules are separate boundaries. Read-only forwarding polls precede client connection and remain in cold lifecycle costs.",
            "API wall timestamps, CRI sample timestamps and client/wrapper/parent monotonic clocks are retained in their own domains; no cross-origin subtraction is used.",
            "Leaf cgroup CPU combines application and wrapper work, management and observation; no pure handler or separate child/wrapper CPU claim is made.",
            "Process RSS may double-count shared pages. Leaf usage is counted once; process, leaf, Pod ancestor and outer node memory are never added together.",
            "Sum of leaf lifetime memory peaks is not a simultaneous cohort peak. Exact within-invocation memory peaks are unmeasured.",
            "Outer kind node usage includes inner Pods and control-plane/background work; it is shown separately without background subtraction.",
            "CRI client memory working set and Docker client memory usage are different metrics and are not directly differenced.",
            "Client CPU counter deltas include validation/output and barrier intervals; CRI CPU/memory timestamps may differ or repeat because samples are cached.",
            "Any absent cohort component makes its metric unavailable. Missing values are not zero; unmatched smoke/full platform populations are not compared."]}
    require(len(canonical(result)) + 1 <= model.MAX_HELPER_BYTES, "kubernetes-aggregate-byte-bound")
    return result


def aggregate(derived, docker_derived):
    require(derived["status"] == "passed", "kubernetes-aggregate-unvalidated-input")
    return _aggregate(derived, docker.aggregate(docker_derived))


def write(derived, docker_derived, directory):
    """Exclusive report directory; retain the original Docker aggregate unchanged."""
    require(derived["status"] == "passed", "kubernetes-aggregate-unvalidated-input")
    original = docker.aggregate(docker_derived)
    result = _aggregate(derived, original)
    outputs = {"aggregate.json": canonical(result) + b"\n", "docker-aggregate.json": canonical(original) + b"\n"}
    outputs.update({name.replace("_", "-") + ".csv": docker._csv_bytes(result[name]) for name in TABLES})
    require(all(len(value) <= model.MAX_HELPER_BYTES for value in outputs.values()), "kubernetes-aggregate-output-bound")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    references = []
    for name, data in outputs.items():
        with (directory / name).open("xb") as stream:
            stream.write(data)
        references.append({"path": name, "bytes": str(len(data)), "sha256": sha256(data)})
    manifest = {"schema": model.PREFIX + "aggregate-files.v1", "profile": result["profile"],
        "suite_sha256": result["suite_sha256"], "docker_suite_sha256": original["suite_sha256"],
        "csv_null": "literal-null", "files": references}
    with (directory / "manifest.json").open("xb") as stream:
        stream.write(canonical(manifest) + b"\n")
    return result
