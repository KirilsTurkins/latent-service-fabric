"""Exact population replay and paired summaries for artifact optimization."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from tools.artifact_identity_runner.model import SCHEMA, plan
from .common import ARMS, Artifacts, canonical, distribution, fields, read_json, require, sha256, uint
from .identity import build_rows, environment, fixtures
from .runs import run


def population(profile):
    expected = []
    preset = plan(profile)
    for pair in range(1, preset["pairs"] + 1):
        arms = ARMS if pair % 2 else tuple(reversed(ARMS))
        for size in preset["sizes"]:
            for operation in preset["operations"]:
                for mode in preset["modes"]:
                    expected.extend((pair, arm, size, operation, mode) for arm in arms)
    return expected


def summarize(observations):
    groups = defaultdict(dict)
    for key, metrics in observations:
        pair, arm, size, operation, mode = key
        for metric, value in metrics.items():
            groups[(size, operation, mode, metric)].setdefault(pair, {})[arm] = Decimal(value)
    result = []
    for (size, operation, mode, metric), pairs in sorted(groups.items()):
        require(all(set(arms) == set(ARMS) for arms in pairs.values()), "unpaired-metric")
        result.append({
            "size": size, "operation": operation, "mode": mode, "metric": metric,
            "control": distribution([arms["control"] for arms in pairs.values()]),
            "candidate": distribution([arms["candidate"] for arms in pairs.values()]),
            "paired_candidate_minus_control": distribution([arms["candidate"] - arms["control"] for arms in pairs.values()]),
        })
    return result


def validate_suite(path: Path):
    path = Path(path)
    suite = read_json(path)
    fields(suite, "schema profile plan requested_refs status reason elapsed_nanos environment tools builds fixtures runs artifacts cleanup")
    require(suite["schema"] == SCHEMA and suite["profile"] in ("smoke", "full"), "invalid-suite-schema")
    require(canonical(suite["plan"]) == canonical(plan(suite["profile"])), "changed-benchmark-population")
    require(suite["status"] == "passed" and suite["reason"] is None, "collection-did-not-pass")
    require(0 < uint(suite["elapsed_nanos"]) <= suite["plan"]["suite_timeout_seconds"] * 1_000_000_000,
            "collection-duration-bound")
    artifacts = Artifacts(path.parent, suite["artifacts"])
    require("suite.json" not in artifacts.rows and "aggregate.json" not in artifacts.rows, "self-referencing-artifact")
    environment(suite["environment"], suite["tools"])
    build_rows(suite, artifacts)
    configuration = fixtures(suite, artifacts)
    fields(suite["cleanup"], "owned_worktree_removed")
    require(suite["cleanup"]["owned_worktree_removed"] is True, "owned-worktree-not-removed")
    expected = population(suite["profile"])
    require(isinstance(suite["runs"], list) and len(suite["runs"]) == len(expected), "incomplete-run-population")
    observations, identities = [], set()
    for key, record in zip(expected, suite["runs"], strict=True):
        require(tuple(record.get(name) for name in ("pair", "arm", "size", "operation", "mode")) == key,
                "changed-run-order-or-population")
        identity, metrics = run(record, suite, artifacts)
        require(identity not in identities, "reused-probe-process")
        identities.add(identity)
        observations.append((key, metrics))
    return {
        "schema": "latent.artifact-identity.aggregate.v1", "profile": suite["profile"],
        "status": "passed", "suite_sha256": sha256(canonical(suite)),
        "population_complete": True, "full_comparison_qualified": suite["profile"] == "full",
        "validated_runs": str(len(observations)), "pairs": str(suite["plan"]["pairs"]),
        "sources": {arm: suite["builds"][arm]["source_before"] for arm in ARMS},
        "fixture_configuration": configuration, "statistics": summarize(observations),
        "boundaries": {
            "timing": "normal timed operation divided by declared operation count; seven process-level samples in full, not individual-invocation tails",
            "cpu": "normal whole-process user plus system rusage, including startup/input/oracles/cleanup; no operation-only CPU claim",
            "rss": "normal whole-process kernel VmHWM and separately maximum observed RSS; includes input buffers and libraries",
            "allocation": "separate Heaptrack-instrumented whole process; interpreted exact allocation events cross-checked against folded totals",
            "remaining_allocations": "raw live at process exit, without leak suppressions; not an inferred leak finding",
            "cache": suite["plan"]["cache_policy"],
            "cgroup": "shared runner cgroup; counters are context, not attributed per-probe usage",
        },
    }
