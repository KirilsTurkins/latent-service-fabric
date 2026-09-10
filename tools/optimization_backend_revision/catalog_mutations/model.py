"""Finite public catalog mutation owners and their adjacent reopen population."""
from tools.optimization_backend_revision.catalog.model import identity
from tools.optimization_evidence.common import require

SCHEMA = "latent.optimization.catalog-mutation-suite.v1"
BUILD_SCHEMA = "latent.optimization.catalog-mutation-builds.v1"
COLLECTOR = "standalone::measurements::comparison::catalog_mutations::phase1_catalog_mutation_collector"
SHAPES = ("distinct", "shared")
MODES = ("initial", "reopen", "allocation", "allocation-reopen")
MUTATIONS = ("unchanged-apply", "weight-update", "delete", "reapply")
SELECTORS = ("repetition", "variant", "shape", "populated_size", "mode", "sequence_ordinal")
OPERATION_KEYS = ("publications", "seed_batches", "applies", "deletes", "gets", "resolves", "policies", "pins")
MAX_TOTAL_BYTES = 1024**3
MAX_FILES = 4096
MAX_DOCUMENT_BYTES = 32 * 1024**2
MAX_ROW_BYTES = 256 * 1024
MAX_SAMPLES = 2048
MAX_LOG_BYTES = 1024**2
MAX_FOLDED_BYTES = 256 * 1024**2
MAX_PROFILE_RECORDS = 4_000_000
BUILD_SECONDS = 10800
ALLOCATION_SECONDS = 7200
PROFILE_SECONDS = 180
REPORT_SECONDS = 120
SYMBOLS = {case: "latentd::standalone::measurements::comparison::catalog_mutations::frames::" + frame
           for case, frame in (
               ("unchanged-apply", "measured_unchanged_apply_and_drop"),
               ("weight-update", "measured_weight_apply_and_drop"),
               ("delete", "measured_delete_and_drop"),
               ("reapply", "measured_reapply_and_drop"),
               ("reopen", "measured_catalog_reopen"))}


def full(profile):
    require(profile in ("smoke", "full"), "catalog-mutation-profile")
    return profile == "full"


def scales(profile):
    return (100, 1000, 10000) if full(profile) else (4,)


def allocation_size(profile):
    return 8 if full(profile) else 4


def profiled(mode):
    require(mode in MODES, "catalog-mutation-mode")
    return mode in ("allocation", "allocation-reopen")


def is_reopen(mode):
    require(mode in MODES, "catalog-mutation-mode")
    return mode in ("reopen", "allocation-reopen")


def is_initial(mode):
    return not is_reopen(mode)


def variants(size_index, shape):
    require(type(size_index) is int and 0 <= size_index <= 2 and shape in SHAPES,
            "catalog-mutation-order-selection")
    return ("control", "candidate") if (size_index + SHAPES.index(shape)) % 2 == 0 else ("candidate", "control")


def population(profile):
    rows = []
    for sizes, modes in ((scales(profile), ("initial", "reopen")),
                         ((allocation_size(profile),), ("allocation", "allocation-reopen"))):
        for size_index, size in enumerate(sizes):
            for shape in SHAPES:
                for variant in variants(size_index, shape):
                    for mode in modes:
                        rows.append({"repetition": 1, "variant": variant, "shape": shape,
                                     "populated_size": size, "mode": mode, "sequence_ordinal": len(rows)})
    return rows


def counts(profile, mode, shape, populated_size):
    require(mode in MODES and shape in SHAPES and type(populated_size) is int
            and populated_size in ((allocation_size(profile),) if profiled(mode) else scales(profile)),
            "catalog-mutation-population-input")
    if is_reopen(mode):
        operations = dict(zip(OPERATION_KEYS, (0, 0, 0, 0, 1, 2, 2, 1), strict=True))
        measured = 0
    else:
        operations = dict(zip(OPERATION_KEYS,
            (populated_size, 1, 3, 1, 4, 12, 10 + (shape == "shared"), 5), strict=True))
        measured = 4
    return {**operations, "commands": sum(operations.values()), "invokes": 0,
            "measured_mutations": measured, "reopen_observations": int(is_reopen(mode)),
            "warmup_calls": 0, "preflight_calls": 0}


def plan(profile, *, repetition=1, variant="control", shape="distinct", populated_size=None,
         mode="initial", sequence_ordinal=0):
    if populated_size is None:
        populated_size = allocation_size(profile) if profiled(mode) else scales(profile)[0]
    row = {"repetition": repetition, "variant": variant, "shape": shape,
           "populated_size": populated_size, "mode": mode, "sequence_ordinal": sequence_ordinal}
    require(all(type(row[key]) is int for key in ("repetition", "populated_size", "sequence_ordinal"))
            and row in population(profile), "catalog-mutation-owner-selection")
    return {"schema": "latent.optimization.catalog-mutation-plan.v1", "profile": profile, **row}


def group_id(row):
    phase = "allocation" if profiled(row["mode"]) else "normal"
    return f"{phase}-{row['populated_size']:05}-{row['shape']}-{row['variant']}-r{row['repetition']:02}"


def run_id(row):
    return f"owner-{row['sequence_ordinal']:02}-{group_id(row)}-{row['mode']}"


def run_seconds(profile, mode):
    if profiled(mode):
        full(profile)
        return PROFILE_SECONDS
    return (1800 if is_reopen(mode) else 3600) if full(profile) else 90


def normal_seconds(profile):
    return 21600 if full(profile) else 3600


def totals(profile, rows):
    result = {key: 0 for key in counts(profile, "initial", "distinct", scales(profile)[0])}
    for row in rows:
        observed = counts(profile, row["mode"], row["shape"], row["populated_size"])
        for key, amount in observed.items():
            result[key] += amount
    return {**result, "collector_processes": len(rows)}


def suite_plan(profile):
    rows = population(profile)
    return {"schema": "latent.optimization.catalog-mutation-suite-plan.v1", "profile": profile,
            "normal_sizes": list(scales(profile)), "allocation_size": allocation_size(profile),
            "pairs_per_size_shape": 1, "rows": rows, "mutations": list(MUTATIONS),
            "normal_totals": totals(profile, [row for row in rows if not profiled(row["mode"])]),
            "allocation_totals": totals(profile, [row for row in rows if profiled(row["mode"])]),
            "totals": totals(profile, rows),
            "order": "sizes-ascending-shapes-distinct-shared-parity-first-arm-adjacent-reopen",
            "maximum_normal_seconds": str(normal_seconds(profile)),
            "maximum_allocation_seconds": str(ALLOCATION_SECONDS),
            "maximum_artifact_bytes": str(MAX_TOTAL_BYTES), "maximum_artifact_files": MAX_FILES,
            "maximum_folded_expanded_bytes": str(MAX_FOLDED_BYTES),
            "maximum_profile_records": MAX_PROFILE_RECORDS,
            "maximum_document_bytes": str(MAX_DOCUMENT_BYTES), "maximum_row_bytes": str(MAX_ROW_BYTES),
            "maximum_samples": MAX_SAMPLES, "sampler_interval_millis": 100,
            "measured_symbols": SYMBOLS.copy(),
            "normal_boundary": "public-versioned-mutation-future-to-return-before-result-validation-and-drop",
            "reopen_boundary": "actual-artifact-and-deployment-repository-open",
            "allocation_boundary": "actual-async-mutation-poll-and-owned-result-drop",
            "allocation_reopen_boundary": "actual-repository-open-with-catalog-retained-through-node-shutdown"}
