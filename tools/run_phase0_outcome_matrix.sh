#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
if [[ "${TARGET_ROOT}" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi

ECHO_CAPSULE="${TARGET_ROOT}/capsules/echo/capsule.json"
CONTAINMENT_COMPONENT="${TARGET_ROOT}/capsules/containment/containment-capsule.wasm"

if [[ ! -f "${ECHO_CAPSULE}" ]]; then
    echo "Phase 0 echo capsule fixture is missing: ${ECHO_CAPSULE}" >&2
    exit 2
fi
if [[ ! -f "${CONTAINMENT_COMPONENT}" ]]; then
    echo "Phase 0 containment component fixture is missing: ${CONTAINMENT_COMPONENT}" >&2
    exit 2
fi

cd "${ROOT}"
LSF_ECHO_CAPSULE="${ECHO_CAPSULE}" \
LSF_CONTAINMENT_COMPONENT="${CONTAINMENT_COMPONENT}" \
    cargo test -p latentd --test phase0_spike_e2e --locked -- --ignored --nocapture
