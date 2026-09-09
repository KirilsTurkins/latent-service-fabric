"""Fixed codec-only operations and independently reconstructible input bytes."""
from tools.optimization_evidence.common import require
from .fixtures import fixtures

COLLECTOR = "values::tests::measurement::codec_collector"
SYMBOLS = ("latent_wasmtime::values::tests::measurement::measured_decode_and_drop",
           "latent_wasmtime::values::tests::measurement::measured_encode_and_drop")
FAMILIES = ("scalar-params", "byte-list", "nested-record", "string-64k", "string-near-limit", "escaped-unicode")
SCHEMA = "latent.optimization.codec-suite.v1"
TYPE_FIXTURE = "crates/latent-wasmtime/src/values/types.wasm"
MAX_DOCUMENT_BYTES, MAX_FOLDED_BYTES = 8 * 1024**2, 128 * 1024**2
MAX_TOTAL_BYTES, MAX_FILES, STAGE_SECONDS = 1024**3, 4096, 7200
LIMITS = dict(max_input_bytes=1024**2, max_output_bytes=1024**2, max_depth=32,
              max_nodes=16384, max_string_bytes=256*1024, max_collection_items=4096,
              max_type_nodes=4096, max_type_name_bytes=256, max_lifted_bytes=16*1024**2,
              max_decoded_value_bytes=16*1024**2)


def plan(profile, repetition=1, variant="control", mode="normal", family="scalar-params"):
    require(profile in ("smoke", "full") and variant in ("control", "candidate"), "codec-plan-selection")
    require(type(repetition) is int and 1 <= repetition <= (7 if profile == "full" else 1), "codec-plan-repetition")
    require(mode in ("normal", "allocation") and family in FAMILIES, "codec-plan-family-or-mode")
    source, expected, _ = fixtures()[family]
    measured = max(4, min(4096, MAX_DOCUMENT_BYTES // max(len(source), len(expected), 1))) if profile == "full" else 4
    return {"schema": "latent.optimization.codec-plan.v1", "profile": profile, "repetition": repetition,
            "variant": variant, "mode": mode, "family": family, "warmup_iterations": 20 if profile == "full" else 2,
            "measured_iterations": measured, "observation_hold_millis": 100, "maximum_output_bytes": str(MAX_DOCUMENT_BYTES)}


def suite_plan(profile):
    plan(profile)
    return {"schema": "latent.optimization.codec-population.v1", "profile": profile,
            "pairs": 7 if profile == "full" else 1, "families": list(FAMILIES), "modes": ["normal", "allocation"],
            "family_plans": [plan(profile, family=family) for family in FAMILIES],
            "pair_order": "odd-control-candidate-even-candidate-control",
            "maximum_run_seconds": str(STAGE_SECONDS), "maximum_artifact_bytes": str(MAX_TOTAL_BYTES),
            "maximum_artifact_files": MAX_FILES, "maximum_folded_expanded_bytes": str(MAX_FOLDED_BYTES),
            "normal_timeout_seconds": 90, "allocation_timeout_seconds": 180, "extraction_timeout_seconds": 120,
            "symbols": list(SYMBOLS), "boundary": "separate-actual-codec-and-result-drop-batches-no-guest-invocation"}


def population(profile):
    for repetition in range(1, suite_plan(profile)["pairs"] + 1):
        arms = ("control", "candidate") if repetition % 2 else ("candidate", "control")
        for family in FAMILIES:
            for mode in ("normal", "allocation"):
                for variant in arms:
                    yield repetition, variant, mode, family
