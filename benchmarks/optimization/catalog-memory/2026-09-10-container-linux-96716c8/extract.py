#!/usr/bin/env python3
"""Extract descriptive #107 tables after semantic replay; never run workloads."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

CONTROL = "397ee901ee919ae538d2a964d1543169bb740926"
CANDIDATE = "96716c8468e90246c59c6282d401c0f5402d0dda"
MAX_INPUT_BYTES = 8 * 1024**2
MAX_OUTPUT_BYTES = 32 * 1024**2
SHAPES = ("distinct", "shared")
CASES = ("default-success", "named-success", "route-miss", "export-miss")
MEMORY = ("rss_bytes", "pss_bytes", "private_clean_bytes", "private_dirty_bytes", "shared_clean_bytes",
          "shared_dirty_bytes", "vm_size_bytes", "vm_peak_bytes", "vm_hwm_bytes")
ALLOCATION = ("allocation_count", "allocated_bytes", "peak_live_bytes", "remaining_allocations", "live_bytes")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def unsupported_number(value):
    raise ValueError("unplanned floating-point or nonfinite JSON number: " + value)


def digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def qualify(value):
    require(value["schema"] == "latent.optimization.catalog-aggregate.v1" and value["profile"] == "full"
            and value["status"] == "complete", "qualified full catalog aggregate required")
    require(all(value[key] is True for key in ("population_complete", "attempt_count_complete", "qualifying_full_population")),
            "full population flags required")
    for key, expected in {"validated_collectors": "24", "planned_collectors": "24", "validated_commands": "596720",
                          "validated_resolves": "196396", "validated_invocations": "0"}.items():
        require(value[key] == expected, "crossed full population: " + key)
    for variant, commit in (("control", CONTROL), ("candidate", CANDIDATE)):
        require(value["sources"][variant]["commit"] == commit and value["sources"][variant]["clean"] is True,
                "crossed or dirty measured source")
    plan = value["plan"]
    require(plan["profile"] == "full" and plan["normal_pairs_per_shape"] == 1
            and plan["maximum_folded_expanded_bytes"] == "268435456"
            and plan["maximum_artifact_bytes"] == "1073741824", "crossed fixed catalog plan")
    require(plan["totals"]["collector_processes"] == 24 and plan["totals"]["measured_resolves"] == 196096
            and plan["totals"]["warmup_resolves"] == 256 and plan["totals"]["preflight_resolves"] == 16,
            "crossed fixed resolve denominators")
    require(len(value["runs"]) == 24 and len(value["normal_pairs"]) == 2 and len(value["allocation_pairs"]) == 8,
            "missing report populations")
    expected = {(shape, variant, mode, None) for shape in SHAPES for variant in ("control", "candidate")
                for mode in ("initial", "reopen")}
    expected.update((shape, variant, "allocation", case) for shape in SHAPES for variant in ("control", "candidate") for case in CASES)
    seen = set()
    for index, row in enumerate(value["runs"]):
        key = (row["shape"], row["variant"], row["mode"], row["case"])
        require(key in expected and key not in seen and type(row["sequence_ordinal"]) is int
                and row["sequence_ordinal"] == index and type(row["repetition"]) is int and row["repetition"] == 1,
                "crossed or duplicated report owner")
        seen.add(key)
        require(row["status"] == "passed" and row["attempt_count_complete"] is True and row["validated_invocations"] == "0"
                and row["source"]["commit"] == (CONTROL if row["variant"] == "control" else CANDIDATE)
                and row["source"]["dirty"] is False, "unqualified report owner")
        commands, resolves = {"initial": ("148013", "48003"), "reopen": ("7", "4"), "allocation": ("290", "273")}[row["mode"]]
        require(row["validated_commands"] == commands and row["validated_resolves"] == resolves, "crossed per-owner denominator")
    require(seen == expected, "missing report owner")
    require({row["shape"] for row in value["normal_pairs"]} == set(SHAPES), "crossed normal contrasts")
    require({(row["shape"], row["case"]) for row in value["allocation_pairs"]} == {(s, c) for s in SHAPES for c in CASES},
            "crossed allocation contrasts")
    for pair in (*value["normal_pairs"], *value["allocation_pairs"]):
        require(pair["order"] == (["control", "candidate"] if pair["shape"] == "distinct" else ["candidate", "control"]),
                "crossed actual shape order")
    require(isinstance(value["targets"], dict), "missing observed targets")


def run_key(row):
    return {key: row[key] for key in ("sequence_ordinal", "repetition", "shape", "variant", "mode", "case")}


def metric_unit(key):
    if key.endswith("_bytes"):
        return "bytes"
    if key.endswith("_nanos"):
        return "ns"
    if key.endswith("cpu_ticks"):
        return "process CPU ticks; clock rate requires matching suite host receipt"
    raise ValueError("unknown report metric unit: " + key)


def allocation_unit(key):
    return "allocations" if key in ("allocation_count", "remaining_allocations") else "bytes"


def tables(value):
    output = {name: [] for name in ("normal-contrasts", "checkpoint-memory", "boundary-memory", "apply-samples",
        "resolver-distributions", "run-costs", "source-sampler", "pin-policy-proofs", "allocation-contrasts",
        "allocation-arms", "target-observations", "ownership-and-verification")}
    for pair in value["normal_pairs"]:
        for name, metric in pair["metrics"].items():
            output["normal-contrasts"].append({"shape": pair["shape"], "repetition": pair["repetition"], "order": pair["order"],
                "metric": name, "unit": metric_unit(name), **metric, "percent_unit": "percent candidate-minus-control/control"})
    for row in value["runs"]:
        identity = run_key(row)
        for checkpoint in row["checkpoints"]:
            for metric in MEMORY:
                observed = checkpoint["memory"][metric]
                output["checkpoint-memory"].append({**identity, "catalog_count": checkpoint["count"],
                    "checkpoint": checkpoint["label"], "old_pin": checkpoint["old_pin"], "metric": metric,
                    "value": observed, "unit": "bytes", "availability": "unavailable" if observed is None else "observed"})
        for phase in ("before_node_memory", "after_shutdown_memory"):
            for metric in MEMORY:
                output["boundary-memory"].append({**identity, "boundary": phase, "metric": metric,
                                                   "value": row[phase][metric], "unit": "bytes"})
        for operation in row["applies"]:
            growth = operation["mode"] == "growth"
            count = str(int(operation["first"]) + int(operation["count"])) if growth else operation["catalog_count"]
            sampled = operation["sampled_memory"]
            output["apply-samples"].append({**identity, "operation": operation["mode"], "catalog_count": count,
                "growth_first": operation["first"] if growth else None, "growth_delta_count": operation["count"] if growth else None,
                "started_nanos": operation["started_nanos"], "finished_nanos": operation["finished_nanos"],
                "elapsed_nanos": str(int(operation["finished_nanos"]) - int(operation["started_nanos"])),
                "sample_count": sampled["sample_count"] if sampled is not None else None,
                "rss_max_bytes": sampled["rss_max_bytes"] if sampled is not None else None,
                "vm_hwm_max_bytes": sampled["vm_hwm_max_bytes"] if sampled is not None else None,
                "sampling_scope": sampled["scope"] if sampled is not None else None})
        for case in row["resolves"]:
            for scope in ("elapsed_nanos", "chunk_elapsed_nanos"):
                for statistic, number in case[scope].items():
                    output["resolver-distributions"].append({**identity, "resolver_case": case["case"], "catalog_count": case["count"],
                        "attempts": case["attempts"], "returned_ok": case["returned_ok"], "returned_error": case["returned_error"],
                        "distribution": scope, "statistic": statistic, "value": number,
                        "unit": "samples" if statistic == "count" else "ns", "call_boundary": case["boundary"]})
        for metric, number in row["metrics"].items():
            if metric.startswith("startup.") or metric == "population_and_observation.cpu_ticks":
                output["run-costs"].append({**identity, "metric": metric, "value": number, "unit": metric_unit(metric),
                    "process_scope": "Heaptrack-instrumented allocation child" if row["mode"] == "allocation" else "normal initial/reopen child",
                    "clock_rate": None, "clock_rate_note": "not retained in aggregate; use matching suite host_before.clock_ticks_per_second"})
        output["source-sampler"].append({**identity, **row["sampler"]})
        for proof in row["proofs"]:
            output["pin-policy-proofs"].append({**identity, **proof,
                "elapsed_nanos": str(int(proof["finished_nanos"]) - int(proof["started_nanos"]))})
        output["ownership-and-verification"].append({**identity, "operations": row["operations"], "final_verification": row["final_verification"],
            "shutdown": row["shutdown"], "data_identity": row["data_identity"], "process_identity": row["process_identity"],
            "effective_engine": row["effective_engine"], "source": row["source"], "binary": row["binary"]})
        if row["mode"] == "allocation":
            selected = row["allocation_attribution"]
            require(selected["contained_calls"] == "256" and selected["frame_invocations"] == "1", "crossed allocation frame boundary")
            for scope in ("selected", "whole_process"):
                for metric in ALLOCATION:
                    number = selected["counts"][metric] if scope == "selected" else row["whole_process_allocations"][
                        "remaining_live_bytes" if metric == "live_bytes" else metric]
                    output["allocation-arms"].append({**identity, "scope": scope, "metric": metric, "value": number,
                        "unit": allocation_unit(metric), "selected_status": selected["status"], "selected_reason": selected["reason"],
                        "frame_invocations": selected["frame_invocations"], "contained_calls": selected["contained_calls"],
                        "per_operation": selected["per_operation"][metric] if scope == "selected" and metric in ("allocation_count", "allocated_bytes") else None,
                        "observed_named_allocation_count": selected["observed_named_allocation_count"],
                        "unresolved_allocation_count": selected["unresolved_allocation_count"], "peak_scope": selected["peak_scope"]})
    for pair in value["allocation_pairs"]:
        for scope in ("selected", "whole_process"):
            for metric in ALLOCATION:
                output["allocation-contrasts"].append({"shape": pair["shape"], "case": pair["case"], "order": pair["order"],
                    "measured_calls_per_child": pair["measured_calls_per_child"], "scope": scope, "metric": metric,
                    "unit": allocation_unit(metric), **pair[scope][metric], "percent_unit": "percent candidate-minus-control/control"})
    for key, number in value["targets"].items():
        output["target-observations"].append({"field": key, "value": number,
            "unit": "bytes" if key.endswith("_bytes") else "percent" if key.endswith("_percent") else "boolean" if key.endswith("_met") else "scope"})
    return output


def csv_bytes(rows):
    names = list(dict.fromkeys(key for row in rows for key in row))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: (item if isinstance(item, str) else json.dumps(item, sort_keys=True, separators=(",", ":")))
                         for key, item in row.items()})
    return stream.getvalue().encode("utf-8")


def extract(aggregate_path, output_path):
    aggregate_path, output_path = Path(aggregate_path).resolve(strict=True), Path(output_path).resolve()
    require(aggregate_path.is_file() and not output_path.exists(), "regular aggregate and new output directory required")
    require(not output_path.is_relative_to(aggregate_path.parent) and not aggregate_path.is_relative_to(output_path),
            "report output must be outside the measured evidence directory")
    require(0 < aggregate_path.stat().st_size <= MAX_INPUT_BYTES, "bounded aggregate required")
    body = aggregate_path.read_bytes()
    require(len(body) <= MAX_INPUT_BYTES, "aggregate grew beyond bound")
    value = json.loads(body, object_pairs_hook=unique_object, parse_float=unsupported_number, parse_constant=unsupported_number)
    qualify(value)
    extracted = tables(value)
    companion = {"schema": "latent.optimization.catalog-descriptive-report.v1",
        "input": {"name": aggregate_path.name, "bytes": str(len(body)), "sha256": digest(body)},
        "extractor_sha256": digest(Path(__file__).read_bytes()),
        "validation_scope": "qualified-aggregate-selection-and-table-extraction; semantic-replay-required-separately",
        "numeric_policy": "preserve source strings and nulls; no rounded values, estimated clock rate or substituted zeros",
        "csv_policy": "literal null means JSON null; blank means absent field; decimal strings are unrounded; objects/lists remain compact JSON",
        "limitations": ["one full pair per shape; shape and order confounded", "normal return boundary excludes validation and Drop",
            "fixed100ms sampler may miss peaks; lifetime high-water differs from apply-local RSS", "null memory reasons require original raw checkpoint",
            "process CPU tick frequency requires matching suite host receipt", "sixteen-release profiles are not100k allocation measurements",
            "selected peaks are not divided by contained calls; unavailable attribution remains null"],
        "aggregate": value, "tables": extracted}
    outputs = {"report-data.json": (json.dumps(companion, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")}
    outputs.update({name + ".csv": csv_bytes(rows) for name, rows in extracted.items()})
    require(sum(map(len, outputs.values())) <= MAX_OUTPUT_BYTES, "report output exceeds bounded size")
    require(aggregate_path.read_bytes() == body, "aggregate changed during extraction")
    output_path.mkdir(parents=True, exist_ok=False)
    for name, encoded in outputs.items():
        with (output_path / name).open("xb") as destination:
            destination.write(encoded)
    manifest = {"schema": "latent.optimization.catalog-report-files.v1", "input": companion["input"],
        "files": [{"path": name, "bytes": str(len(encoded)), "sha256": digest(encoded)} for name, encoded in outputs.items()],
        "table_rows": {name: len(rows) for name, rows in extracted.items()}}
    with (output_path / "manifest.json").open("x", encoding="utf-8", newline="\n") as destination:
        json.dump(manifest, destination, indent=2)
        destination.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aggregate", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    try:
        result = extract(args.aggregate, args.output_directory)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"Catalog report extraction rejected: {error}\n")
    print(json.dumps({"input": result["input"], "files": len(result["files"]), "table_rows": result["table_rows"]}))


if __name__ == "__main__":
    main()
