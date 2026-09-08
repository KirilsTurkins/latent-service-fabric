"""Fixed collection population and receipt shapes shared with offline replay."""
from __future__ import annotations

SCHEMA = "latent.artifact-identity.suite.v1"
PROBE = "tools/optimization-bench/src/bin/artifact-identity-probe.rs"
PROBE_DIRECTORY = "tools/optimization-bench/src/bin/artifact_identity_probe"
BUILD_RECIPE = "source tools/phase0_build_environment.sh; phase0_release_cargo build -p latent-optimization-bench --bin artifact-identity-probe --release --locked"
PAIRED_INPUTS = ("tools/optimization-bench/Cargo.toml", "rust-toolchain.toml",
                 ".cargo/config.toml", "tools/phase0_build_environment.sh")
OPERATIONS = ("hash", "artifact-open", "catalog-open")
MODES = ("normal", "allocation")
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILES = 4096


def plan(profile: str) -> dict:
    if profile not in ("smoke", "full"):
        raise ValueError("invalid-profile")
    return {
        "pairs": 7 if profile == "full" else 1,
        "sizes": ["small", "16m", "64m"] if profile == "full" else ["small"],
        "operations": list(OPERATIONS), "modes": list(MODES),
        "pair_order": "odd-control-candidate-even-candidate-control",
        "hash_iteration_policy": "max-1-min-4096-64m-div-size" if profile == "full" else "one",
        "cache_policy": "best-effort-sequential-64k-read-before-every-child",
        "allocation_required": True, "build_timeout_seconds": 3600,
        "normal_timeout_seconds": 60, "allocation_timeout_seconds": 180,
        "profile_report_timeout_seconds": 120, "suite_timeout_seconds": 7200,
        "maximum_file_bytes": str(MAX_FILE_BYTES),
        "maximum_total_bytes": str(MAX_TOTAL_BYTES), "maximum_files": MAX_FILES,
    }


def suite(profile: str, control_ref: str, candidate_ref: str) -> dict:
    return {
        "schema": SCHEMA, "profile": profile, "plan": plan(profile),
        "requested_refs": {"control": control_ref, "candidate": candidate_ref},
        "status": "failed", "reason": "collection-incomplete", "elapsed_nanos": "0",
        "environment": {}, "tools": {}, "builds": {}, "fixtures": {},
        "runs": [], "artifacts": [], "cleanup": {"owned_worktree_removed": False},
    }


def run_record(pair: int, arm: str, size: str, operation: str, mode: str,
               command: list[str]) -> dict:
    return {
        "pair": pair, "arm": arm, "size": size, "operation": operation, "mode": mode,
        "status": "failed", "reason": "run-incomplete", "command": command,
        "ready": None, "result": None, "process": None, "probe_process": None,
        "resources": None, "cpu": None, "profile_refs": None,
        "log": None, "warmup": None,
    }


def population(profile: str):
    configuration = plan(profile)
    for pair in range(1, configuration["pairs"] + 1):
        arms = ("control", "candidate") if pair % 2 else ("candidate", "control")
        for size in configuration["sizes"]:
            for operation in OPERATIONS:
                for mode in MODES:
                    for arm in arms:
                        yield pair, arm, size, operation, mode
