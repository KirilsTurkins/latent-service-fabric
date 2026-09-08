#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
if [[ "${TARGET_ROOT}" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi
cd "${ROOT}"

python3 tools/build_echo_capsule.py --verify-reproducible
for fixture in generic capabilities; do
    cargo build -p latent-toolchain-smoke --example "${fixture}-capsule" \
        --target wasm32-unknown-unknown --release --locked
    component="${TARGET_ROOT}/capsules/${fixture}/${fixture}-capsule.wasm"
    core="${TARGET_ROOT}/wasm32-unknown-unknown/release/examples/${fixture}_capsule.wasm"
    mkdir -p "$(dirname "${component}")"
    wasm-tools component new "${core}" -o "${component}"
    wasm-tools validate "${component}"
done
