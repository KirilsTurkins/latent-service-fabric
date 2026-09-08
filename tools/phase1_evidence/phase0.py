"""Consume retained Phase0 evidence without relabeling mixed populations."""

from decimal import Decimal
from pathlib import Path

from .common import EvidenceError, hash_file, read_json, require
from .statistics import distribution

RETAINED_SHA256 = "sha256:2fd84f8c57e46e538762a8bb41a2df8e19c7494c26f856be95b09f7a978827f8"
WARM_FIELDS = ("backend_setup_micros", "guest_call_micros", "host_call_micros", "host_call_count",
    "component_post_return_micros", "activation_resource_reclamation_micros",
    "outcome_classification_micros", "reusable_proof_micros", "backend_total_micros")


def load_reference(path: Path, runs_directory: Path | None = None):
    document = read_json(path)
    require(isinstance(document, dict) and document.get("schema_version") == "latent.phase0.calibration.v2",
            "unsupported-phase0-reference")
    if runs_directory is None:
        require(hash_file(path)[0] == RETAINED_SHA256, "unverified-phase0-reference-requires-raw-runs")
        return document, "retained-aggregate", {}
    try:
        from tools.aggregate_phase0_calibration import verify_aggregate
    except ImportError:
        from aggregate_phase0_calibration import verify_aggregate
    try:
        verify_aggregate(path, document["source_commit"], document["source_tree"], runs_directory)
    except (ValueError, OSError, KeyError, RuntimeError) as error:
        raise EvidenceError("invalid-phase0-raw-reference") from error
    return document, "raw-reverified", warm_populations(document, runs_directory)


def number(value):
    require(type(value) in (int, float) and value >= 0, "invalid-phase0-number")
    result = Decimal(str(value))
    require(result.is_finite(), "invalid-phase0-number")
    return result


def warm_populations(document, runs_directory):
    """All warm_echo samples in each verified run; no trimming or mixed faults."""
    per_metric = {field: [] for field in WARM_FIELDS}
    for run in document["raw_runs"]:
        # The Phase0 verifier has already validated every named file and run.
        raw = read_json(runs_directory / run["run"] / "raw-results.json", 128 * 1024 * 1024)
        samples = [sample for sample in raw["activation_samples"] if sample["scenario"] == "warm_echo"]
        require(len(samples) == document["reference_identity"]["config"]["warm_samples"], "phase0-warm-population-mismatch")
        for sample in samples:
            require(sample["input_bytes"] == len("phase0 warm echo") and sample["contract_result_valid"] is True,
                    "phase0-warm-input-mismatch")
        for field in WARM_FIELDS:
            values = [number(sample["phase_timings"][field]) for sample in samples]
            per_metric[field].append(Decimal(distribution(values)["median"]))
    return {"warm_echo." + field: {"unit": "count" if field == "host_call_count" else "us",
             "value": distribution(values)["median"]} for field, values in per_metric.items()}
