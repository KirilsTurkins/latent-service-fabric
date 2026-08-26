#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
if [[ "${TARGET_ROOT}" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi

MODE="${1:-full}"
OUTPUT_DIR="${2:-${TARGET_ROOT}/phase0-gate/${MODE}}"
if [[ "${OUTPUT_DIR}" != /* ]]; then
    OUTPUT_DIR="${ROOT}/${OUTPUT_DIR}"
fi

case "${MODE}" in
    smoke|full) ;;
    *)
        echo "usage: $0 [smoke|full] [output-directory]" >&2
        exit 64
        ;;
esac

for command in cargo python3 wasm-tools buf; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        echo "required Phase 0 gate command is unavailable: ${command}" >&2
        exit 69
    fi
done

cd "${ROOT}"
rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

echo "==> Phase 0 gate: repository Rust checks"
cargo fmt --all --check
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked
cargo test --workspace --all-targets --all-features --locked

echo "==> Phase 0 gate: executable spike and containment E2E"
tools/run_phase0_spike.sh

echo "==> Phase 0 gate: ${MODE} resource and containment baseline"
tools/run_phase0_baselines.sh "${MODE}" "${OUTPUT_DIR}/baseline"

python3 - "${OUTPUT_DIR}/baseline/raw-results.json" "${OUTPUT_DIR}/gate-summary.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

baseline_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
document = json.loads(baseline_path.read_text(encoding="utf-8"))

required_checks = {
    "real_issue23_executable_probe_passed",
    "real_issue23_executable_failure_and_recovery_probe_passed",
    "linux_process_resource_probe_supported",
    "configured_runtime_workers_observed_before_and_after_loading",
    "prepared_cache_bounded_after_prepare",
    "fixed_pool_queue_saturation_is_bounded",
    "fixed_pool_returns_to_configured_idle_state",
    "real_activation_throughput_reaches_pool_capacity",
    "real_activation_throughput_reaches_bounded_queue_saturation",
    "activation_owned_state_returns_to_baseline_after_every_sample",
    "all_scenarios_return_expected_terminal_outcomes",
    "failure_does_not_degrade_the_next_cause_specific_echo",
    "timeout_and_cancellation_overshoot_are_bounded",
    "topology_constant_across_component_loading_and_repeated_invocations",
    "rss_has_no_unbounded_monotonic_growth",
    "file_descriptors_have_no_unbounded_monotonic_growth",
    "explicit_release_clears_prepared_cache",
    "post_release_backend_and_pool_are_clean",
    "runtime_shutdown_returns_thread_count_to_process_baseline",
}
required_outcomes = {
    "success",
    "domain_error",
    "trap",
    "timeout",
    "cancelled",
    "resource_exhausted",
}

if document.get("schema_version") != "latent.phase0.baseline.v2":
    raise SystemExit("unexpected Phase 0 baseline schema")
if document.get("status") != "pass":
    raise SystemExit("Phase 0 baseline did not pass")
if document.get("production_ready") is not False:
    raise SystemExit("baseline must remain explicitly non-production")
if document.get("phase1_api_compatible") is not False:
    raise SystemExit("Phase 0 spike must remain explicitly non-Phase-1-compatible")

checks = {check["name"]: check for check in document.get("checks", [])}
missing = sorted(required_checks - checks.keys())
failed = sorted(
    name for name in required_checks if name in checks and checks[name].get("passed") is not True
)
if missing or failed:
    raise SystemExit(f"required Phase 0 checks missing={missing} failed={failed}")

observed_outcomes = {
    sample.get("outcome", {}).get("name")
    for sample in document.get("activation_samples", [])
}
missing_outcomes = sorted(required_outcomes - observed_outcomes)
if missing_outcomes:
    raise SystemExit(f"required terminal outcomes were not observed: {missing_outcomes}")

harness = document.get("executable_harness", {})
if not harness.get("samples"):
    raise SystemExit("real executable harness produced no success samples")
if not harness.get("failure_recovery_samples"):
    raise SystemExit("real executable harness produced no failure/recovery samples")

summary = {
    "schema_version": "latent.phase0.gate.v1",
    "status": "pass",
    "profile": document.get("config", {}).get("mode"),
    "baseline_schema_version": document["schema_version"],
    "baseline_path": str(baseline_path),
    "reference_evidence_path": "benchmarks/phase0/raw-results.json",
    "required_checks_passed": len(required_checks),
    "observed_terminal_outcomes": sorted(required_outcomes),
    "executable_e2e": "passed",
    "production_ready": False,
    "phase1_api_compatible": False,
}
summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, sort_keys=True))
PY

echo "==> Phase 0 gate PASS"
echo "    baseline: ${OUTPUT_DIR}/baseline/raw-results.json"
echo "    report:   ${OUTPUT_DIR}/baseline/BASELINE.md"
echo "    receipt:  ${OUTPUT_DIR}/gate-summary.json"
