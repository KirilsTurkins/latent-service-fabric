#!/usr/bin/env python3
"""Extract #106 descriptive results only after both full aggregates complete.

This reporting helper does not run collectors, tests, profilers or semantic
replay. Supply aggregates already produced by the official semantic validators.
Optional matching suites supply actual elapsed times and hash-bound raw matrix
code charges/memory endpoints. Missing raw inputs stay explicitly unavailable.
No output is created until all input/population/arithmetic checks succeed.
"""
import argparse
from collections import Counter
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

MAX_DOCUMENT = 8 * 1024**2
MAX_RAW = 32 * 1024**2
MAX_RAW_TOTAL = 1024**3
SELECTORS = ("O", "D0", "P0", "D1", "P1")
SELECTOR_KEYS = {"O": ("control", "D0"), **{name: ("candidate", name) for name in SELECTORS[1:]}}
ORDERS = ("O D0 P0 D1 P1", "O P1 D1 P0 D0", "P0 D1 P1 O D0", "P0 D0 O P1 D1",
          "P1 O D0 P0 D1", "P1 D1 P0 D0 O", "D0 P0 D1 P1 O")
CONTRASTS = (("default-preservation", "O", "D0"), ("pooling-speed", "D0", "P0"),
             ("speed-and-size-on-demand", "D0", "D1"), ("pooling-speed-and-size", "D0", "P1"))
PHASES = {"echo": (40, 400), "compute": (4, 128), "memory": (2, 64), "concurrent-echo": (4, 128)}
MEMORY = ("vm_size_bytes", "vm_peak_bytes", "rss_bytes", "vm_hwm_bytes", "pss_bytes", "private_clean_bytes",
          "private_dirty_bytes", "shared_clean_bytes", "shared_dirty_bytes")
STAGES = ("repository_fetch_verified", "metadata_validation", "component_new", "surface_link", "cache_adoption", "whole_job", "queue_wait")
LIMITATIONS = [
    "Reporting checks are not another full semantic replay; publication replay/CI receipts remain separate.",
    "Seven process observations per row; median paired delta is not difference of row medians. No pooled individual-call estimate.",
    "Three configuration contrasts reuse the same actual candidate D0 in each block. Order strata are small descriptive subsets.",
    "Successful latency is conditional on success. All-offered counts, warmups, intentional faults and budget misses remain retained.",
    "Matrix throughput includes Invoke, status, validation and retention; external throughput spans scheduled measured offers to completion.",
    "Matrix CPU combines node/client/observation work; external server and client CPU cover their full batches including warmup.",
    "Compilation stages overlap. Do not sum whole_job CPU/time with its child stages or infer totals from a stage median.",
    "Virtual mappings, kernel high-water fields, sampled RSS, smaps values and compiled-image span charges are distinct.",
    "Missing values are unavailable, never zero. No allocation-per-call, physical-pool-slot, universal speedup or SLO claim.",
    "Historical #104/#105 medians are not subtracted. External default D0 results do not qualify P0/D1/P1 external performance.",
    "The maintained Echo guest emits its result log in both arms. The corrected replay oracle checks this existing behavior; logging is not removed from timings.",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def read(path, maximum=MAX_DOCUMENT):
    path = Path(path)
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= maximum, "input file bound: " + str(path))
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    require(len(data) <= maximum and len(data) == path.stat().st_size, "input changed or oversized")
    value = json.loads(data, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    return value, {"path": str(path.resolve()), "bytes": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}


def numeric(value):
    if value is None:
        return None
    require(type(value) in (str, int, Decimal), "nonexact numeric input")
    result = Decimal(value)
    require(result.is_finite(), "nonfinite metric")
    return result


def encoded(value):
    if value is None:
        return None
    value = numeric(value)
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def median(values):
    ordered = sorted(numeric(value) for value in values if value is not None)
    return None if not ordered else (ordered[(len(ordered) - 1) // 2] + ordered[len(ordered) // 2]) / 2


def observation_summary(values):
    known = [numeric(value) for value in values if value is not None]
    return {"observations": len(values), "available": len(known), "unavailable": len(values) - len(known),
            "minimum": encoded(min(known)) if known else None, "median": encoded(median(known)),
            "maximum": encoded(max(known)) if known else None}


def paired_summary(rows):
    known = [row for row in rows if row["delta"] is not None]
    return {"pair_count": len(rows), "available_pairs": len(known), "unavailable_pairs": len(rows) - len(known),
            "baseline_median": encoded(median([row["baseline"] for row in known])),
            "candidate_median": encoded(median([row["candidate"] for row in known])),
            "paired_delta_median": encoded(median([row["delta"] for row in known])),
            "paired_percentage_median": encoded(median([row["percentage"] for row in known])),
            "percentage_pairs": sum(row["percentage"] is not None for row in known),
            **{name: sum(test(numeric(row["delta"])) for row in known) for name, test in
               (("lower", lambda n: n < 0), ("equal", lambda n: n == 0), ("higher", lambda n: n > 0))}}


def paired_metric(pairs, key):
    values = []
    with localcontext() as context:
        context.prec = 40
        for pair in pairs:
            left, right = (numeric(pair[arm][key]) for arm in ("baseline", "candidate"))
            delta = None if left is None or right is None else right - left
            percent = None if delta is None or left == 0 else delta * 100 / left
            values.append({"repetition": pair["repetition"], "order": pair["order"], "rotation_direction": pair["rotation_direction"],
                           "baseline": encoded(left), "candidate": encoded(right), "delta": encoded(delta), "percentage": encoded(percent)})
    return {**paired_summary(values), "pairs": values,
            "order_strata": {order: paired_summary([row for row in values if row["order"] == order])
                             for order in ("baseline-first", "candidate-first")},
            "rotation_strata": {order: paired_summary([row for row in values if row["rotation_direction"] == order])
                                for order in sorted({row["rotation_direction"] for row in values})}}


def complete(value, schema, attempts, processes):
    require(value.get("schema") == schema and value.get("profile") == "full" and value.get("status") == "complete"
            and value.get("population_complete") is True and value.get("attempt_count_complete") is True
            and value.get("validated_attempts") == str(attempts) and value.get("validated_processes") == str(processes),
            "requires actual complete full-population aggregate: " + schema)
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", value["suite_sha256"]) is not None, "invalid suite digest")


def matrix_key(row):
    return row["repetition"], row["variant"], row["engine_profile_id"]


def matrix_base(value):
    complete(value, "latent.optimization.engine-aggregate.v1", 27790, 35)
    require(value.get("validated_commands") == "56315" and len(value["runs"]) == 35, "matrix population mismatch")
    expected = [(block, slot, *SELECTOR_KEYS[name]) for block, order in enumerate(ORDERS, 1) for slot, name in enumerate(order.split())]
    require([(r["repetition"], r["sequence_ordinal"], r["variant"], r["engine_profile_id"]) for r in value["runs"]] == expected,
            "matrix actual order differs from fixed rotation/reversal")
    result = {}
    for row in value["runs"]:
        require(row["status"] == "passed" and row["validated_attempts"] == "794" and row["validated_commands"] == "1609"
                and row["attempt_count_complete"] is True and row["source"]["dirty"] is False, "incomplete or dirty matrix owner")
        require([(p["phase"], p["population"], p["offers"]) for p in row["phases"]]
                == [(name, label, str(count)) for name, counts in PHASES.items() for label, count in zip(("warmup", "measured"), counts)],
                "matrix phase population mismatch")
        metrics = dict(row["metrics"])
        require(len(metrics) <= 1024, "metric count bound")
        frequency = numeric(row["preparation"]["clock_ticks_per_second"])
        require(frequency is not None and frequency > 0 and row["preparation"]["jobs"] == "8", "preparation count/clock")
        require([stage["stage"] for stage in row["preparation"]["stages"]] == list(STAGES), "stage population")
        for stage in row["preparation"]["stages"]:
            prefix = "derived.preparation." + stage["stage"] + "."
            metrics[prefix + "records"] = stage["records"]
            for quantile in ("median", "p95", "p99"):
                metrics[prefix + quantile + "_nanos"] = None if stage["elapsed_nanos"] is None else stage["elapsed_nanos"][quantile]
            cpu = (numeric(stage["thread_cpu_user_ticks"]) + numeric(stage["thread_cpu_system_ticks"]))
            available = int(stage["thread_cpu_unavailable"]) == 0 and int(stage["thread_cpu_available"]) == int(stage["records"])
            metrics[prefix + "total_cpu_ticks"] = encoded(cpu) if available else None
            metrics[prefix + "total_cpu_seconds"] = encoded(cpu / frequency) if available else None
        for field in MEMORY:
            for statistic in ("minimum", "maximum", "last"):
                metrics[f"derived.memory.{field}.{statistic}"] = row["memory"]["fields"][field][statistic]
        metrics["derived.artifact.backend_executable_bytes"] = row["binary"]["bytes"]
        result[matrix_key(row)] = {"record": row, "metrics": metrics, "raw_inputs": None}
    return result


def checked_suite(path, aggregate, schema):
    if path is None:
        return None, None
    value, receipt = read(path)
    require(receipt["sha256"] == aggregate["suite_sha256"] and value["schema"] == schema
            and value["profile"] == "full" and value["status"] == "passed", "suite aggregate binding")
    return value, receipt


def raw_reference(root, reference):
    relative = PurePosixPath(reference["path"])
    require(not relative.is_absolute() and all(part not in ("", ".", "..") for part in relative.parts)
            and "\\" not in reference["path"] and ":" not in reference["path"], "raw reference path")
    current = root
    for part in relative.parts:
        current = current / part
        require(not current.is_symlink(), "raw reference symlink")
    current.resolve().relative_to(root.resolve())
    value, receipt = read(current, MAX_RAW)
    require(receipt["sha256"] == reference["sha256"] and receipt["bytes"] == int(reference["bytes"]), "raw reference digest/bytes")
    return value, receipt


def memory_values(value):
    entries = {**value["status"]["values"], **value["smaps_rollup"]["values"]}
    require(set(entries) == set(MEMORY), "raw memory fields")
    return {name: row["value_bytes"] for name, row in entries.items()}, {name: row["reason"] for name, row in entries.items() if row["value_bytes"] is None}


def raw_matrix(rows, suite, root):
    if suite is None:
        return {"status": "unavailable", "reason": "matching matrix suite and raw files not supplied; compiled charges not inferred"}
    require(len(suite["runs"]) == 35, "raw matrix owner count")
    total = 0
    for entry in suite["runs"]:
        owner = rows[matrix_key(entry)]
        raw, receipt = raw_reference(root, entry["raw"])
        total += receipt["bytes"]
        require(total <= MAX_RAW_TOTAL and raw["status"] == "passed" and raw["reason"] is None
                and matrix_key(raw["plan"]) == matrix_key(entry)
                and raw["identity"]["source"] == owner["record"]["source"]
                and raw["identity"]["binary"] == owner["record"]["binary"], "raw owner/identity/status binding")
        metrics, unavailable = owner["metrics"], {}
        points = {row["label"]: row for row in raw["samples"] if row["kind"] == "checkpoint"}
        points["before-shutdown"] = raw["before_shutdown"]
        for label in ("empty", "echo-after-measured", "compute-after-measured", "memory-after-measured",
                      "concurrent-echo-after-measured", "functional-after-drain", "before-shutdown"):
            point = points[label]
            for population in ("live", "resident", "unpublished", "evicted_live"):
                for field in ("runtimes", "source_bytes", "metadata_bytes", "compiled_image_bytes"):
                    metrics[f"raw.{label}.runtime.{population}.{field}"] = point["accounting"]["runtimes"][population][field]
            metrics[f"raw.{label}.resident.compiled_image_bytes"] = point["accounting"]["resident"]["compiled_image_bytes"]
        memory_points = {"before-node": raw["before_node_memory"], "empty": points["empty"]["memory"],
                         "before-shutdown": points["before-shutdown"]["memory"], "after-shutdown": raw["after_shutdown_memory"]}
        for label, point in memory_points.items():
            values, reasons = memory_values(point)
            metrics.update({f"raw.{label}.memory.{name}": value for name, value in values.items()})
            unavailable[label] = reasons
        ledger = raw["final_runtime_accounting"]
        require(all(numeric(value) == 0 for population in ledger.values() for value in population.values()), "raw final runtime owners/costs not zero")
        for population, fields in ledger.items():
            metrics.update({f"raw.after-shutdown.runtime.{population}.{name}": value for name, value in fields.items()})
        stages = raw["final_preparation"]["snapshot"]["recent_stages"]
        require(len(stages) == int(owner["record"]["preparation"]["stage_records"]) <= 256, "raw stage population")
        for stage in STAGES:
            selected = [row for row in stages if row["stage"] == stage]
            metrics[f"raw.preparation.{stage}.total_elapsed_nanos"] = encoded(sum(numeric(row["finished_nanos"]) - numeric(row["started_nanos"]) for row in selected))
        release = raw["fixtures"][0]["target"]["release_digest"]
        first = [row for row in stages if row["stage"] == "component_new"
                 and "sha256:" + bytes(int(value) for value in row["component_digest"]).hex() == release]
        require(len(first) == 1, "fresh Echo compilation identity")
        metrics["raw.fresh_echo.component_new.elapsed_nanos"] = encoded(numeric(first[0]["finished_nanos"]) - numeric(first[0]["started_nanos"]))
        cpu = first[0]["thread_cpu"]
        metrics["raw.fresh_echo.component_new.cpu_ticks"] = None if cpu is None else encoded(sum(numeric(cpu["after"][key]) - numeric(cpu["before"][key]) for key in ("user_ticks", "system_ticks")))
        owner["raw_inputs"] = {"file": receipt, "memory_unavailable_reasons": unavailable, "final_runtime_accounting": ledger}
    return {"status": "available", "files": 35, "read_bytes": total,
            "scope": "hash-bound raw endpoints and stage arithmetic; not a second semantic replay"}


def matrix_analysis(value, rows):
    keys = set(next(iter(rows.values()))["metrics"])
    require(all(set(row["metrics"]) == keys for row in rows.values()) and len(keys) <= 1024, "derived metric keys differ")
    profiles = {}
    for label, selector in SELECTOR_KEYS.items():
        selected = [rows[block, *selector] for block in range(1, 8)]
        profiles[label] = {"metrics": {key: observation_summary([row["metrics"][key] for row in selected]) for key in sorted(keys)},
                           "owners": [{"repetition": row["record"]["repetition"], "sequence_ordinal": row["record"]["sequence_ordinal"],
                                       "source": row["record"]["source"], "binary": row["record"]["binary"],
                                       "configuration_digest": row["record"]["configuration_digest"], "metrics": row["metrics"],
                                       "phases": row["record"]["phases"], "preparation": row["record"]["preparation"],
                                       "memory_availability": row["record"]["memory"]["fields"], "raw_inputs": row["raw_inputs"]} for row in selected]}
    stored = {row["id"]: row for row in value["comparisons"]}
    require(set(stored) == {row[0] for row in CONTRASTS}, "matrix contrasts")
    contrasts = {}
    for label, baseline, candidate in CONTRASTS:
        existing = stored[label]
        require(len(existing["pairs"]) == 7, "matrix paired population")
        pairs = []
        for block in range(1, 8):
            left, right = (rows[block, *SELECTOR_KEYS[name]] for name in (baseline, candidate))
            old = existing["pairs"][block - 1]
            require(old["repetition"] == block and old["baseline"]["metrics"] == left["record"]["metrics"]
                    and old["candidate"]["metrics"] == right["record"]["metrics"]
                    and set(old["candidate_minus_baseline"]) == set(left["record"]["metrics"])
                    and set(existing["metrics"]) == set(left["record"]["metrics"]), "aggregate pair does not reference actual owners")
            for arm, actual in (("baseline", left["record"]), ("candidate", right["record"])):
                require(all(old[arm][key] == actual[key] for key in ("repetition", "sequence_ordinal", "variant", "engine_profile_id"))
                        and old[arm]["source_commit"] == actual["source"]["commit"]
                        and old[arm]["binary_sha256"] == actual["binary"]["sha256"]
                        and old[arm]["configuration_digest"] == actual["configuration_digest"], "aggregate pair identity differs")
            for key, delta in old["candidate_minus_baseline"].items():
                a, b = (numeric(row["record"]["metrics"][key]) for row in (left, right))
                require(numeric(delta) == (None if a is None or b is None else b - a), "stored paired difference mismatch")
            a_slot, b_slot = left["record"]["sequence_ordinal"], right["record"]["sequence_ordinal"]
            pairs.append({"repetition": block, "actual_five_row_order": ORDERS[block - 1],
                          "baseline_sequence_ordinal": a_slot, "candidate_sequence_ordinal": b_slot,
                          "order": "baseline-first" if a_slot < b_slot else "candidate-first",
                          "rotation_direction": "forward" if block % 2 else "reversed",
                          "baseline": left["metrics"], "candidate": right["metrics"]})
        metrics = {key: paired_metric(pairs, key) for key in sorted(keys)}
        for key, original in existing["metrics"].items():
            current = metrics[key]
            for field in ("available_pairs", "unavailable_pairs", "lower", "equal", "higher"):
                require(current[field] == original[field], "stored contrast count mismatch")
            for old_name, new_name in (("baseline", "baseline_median"), ("candidate", "candidate_median"), ("paired_difference", "paired_delta_median")):
                require(numeric(current[new_name]) == (None if original[old_name] is None else numeric(original[old_name]["median"])), "stored contrast median mismatch")
        contrasts[label] = {"baseline": baseline, "candidate": candidate, "shared_D0": label != "default-preservation", "pairs": pairs, "metrics": metrics}
    return {"profiles": profiles, "contrasts": contrasts, "functional": [row["record"]["functional"] for row in rows.values()],
            "shutdown": [row["record"]["shutdown"] for row in rows.values()]}


def external_analysis(value):
    complete(value, "latent.optimization.engine-warm-aggregate.v1", 6160, 42)
    require(len(value["runs"]) == 14 and [row["id"] for row in value["comparisons"]] == ["warm-echo"], "external population")
    expected_order = [(block, arm) for block in range(1, 8) for arm in (("control", "candidate") if block % 2 else ("candidate", "control"))]
    require([(row["repetition"], row["variant"]) for row in value["runs"]] == expected_order, "external process order")
    frequency = numeric(value["clock_ticks_per_second"])
    require(frequency is not None and frequency > 0, "external CPU frequency")
    records, totals = {}, {}
    for row in value["runs"]:
        require(row["status"] == "passed" and len(row["batches"]) == 1, "external failed/missing batch")
        batch = row["batches"][0]
        require(batch["id"] == "warm-echo" and batch["warmup"]["counts"]["attempts"] == "40"
                and batch["measured"]["counts"]["attempts"] == "400", "external batch population")
        measured, metrics = batch["measured"], {}
        for name in ("successful_response_latency_nanos", "all_offered_elapsed_nanos"):
            for quantile in ("median", "p95", "p99"):
                metrics[name + "_" + quantile] = None if measured[name] is None else measured[name][quantile]
        for name in ("successes_per_second", "attempts_per_second", "budget_successes", "budget_misses"):
            metrics[name] = measured[name]
        for role in ("server", "client"):
            resource = batch["resources"][role]
            metrics.update({role + "." + key: item for key, item in resource.items()})
            ticks = numeric(resource["cpu_user_ticks"]) + numeric(resource["cpu_system_ticks"])
            metrics[role + ".cpu_ticks"] = encoded(ticks)
            metrics[role + ".cpu_seconds"] = encoded(ticks / frequency)
        records[row["repetition"], row["variant"]] = {"metrics": metrics, "batch": batch, "transport_cleanup": row["transport_cleanup"]}
        totals.setdefault(row["variant"], []).append(records[row["repetition"], row["variant"]])
    comparison = value["comparisons"][0]
    require(len(comparison["pairs"]) == 7, "external pairs")
    pairs = []
    for block in range(1, 8):
        old = comparison["pairs"][block - 1]
        require(old["repetition"] == block and all(old[arm] == records[block, arm]["batch"]["measured"] for arm in ("control", "candidate")), "external pair references differ")
        pairs.append({"repetition": block, "order": "baseline-first" if block % 2 else "candidate-first",
                      "rotation_direction": "not-applicable", "baseline": records[block, "control"]["metrics"],
                      "candidate": records[block, "candidate"]["metrics"]})
        for key, delta in old["candidate_minus_control_nanos"].items():
            left, right = (numeric(pairs[-1][arm][key]) for arm in ("baseline", "candidate"))
            require(numeric(delta) == (None if left is None or right is None else right - left), "external stored paired delta mismatch")
    keys = sorted(pairs[0]["baseline"])
    require(all(set(pair[arm]) == set(keys) for pair in pairs for arm in ("baseline", "candidate")), "external metric fields differ")
    metrics = {key: paired_metric(pairs, key) for key in keys}
    for key, summary in comparison["paired_differences_nanos"].items():
        require(numeric(summary["median"]) == numeric(metrics[key]["paired_delta_median"]), "external stored paired median mismatch")
    totals_result = {}
    for arm, selected in totals.items():
        phases = {}
        for phase in ("warmup", "measured"):
            outcomes = Counter()
            for row in selected:
                outcomes.update({key: int(item) for key, item in row["batch"][phase]["counts"]["outcomes"].items()})
            phases[phase] = {"offers": sum(int(row["batch"][phase]["counts"]["attempts"]) for row in selected), "outcomes": dict(outcomes),
                             "useful_on_time_successes": sum(int(row["batch"][phase]["budget_successes"]) for row in selected),
                             "budget_misses": sum(int(row["batch"][phase]["budget_misses"]) for row in selected)}
        totals_result[arm] = {"phases": phases, "batch_cpu_seconds": {role: encoded(sum(numeric(row["metrics"][role + ".cpu_seconds"]) for row in selected)) for role in ("server", "client")}}
    return {"pairs": pairs, "metrics": metrics, "totals": totals_result, "clock_ticks_per_second": value["clock_ticks_per_second"],
            "batches": [{"repetition": key[0], "variant": key[1], **record} for key, record in records.items()]}


def markdown(result):
    lines = ["# Issue 106 descriptive extraction", "", "Input full-population and aggregate arithmetic checks passed. This helper did not perform semantic replay.", ""]
    lines += ["## External warm D0", "", "| Metric (original units) | Control median | Candidate median | Median paired delta | Lower/equal/higher | Available pairs |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key, value in result["external"]["metrics"].items():
        lines.append(f"| {key} | {value['baseline_median']} | {value['candidate_median']} | {value['paired_delta_median']} | {value['lower']}/{value['equal']}/{value['higher']} | {value['available_pairs']}/7 |")
    chosen = ["fresh_engine_first_echo.latency_nanos", "derived.preparation.component_new.median_nanos",
              "preparation.component_new.total_cpu_ticks", "process.population_and_controls.cpu_seconds",
              "derived.memory.vm_size_bytes.maximum", "derived.memory.vm_peak_bytes.maximum", "derived.memory.rss_bytes.maximum",
              "derived.memory.vm_hwm_bytes.maximum", "raw.before-shutdown.resident.compiled_image_bytes"]
    lines += ["", "## Five profile medians", "", "| Metric (original units) | " + " | ".join(SELECTORS) + " |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key in chosen:
        values = [result["matrix"]["profiles"][name]["metrics"].get(key, {}).get("median", "unavailable") for name in SELECTORS]
        lines.append("| " + key + " | " + " | ".join(str(value) for value in values) + " |")
    for label, contrast in result["matrix"]["contrasts"].items():
        lines += ["", "## " + label, "", "| Metric (original units) | Baseline median | Candidate median | Median paired delta | Lower/equal/higher | Available pairs |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        selected = chosen + [f"phase.{phase}.{name}" for phase in PHASES for name in
                   ("successful.median_nanos", "successful.p95_nanos", "successful.p99_nanos", "all_offered.p99_nanos",
                    "backend_setup_micros.median", "guest_call_micros.median", "activation_resource_reclamation_micros.median", "throughput_rps", "process_cpu_ticks")]
        for key in selected:
            value = contrast["metrics"].get(key)
            if value is not None:
                lines.append(f"| {key} | {value['baseline_median']} | {value['candidate_median']} | {value['paired_delta_median']} | {value['lower']}/{value['equal']}/{value['higher']} | {value['available_pairs']}/7 |")
    lines += ["", "All seven pair values, percentages, order strata, full metric tables and availability reasons are retained in the adjacent JSON.",
              "", "## Scope", "", *["- " + note for note in LIMITATIONS], ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-aggregate", type=Path, required=True)
    parser.add_argument("--external-aggregate", type=Path, required=True)
    parser.add_argument("--matrix-suite", type=Path, help="Matching suite with raw paths relative to its parent; required for code-charge extraction")
    parser.add_argument("--external-suite", type=Path, help="Matching suite for actual collection elapsed times")
    parser.add_argument("--output-prefix", type=Path, required=True, help="Fresh .json/.md outputs; refuses overwrite")
    args = parser.parse_args()
    outputs = [Path(str(args.output_prefix) + suffix) for suffix in (".json", ".md")]
    require(all(not path.exists() and not path.is_symlink() for path in outputs), "output already exists")
    matrix, matrix_receipt = read(args.matrix_aggregate)
    external, external_receipt = read(args.external_aggregate)
    rows = matrix_base(matrix)
    external_result = external_analysis(external)
    matrix_suite, matrix_suite_receipt = checked_suite(args.matrix_suite, matrix, "latent.optimization.engine-suite.v1")
    external_suite, external_suite_receipt = checked_suite(args.external_suite, external, "latent.optimization.engine-warm-suite.v1")
    raw = raw_matrix(rows, matrix_suite, None if args.matrix_suite is None else args.matrix_suite.parent)
    result = {"schema": "latent.optimization.engine-descriptive-analysis.v1", "input_receipts": {"matrix": matrix_receipt, "external": external_receipt,
              "matrix_suite": matrix_suite_receipt, "external_suite": external_suite_receipt},
              "population": {"matrix_owners": 35, "matrix_invokes": 27790, "matrix_commands": 56315, "matrix_warmup": 1750,
              "matrix_measured": 25200, "matrix_functional": 840, "external_invokes": 6160, "external_warmup": 560, "external_measured": 5600},
              "raw_matrix": raw, "matrix": matrix_analysis(matrix, rows), "external": external_result,
              "source_receipts": {"matrix_requested_refs": matrix["builds"]["requested_refs"], "external_builds": external["identity"]["builds"]},
              "stage_elapsed_nanos": {"matrix_collection": None if matrix_suite is None else matrix_suite["elapsed_nanos"],
              "external_collection": None if external_suite is None else external_suite["measurement_elapsed_nanos"],
              "external_suite_total": None if external_suite is None else external_suite["elapsed_nanos"]},
              "semantic_replay_performed_by_this_helper": False, "limitations": LIMITATIONS}
    encoded_result = (json.dumps(result, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    note = markdown(result).encode()
    require(len(encoded_result) <= 16 * 1024**2 and len(note) <= 1024**2, "report artifact bound")
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    for path, data in zip(outputs, (encoded_result, note)):
        with path.open("xb") as output:
            output.write(data)
    print(json.dumps({"outputs": [str(path) for path in outputs], "input_population_checks": "passed", "semantic_replay": "not performed"}))


if __name__ == "__main__":
    main()
