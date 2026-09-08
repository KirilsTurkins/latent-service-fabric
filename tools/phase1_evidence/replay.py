"""Recompute a retained aggregate from every declared attempted run."""

from pathlib import Path

from .aggregate import aggregate_suites
from .common import canonical, read_json, require, verify_artifact


def validate_aggregate(path: Path):
    path = path.resolve()
    retained = read_json(path)
    require(isinstance(retained, dict) and retained.get("schema") == "latent.phase1.measurement-aggregate.v1",
            "invalid-aggregate-schema")
    sources = retained.get("sources")
    require(isinstance(sources, list) and 1 <= len(sources) <= 16, "missing-aggregate-sources")
    paths = [verify_artifact(path.parent, reference) for reference in sources]
    regenerated = aggregate_suites(paths, path.parent)
    require(canonical(regenerated) == canonical(retained), "aggregate-does-not-match-raw-evidence")
    return regenerated


def validate_comparison(path: Path, phase0_runs: Path | None = None):
    from .comparison import compare
    from .phase0 import load_reference
    path = path.resolve()
    retained = read_json(path)
    require(isinstance(retained, dict) and retained.get("schema") == "latent.phase1.measurement-comparison.v1",
            "invalid-comparison-schema")
    candidate_path = verify_artifact(path.parent, retained.get("candidate"))
    reference_path = verify_artifact(path.parent, retained.get("reference"))
    candidate = validate_aggregate(candidate_path)
    prior, validation, warm = load_reference(reference_path, phase0_runs)
    regenerated = {"schema": "latent.phase1.measurement-comparison.v1", "phase1_completion": "incomplete",
                   "observational_only": True, "candidate": retained["candidate"], "reference": retained["reference"],
                   "reference_validation": validation, **compare(candidate, prior, warm)}
    require(canonical(regenerated) == canonical(retained), "comparison-does-not-match-evidence")
    return regenerated
