"""Closed catalog populations, including every pin/reopen and profiler call."""
from tools.optimization_evidence.common import require

SCHEMA = "latent.optimization.catalog-suite.v1"
BUILD_SCHEMA = "latent.optimization.catalog-builds.v1"
COLLECTOR = "standalone::measurements::comparison::catalog::phase1_catalog_collector"
SHAPES = ("distinct", "shared")
CASES = ("default-success", "named-success", "route-miss", "export-miss")
SELECTORS = ("repetition", "variant", "shape", "mode", "sequence_ordinal", "case")
MAX_TOTAL_BYTES = 1024**3
MAX_FILES = 4096
MAX_DOCUMENT_BYTES = 32 * 1024**2
MAX_ROW_BYTES = 256 * 1024
MAX_SAMPLES = 2048
MAX_LOG_BYTES = 1024**2
BUILD_SECONDS = 10800
ALLOCATION_SECONDS = 7200
PROFILE_SECONDS = 180
REPORT_SECONDS = 120
SYMBOLS = {
    case: "latentd::standalone::measurements::comparison::catalog::frames::measured_"
          + case.replace("-", "_") + "_and_drop"
    for case in CASES
}


def full(profile):
    require(profile in ("smoke", "full"), "catalog-profile")
    return profile == "full"


def repetitions(profile):
    return 1 if full(profile) else 3


def scales(profile):
    return (100, 1000, 10000, 100000) if full(profile) else (2, 4, 16)


def case_counts(profile):
    return dict(zip(CASES, (5000, 5000, 1000, 1000) if full(profile) else (32, 32, 64, 64), strict=True))


def variants(shape):
    require(shape in SHAPES, "catalog-shape")
    return ("control", "candidate") if shape == "distinct" else ("candidate", "control")


def population(profile):
    rows = []
    for repetition in range(1, repetitions(profile) + 1):
        for shape in SHAPES:
            for variant in variants(shape):
                for mode in ("initial", "reopen"):
                    rows.append({"repetition": repetition, "variant": variant, "shape": shape,
                                 "mode": mode, "sequence_ordinal": len(rows), "case": None})
    for shape in SHAPES:
        for case in CASES:
            for variant in variants(shape):
                rows.append({"repetition": 1, "variant": variant, "shape": shape, "mode": "allocation",
                             "sequence_ordinal": len(rows), "case": case})
    return rows


def counts(profile, mode):
    require(mode in ("initial", "reopen", "allocation"), "catalog-mode")
    is_full = full(profile)
    if mode == "initial":
        timed = len(scales(profile)) * sum(case_counts(profile).values())
        publications, applies, resolves, policies, pins = scales(profile)[-1], len(scales(profile)) + 1, timed + 3, 3, 2
        warmup = preflight = 0
    elif mode == "reopen":
        publications, applies, resolves, policies, pins = 0, 0, 4, 2, 1
        timed = warmup = preflight = 0
    else:
        timed, warmup, preflight = 256 if is_full else 64, 16, 1
        publications, applies, resolves, policies, pins = 16, 1, timed + warmup + preflight, 0, 0
    return {"invokes": 0, "commands": publications + applies + resolves + policies + pins,
            "publications": publications, "applies": applies, "resolves": resolves,
            "policies": policies, "pins": pins, "measured_resolves": timed,
            "warmup_resolves": warmup, "preflight_resolves": preflight}


def run_seconds(profile, mode):
    require(mode in ("initial", "reopen", "allocation"), "catalog-mode")
    if mode == "allocation":
        full(profile)
        return PROFILE_SECONDS
    return {"initial": 3600, "reopen": 1800}[mode] if full(profile) else 90


def normal_seconds(profile):
    return 21600 if full(profile) else 3600


def plan(profile, *, repetition=1, variant="control", shape="distinct", mode="initial",
         sequence_ordinal=0, case=None):
    row = {"repetition": repetition, "variant": variant, "shape": shape, "mode": mode,
           "sequence_ordinal": sequence_ordinal, "case": case}
    require(type(repetition) is int and type(sequence_ordinal) is int and row in population(profile),
            "catalog-owner-selection")
    return {"schema": "latent.optimization.catalog-plan.v1", "profile": profile, **row}


def group_id(row):
    return f"pair-{row['repetition']:02}-{row['shape']}-{row['variant']}"


def run_id(row):
    suffix = row["mode"] if row["case"] is None else "allocation-" + row["case"]
    return f"owner-{row['sequence_ordinal']:02}-{group_id(row)}-{suffix}"


def suite_plan(profile):
    rows = population(profile)
    totals = {key: sum(counts(profile, row["mode"])[key] for row in rows)
              for key in counts(profile, "initial")}
    return {"schema": "latent.optimization.catalog-suite-plan.v1", "profile": profile,
            "normal_pairs_per_shape": repetitions(profile), "rows": rows,
            "scales": list(scales(profile)), "cases_per_checkpoint": case_counts(profile),
            "per_owner": {mode: counts(profile, mode) for mode in ("initial", "reopen", "allocation")},
            "totals": {**totals, "collector_processes": len(rows)},
            "order": "distinct-control-first-shared-candidate-first-initial-reopen-adjacent",
            "maximum_normal_seconds": str(normal_seconds(profile)),
            "maximum_allocation_seconds": str(ALLOCATION_SECONDS),
            "maximum_artifact_bytes": str(MAX_TOTAL_BYTES), "maximum_artifact_files": MAX_FILES,
            "maximum_document_bytes": str(MAX_DOCUMENT_BYTES), "maximum_row_bytes": str(MAX_ROW_BYTES),
            "maximum_samples": MAX_SAMPLES, "sampler_interval_millis": 100,
            "measured_symbols": SYMBOLS.copy(), "allocation_frame_invocations": 1,
            "normal_boundary": "directory-deployment-resolver.resolve-to-return-before-validation-and-drop",
            "allocation_boundary": "public-resolve-and-result-drop-batch"}


def identity(build, variant, environment):
    require(variant in ("control", "candidate"), "catalog-identity-variant")
    source = build["builds"][variant]["source"]
    binary = build["builds"][variant]["executables"]["backend"]
    echo = build["harness"]["echo"]["component"]
    return {"schema": "latent.phase1.measurement-identity.v1",
            "source": {**{key: source[key] for key in ("commit", "tree", "cargo_lock_sha256")}, "dirty": False},
            "build": build["build"], "environment": environment,
            "binary": {key: binary[key] for key in ("sha256", "bytes")},
            "fixtures": [{"name": "echo", **{key: echo[key] for key in ("sha256", "bytes")}}]}
