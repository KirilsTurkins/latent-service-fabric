#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=phase0_build_environment.sh
source "${ROOT}/tools/phase0_build_environment.sh"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
if [[ "${TARGET_ROOT}" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi

phase0_reject_inherited_build_overrides
INPUT="${LSF_SPIKE_INPUT:-hello from the Phase 0 spike}"

cd "${ROOT}"

# This gate validates every checked-in contract, builds the real echo and
# containment components, and runs the lower-level Wasmtime containment tests.
tools/validate_contracts.sh

# The executable matrix includes `verify-recovery`, which retains one
# runtime/pool/backend/prepared-runner composition across a trap and echo.
LSF_ECHO_CAPSULE="${TARGET_ROOT}/capsules/echo/capsule.json" \
LSF_CONTAINMENT_COMPONENT="${TARGET_ROOT}/capsules/containment/containment-capsule.wasm" \
    cargo test -p latentd --test phase0_spike_e2e --locked -- --ignored --nocapture

cargo build -p latentd --locked

exec "${TARGET_ROOT}/debug/latentd" phase0-spike invoke-once \
    --capsule "${TARGET_ROOT}/capsules/echo" \
    --input "${INPUT}" \
    --pool-capacity 2 \
    --pool-queue-capacity 16 \
    --runtime-workers 2 \
    --memory-bytes 4194304 \
    --fuel 1000000 \
    --timeout-ms 1000
