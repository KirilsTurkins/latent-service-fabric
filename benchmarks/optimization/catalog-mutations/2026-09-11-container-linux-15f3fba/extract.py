"""Project already-replayed full evidence; does not perform semantic validation."""
import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

# Exact clean checkpoint declaring one active expanded-file allowance.
CONTROL = "165d1eb5084c256dab72ac10217b26af3c6e4c44"
CANDIDATE = "15f3fba3f47404240dd577d9eaaa3f60270b81d1"
SELECTORS = ("sequence_ordinal", "repetition", "variant", "shape", "populated_size", "mode")
COUNTS = {"validated_collectors": "32", "planned_collectors": "32", "validated_commands": "45096",
          "validated_resolves": "224", "validated_invocations": "0", "validated_mutations": "64", "validated_reopens": "16"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def document(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 32 * 1024**2, "input-file-bound")
    body = path.read_bytes()
    require(len(body) <= 32 * 1024**2, "input-read-bound")
    return json.loads(body), {"bytes": str(len(body)), "sha256": digest(body)}


def expected_owners():
    rows = []
    for sizes, modes in (((100, 1000, 10000), ("initial", "reopen")), ((4,), ("allocation", "allocation-reopen"))):
        for index, size in enumerate(sizes):
            for shape_index, shape in enumerate(("distinct", "shared")):
                variants = ("control", "candidate") if (index + shape_index) % 2 == 0 else ("candidate", "control")
                for variant in variants:
                    for mode in modes:
                        rows.append(dict(zip(SELECTORS, (len(rows), 1, variant, shape, size, mode), strict=True)))
    return rows


def qualified(aggregate, suite, suite_ref):
    require(CONTROL is not None and CANDIDATE is not None, "source-identities-await-next-common-checkpoint")
    require(aggregate["schema"] == "latent.optimization.catalog-mutation-aggregate.v1"
            and suite["schema"] == "latent.optimization.catalog-mutation-suite.v1", "input-schema")
    require(aggregate["profile"] == suite["profile"] == "full" and aggregate["status"] == "complete"
            and suite["status"] == "passed" and suite["reason"] is None, "full-completed-inputs-required")
    require(all(aggregate[key] is True for key in ("population_complete", "attempt_count_complete", "qualifying_full_population")),
            "full-qualification-flags-required")
    require(all(aggregate[key] == value for key, value in COUNTS.items()), "full-population-counts")
    require(aggregate["suite"]["sha256"] == suite_ref["sha256"] and aggregate["builds"] == suite["builds"]
            and aggregate["plan"] == suite["plan"], "aggregate-suite-byte-or-plan-binding")
    require(suite["plan"]["normal_sizes"] == [100, 1000, 10000] and suite["plan"]["allocation_size"] == 4
            and suite["plan"]["normal_totals"]["commands"] == 44910
            and suite["plan"]["allocation_totals"]["commands"] == 186
            and suite["plan"]["maximum_folded_expanded_bytes"] == "536870912"
            and suite["plan"]["maximum_temporary_folded_bytes"] == "536870912"
            and suite["plan"]["maximum_artifact_bytes"] == "1073741824", "declared-stage-populations")
    for variant, commit in (("control", CONTROL), ("candidate", CANDIDATE)):
        require(aggregate["sources"][variant]["commit"] == commit and aggregate["sources"][variant]["clean"] is True,
                "actual-clean-measured-source-required")
    require(suite["runner_source"]["commit"] == CANDIDATE and suite["runner_source"]["clean"] is True
            and suite["runner_source_after"] == suite["runner_source"], "actual-clean-harness-required")
    expected = expected_owners()
    require(len(aggregate["runs"]) == len(suite["runs"]) == len(expected), "owner-count")
    for actual, recorded, selected in zip(aggregate["runs"], suite["runs"], expected, strict=True):
        require(all(type(actual[key]) is int and type(recorded[key]) is int
                    for key in ("sequence_ordinal", "repetition", "populated_size")), "selector-integer-type")
        require({key: actual[key] for key in SELECTORS} == {key: recorded[key] for key in SELECTORS} == selected
                and actual["status"] == recorded["status"] == "passed", "actual-owner-selection")
        require(actual["source"]["dirty"] is False and actual["source"]["commit"] ==
                (CONTROL if selected["variant"] == "control" else CANDIDATE), "owner-source-binding")
    require(len(aggregate["normal_pairs"]) == 6 and len(aggregate["allocation_pairs"]) == 4, "paired-population")


def csv_file(path, rows):
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "null" if value is None else json.dumps(value, separators=(",", ":"), sort_keys=True)
                             if isinstance(value, (dict, list)) else value for key, value in row.items()})


def pair_row(pair, metric, value, **extra):
    difference = value["candidate_minus_control"]
    return {"populated_size": pair["populated_size"], "shape": pair["shape"], "order": pair["order"],
            "owner_ordinals": pair["owner_ordinals"], **extra, "metric": metric, **value,
            "direction": None if difference is None else "lower" if Decimal(difference) < 0
            else "higher" if Decimal(difference) > 0 else "equal"}


def project(aggregate, suite):
    tables = {name: [] for name in ("normal-contrasts", "operations", "work-counters", "checkpoint-memory",
                                    "proofs", "samplers", "allocation-frames", "allocation-scopes", "allocation-contrasts", "owners")}
    for pair in aggregate["normal_pairs"]:
        tables["normal-contrasts"].extend(pair_row(pair, key, value) for key, value in pair["metrics"].items())
    for row, source in zip(aggregate["runs"], suite["runs"], strict=True):
        selected = {key: row[key] for key in SELECTORS}
        frequency = source["host_before"]["clock_ticks_per_second"]
        require(type(frequency) is int and 1 <= frequency <= 1_000_000, "actual-cpu-frequency-required")
        tables["owners"].append({**selected, "process_identity": row["process_identity"], "source": row["source"],
            "binary": row["binary"], "raw": source["raw"], "plan": source["plan"], "identity": source["identity"],
            "process": source["process"], "probe_process": source["probe_process"], "cleanup": source["cleanup"],
            "host_before": source["host_before"], "host_after": source["host_after"],
            "cgroup_before": source["cgroup_before"], "cgroup_after": source["cgroup_after"]})
        tables["samplers"].append({**selected, **row["sampler"]})
        operations = [("opening", row["opening"]), ("seed", row["seed"])]
        operations.extend((item["label"], item) for item in row["mutations"])
        for label, item in operations:
            if item is None:
                continue
            ticks = item["cpu_ticks"]
            tables["operations"].append({**selected, "operation": label,
                "started_nanos": item["started_nanos"], "finished_nanos": item["finished_nanos"],
                "elapsed_nanos": str(int(item["finished_nanos"]) - int(item["started_nanos"])),
                "cpu_ticks": ticks, "clock_ticks_per_second": frequency,
                "cpu_seconds": None if ticks is None else str(Decimal(ticks) / frequency),
                "cpu_scope": item["cpu_scope"], "cpu_before": item["cpu_before"], "cpu_after": item["cpu_after"],
                "sampled_memory": item["sampled_memory"]})
            tables["work-counters"].extend({**selected, "operation": label, "counter": key,
                "scope": "operation-local-work-receipt", "value": None if value is None else str(value)}
                for key, value in item["work_counts"].items())
            before, after = item.get("verification_before"), item["verification_after"]
            tables["work-counters"].extend({**selected, "operation": label, "counter": key,
                "scope": "fresh-process-opening-total" if before is None else "verification-after-minus-before",
                "value": value if before is None else str(int(value) - int(before[key]))} for key, value in after.items())
        for checkpoint in row["checkpoints"]:
            tables["checkpoint-memory"].append({**selected, **checkpoint})
        for boundary in ("before_node_memory", "after_shutdown_memory"):
            tables["checkpoint-memory"].append({**selected, "label": boundary, "memory_values": row[boundary]})
        tables["proofs"].extend({**selected, **proof} for proof in row["proofs"])
        attribution = row["allocation_attribution"]
        if attribution is not None:
            witnesses = {item["case"]: item for item in row["allocation_frames"]}
            for case, frame in attribution["frames"].items():
                tables["allocation-frames"].append({**selected, "case": case, "status": attribution["status"],
                    "reason": attribution["reason"], "symbol": frame["symbol"], "witness": witnesses[case],
                    "verified_symbol": attribution["verified_symbols"][case], **frame["counts"],
                    "observed_named_allocation_count": attribution["observed_named_allocation_count"],
                    "unresolved_allocation_count": attribution["unresolved_allocation_count"]})
            tables["allocation-scopes"].append({**selected, "scope": "selected-union", **attribution["union"],
                "temporary_scratch_peak_bytes": attribution["temporary_scratch_peak_bytes"],
                "temporary_scratch_peak_unavailable_reason": attribution["temporary_scratch_peak_unavailable_reason"]})
            tables["allocation-scopes"].append({**selected, "scope": "whole-process", **row["whole_process_allocations"]})
    for pair in aggregate["allocation_pairs"]:
        for scope, values in [*pair["selected"].items(), ("union", pair["union"]), ("whole-process", pair["whole_process"])]:
            tables["allocation-contrasts"].extend(pair_row(pair, metric, value, mode=pair["mode"], scope=scope)
                                                  for metric, value in values.items())
    return tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aggregate", type=Path)
    parser.add_argument("suite", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    aggregate, aggregate_ref = document(args.aggregate)
    suite, suite_ref = document(args.suite)
    qualified(aggregate, suite, suite_ref)
    output = args.output.resolve()
    require(not output.exists() and all(not output.is_relative_to(path.resolve().parent)
            for path in (args.aggregate, args.suite)), "fresh-output-outside-input-roots-required")
    tables = project(aggregate, suite)
    output.mkdir(parents=True, exist_ok=False)
    value = {"schema": "latent.optimization.catalog-mutation-descriptive-report.v1",
             "semantic_replay_performed_by_extractor": False, "inputs": {"aggregate": aggregate_ref, "suite": suite_ref},
             "extractor_sha256": digest(Path(__file__).read_bytes()), "aggregate": aggregate, "tables": tables}
    (output / "report-data.json").write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    for name, rows in tables.items():
        csv_file(output / (name + ".csv"), rows)
    files = [{"path": path.name, "bytes": str(path.stat().st_size), "sha256": digest(path.read_bytes())}
             for path in sorted(output.iterdir())]
    (output / "manifest.json").write_text(json.dumps({"inputs": value["inputs"], "files": files,
        "csv_null": "literal null; nested objects are compact JSON", "qualifying_input": True}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
