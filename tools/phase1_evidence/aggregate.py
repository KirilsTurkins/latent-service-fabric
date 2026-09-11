"""Aggregate compatible repetitions without hiding failures or mixing machines."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from .common import KINDS, PREFIX, REPETITIONS, canonical, reference, require, sha256
from .statistics import distribution
from .suite import validate_suite
from .policy import policy


def comparison_identity(identity: dict[str, Any]) -> dict[str, Any]:
    # Load is an observation rather than a machine identity; retain it in each
    # raw header, but do not require two independent runs to have identical load.
    environment = {key: value for key, value in identity["environment"].items() if key != "load_before"}
    return {"source": identity["source"], "build": identity["build"], "environment": environment,
            "binary": identity["binary"], "fixtures": identity["fixtures"]}


def aggregate_suites(paths: list[Path], root: Path) -> dict[str, Any]:
    require(1 <= len(paths) <= 16 and len(set(path.resolve() for path in paths)) == len(paths), "invalid-suite-selection")
    sources = []
    runs = []
    profiles = set()
    per_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_attempts = set()
    for path in paths:
        validated = validate_suite(path)
        document = validated["document"]
        profiles.add(document["profile"])
        source = reference(path, root)
        sources.append(source)
        identity = document["identity"]
        for record in validated["runs"]:
            attempt, raw = record["attempt"], record["raw"]
            key = attempt["kind"], attempt["repetition"]
            require(key not in seen_attempts, "duplicate-attempt-across-suites")
            seen_attempts.add(key)
            entry = {"kind": key[0], "repetition": key[1], "status": attempt["status"],
                     "reason": attempt["reason"], "validation_error": record["validation_error"],
                     "suite": source["path"], "identity": record["identity"],
                     "host_observations": record["host_observations"],
                     "config": raw["header"]["config"] if raw else None,
                     "metrics": raw["metrics"] if raw else [],
                     "reclamation": raw.get("reclamation") if raw else None,
                     "benchmark_input": raw.get("benchmark_input") if raw else None,
                     "throughput": raw.get("throughput") if raw else None,
                     "summary": raw["summary"] if raw else None,
                     "raw": reference(path.parent / attempt["report"]["path"], root) if attempt["report"] else None}
            runs.append(entry)
            per_kind[key[0]].append(entry)
    require(len(profiles) == 1, "cannot-mix-smoke-and-full")
    profile = profiles.pop()
    groups = {}
    for kind in KINDS:
        selected = sorted(per_kind[kind], key=lambda entry: entry["repetition"])
        expected = 1 if profile == "smoke" else REPETITIONS[kind]
        reasons = []
        if len(selected) < expected or [entry["repetition"] for entry in selected] != list(range(1, len(selected) + 1)):
            reasons.append("missing-required-repetitions")
        if any(entry["status"] != "passed" or entry["validation_error"] for entry in selected):
            reasons.append("failed-attempt")
        compatible = {sha256(canonical(comparison_identity(entry["identity"]))) for entry in selected}
        configs = {sha256(canonical(entry["config"])) for entry in selected if entry["config"] is not None}
        if len(compatible) > 1 or len(configs) > 1:
            reasons.append("incompatible-run-identities")
        if kind == "benchmark" and len({sha256(canonical(entry["benchmark_input"]))
                                        for entry in selected if entry["benchmark_input"] is not None}) > 1:
            reasons.append("incompatible-benchmark-inputs")
        if kind == "benchmark" and any(entry["identity"]["source"]["dirty"] for entry in selected):
            reasons.append("dirty-calibration-source")
        if kind == "benchmark" and any(entry["host_observations"] is not None
                                       and not entry["host_observations"]["stable_identity"] for entry in selected):
            reasons.append("host-identity-changed-during-run")
        metrics = []
        if selected and not reasons:
            series: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
            expected_names = None
            for entry in selected:
                names = {(metric["name"], metric["boundary"], metric["unit"]) for metric in entry["metrics"]}
                if expected_names is None:
                    expected_names = names
                require(names == expected_names, "repetition-metric-set-mismatch")
                for metric in entry["metrics"]:
                    series[(metric["name"], metric["boundary"], metric["unit"])].append(
                        {"repetition": entry["repetition"], "value": metric["statistics"]["median"]})
            for (name, boundary, unit), representatives in sorted(series.items()):
                metrics.append({"name": name, "boundary": boundary, "unit": unit,
                                "representatives": representatives,
                                "statistics": distribution([Decimal(item["value"]) for item in representatives])})
        groups[kind] = {"status": "passed" if not reasons else ("failed" if "failed-attempt" in reasons else "incomplete"),
                        "required_runs": expected, "attempted_runs": len(selected), "reasons": reasons,
                        "metrics": metrics}
    return {"schema": PREFIX + "aggregate.v1", "profile": profile,
            "status": "complete" if profile == "full" and all(value["status"] == "passed" for value in groups.values()) else "incomplete",
            "phase1_completion": "incomplete", "observational_only": True,
            "policy": policy(),
            "statistic": "median-of-all-per-run-medians; nearest-rank-percentiles; no-outlier-removal",
            "sources": sorted(sources, key=lambda item: item["path"]),
            "runs": sorted(runs, key=lambda item: (item["kind"], item["repetition"])), "kinds": groups}
