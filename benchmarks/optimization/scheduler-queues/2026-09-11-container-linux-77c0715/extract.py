"""One-off descriptive report extraction; never collects or replays a workload."""
import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

REFS = {"control": "7ddc41779cd0648a14626b1e558a7bff08ba3fe2",
        "candidate": "77c071550160cb661864c828d825b3fd08cf25f0",
        "harness": "77c071550160cb661864c828d825b3fd08cf25f0"}
CASES = ("closed-one", "saturated-one", "saturated-many", "reference-many", "cancel-one", "cancel-many")
DISTRIBUTIONS = ("scheduling_lag_nanos", "enqueue_to_result_all_nanos", "enqueue_to_result_released_nanos",
                 "observed_hold_nanos", "cancel_to_original_settlement_nanos")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def distribution_columns(value):
    return {name + "." + statistic: None if value[name] is None else value[name][statistic]
            for name in DISTRIBUTIONS for statistic in ("count", "median", "p95", "p99", "maximum")}


def compare_rows(value, prefix=""):
    for key, item in value.items():
        path = prefix + key
        if isinstance(item, dict) and set(item) == {"control", "candidate", "difference", "percent"}:
            before, after = Decimal(item["control"]), Decimal(item["candidate"])
            require(Decimal(item["difference"]) == after - before, "paired difference changed")
            require(item["percent"] is None if before == 0 else Decimal(item["percent"]) == (after - before) * 100 / before,
                    "paired percent changed")
            yield {"metric": path, **item}
        elif isinstance(item, dict):
            yield from compare_rows(item, path + ".")


def extract(path, output):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8 * 1024**2, "aggregate file bound")
    source = path.read_bytes()
    value = json.loads(source)
    require(value["schema"] == "latent.optimization.scheduler-aggregate.v1" and value["profile"] == "full"
            and value["status"] == "complete" and value["source_revisions"] == REFS, "wrong measured population/source")
    require(all(value[key] is True for key in ("completed_paired_run", "full_population_completed", "acceptance_qualified")),
            "full qualified evidence required")
    require(type(value["validated_attempts"]) is int and value["validated_attempts"] == 14
            and (value["logical_offers"], value["load_offers"], value["storm_offers"], value["profile_offers"])
            == ("9128", "8720", "272", "136"), "wrong full denominators")
    expected = []
    for index, case in enumerate(CASES):
        expected.extend((case, "normal", arm) for arm in (("control", "candidate") if index % 2 == 0 else ("candidate", "control")))
    expected.extend(("cancel-many", "allocation", arm) for arm in ("control", "candidate"))
    require([(row["case"], row["mode"], row["variant"]) for row in value["runs"]] == expected, "wrong owner order")
    require(all(row["status"] == "passed" for row in value["runs"]), "failed owner cannot enter report")
    tables = {name: [] for name in ("load", "cancellation", "normal-resources", "allocation", "per-tenant", "paired-differences")}
    for row in value["runs"]:
        summary = row["raw_summary"]
        common = {"case": row["case"], "mode": row["mode"], "variant": row["variant"], "ordinal": row["ordinal"]}
        detail = {**common, **summary["counts"], "measured_offers": summary["measured"]["offers"],
                  **{"measured_" + key: number for key, number in summary["measured"]["outcomes"].items()},
                  "window_nanos": summary["elapsed_nanos"], "offered_per_second": summary["offered_per_second"],
                  "released_per_second": summary["released_per_second"], "scheduler_rejected": summary["scheduler_rejected"],
                  "observed_backlog": summary["observed_backlog"], **distribution_columns(summary["measured"])}
        if row["mode"] == "normal":
            tables["normal-resources"].append({**common, **row["metrics"]})
            if row["case"].startswith("cancel-"):
                frame = summary["frame"]
                tables["cancellation"].append({**detail, "frame_poll_calls": frame["polls"],
                    "frame_elapsed_nanos": str(int(frame["finished_nanos"]) - int(frame["started_nanos"])), **summary["work"]})
            else:
                tables["load"].append({**detail, "warmup_offers": summary["warmup"]["offers"]})
        else:
            selected = row["allocation_attribution"]
            tables["allocation"].append({**common, "status": selected["status"], "reason": selected["reason"],
                "frame_poll_calls": summary["frame"]["polls"], "cancel_calls": summary["frame"]["cancel_calls"],
                "settled": summary["frame"]["settled"], "named_allocation_count": selected["observed_named_allocation_count"],
                "unresolved_allocation_count": selected["unresolved_allocation_count"],
                **{"selected_" + key: number for key, number in selected["statistics"].items()},
                **{key: number for key, number in row["metrics"].items() if key.startswith("whole_process_")}})
        for tenant, observed in summary["per_tenant"].items():
            tables["per-tenant"].append({**common, "tenant": tenant, "offers": observed["offers"],
                                        **observed["outcomes"], **distribution_columns(observed)})
    for pair in value["comparisons"]:
        for section in ("metrics", "raw_summary"):
            for observed in compare_rows(pair[section], section + "."):
                tables["paired-differences"].append({"case": pair["case"], "mode": pair["mode"],
                                                    "order": ",".join(pair["order"]), **observed})
    require(path.read_bytes() == source, "source changed during extraction")
    require(not output.exists() and not output.is_symlink() and not output.resolve().is_relative_to(path.parent.resolve()),
            "output must be fresh and outside the measured root")
    output.mkdir(parents=True)
    document = {"schema": "latent.optimization.scheduler-descriptive-analysis.v1",
                "source_aggregate_sha256": "sha256:" + hashlib.sha256(source).hexdigest(), "source_aggregate_bytes": str(len(source)),
                "source_revisions": REFS, "population": {key: value[key] for key in
                    ("validated_attempts", "logical_offers", "load_offers", "storm_offers", "profile_offers", "collection_elapsed_nanos")},
                "acceptance_evidence": value["acceptance_evidence"], "tables": tables, "runs": value["runs"],
                "comparisons": value["comparisons"], "limitations": value["limitations"]}
    (output / "analysis.json").write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    for name, data in tables.items():
        columns = list(dict.fromkeys(key for row in data for key in row))
        with (output / (name + ".csv")).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows({key: "null" if item is None else item for key, item in row.items()} for row in data)
    require(path.read_bytes() == source, "source changed while writing report")
    print(json.dumps({"status": "extracted", "source_sha256": document["source_aggregate_sha256"],
                      "table_rows": {key: len(rows) for key, rows in tables.items()}}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aggregate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    extract(args.aggregate, args.output)
