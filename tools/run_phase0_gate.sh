#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
if [[ "${TARGET_ROOT}" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi

MODE="${1:-full}"
OUTPUT_DIR="${2:-}"

case "${MODE}" in
    smoke|full) ;;
    *)
        echo "usage: $0 [smoke|full] [new-output-directory]" >&2
        exit 64
        ;;
esac

for command in cargo git python3 wasm-tools buf make zstd; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        echo "required Phase 0 gate command is unavailable: ${command}" >&2
        exit 69
    fi
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    mkdir -p "${TARGET_ROOT}/phase0-gate"
    OUTPUT_DIR="$(mktemp -d "${TARGET_ROOT}/phase0-gate/${MODE}.XXXXXX")"
else
    if [[ "${OUTPUT_DIR}" != /* ]]; then
        OUTPUT_DIR="${ROOT}/${OUTPUT_DIR}"
    fi
    if [[ -e "${OUTPUT_DIR}" ]]; then
        echo "Phase 0 gate output directory already exists: ${OUTPUT_DIR}" >&2
        exit 73
    fi
    mkdir -p "$(dirname "${OUTPUT_DIR}")"
    mkdir "${OUTPUT_DIR}"
fi

cd "${ROOT}"
export GITHUB_SHA="$(git rev-parse HEAD)"

echo "==> Phase 0 gate: repository contracts, builds, and tests"
make validate
make repository-tests

echo "==> Phase 0 gate: real executable spike and containment"
tools/run_phase0_spike.sh

echo "==> Phase 0 gate: ${MODE} executable baseline"
tools/run_phase0_baselines.sh "${MODE}" "${OUTPUT_DIR}/baseline"

echo "==> Phase 0 gate: retained evidence receipt"
validator_args=(
    "${OUTPUT_DIR}/baseline/raw-results.json"
    "${OUTPUT_DIR}/gate-summary.json"
)
if [[ "${MODE}" == "full" ]]; then
    validator_args+=(--require-authorized)
fi

if ! python3 tools/validate_phase0_gate.py "${validator_args[@]}"; then
    echo "Phase 0 gate receipt: ${OUTPUT_DIR}/gate-summary.json" >&2
    exit 1
fi

AUTHORIZATION_STATUS="$(python3 - "${OUTPUT_DIR}/gate-summary.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(receipt["authorization_status"].upper())
PY
)"
if [[ "${MODE}" == "smoke" ]]; then
    echo "==> Phase 0 smoke validation: PASS"
else
    echo "==> Phase 0 completion validation: PASS"
fi
echo "==> Phase 1 authorization: ${AUTHORIZATION_STATUS}"
echo "    baseline: ${OUTPUT_DIR}/baseline/raw-results.json"
echo "    report:   ${OUTPUT_DIR}/baseline/BASELINE.md"
echo "    receipt:  ${OUTPUT_DIR}/gate-summary.json"
