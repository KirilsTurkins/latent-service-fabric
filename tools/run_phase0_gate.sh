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

python3 tools/validate_phase0_gate.py \
    "${OUTPUT_DIR}/baseline/raw-results.json" \
    "${OUTPUT_DIR}/gate-summary.json"

echo "==> Phase 0 gate PASS"
echo "    baseline: ${OUTPUT_DIR}/baseline/raw-results.json"
echo "    report:   ${OUTPUT_DIR}/baseline/BASELINE.md"
echo "    receipt:  ${OUTPUT_DIR}/gate-summary.json"
