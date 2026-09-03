#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
if [[ "${TARGET_ROOT}" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi
OUTPUT="${TARGET_ROOT}/contracts"

cd "${ROOT}"
rm -rf "${OUTPUT}"
mkdir -p "${OUTPUT}/wit" "${OUTPUT}/proto" "${OUTPUT}/example-wit"

python3 tools/validate_repository.py
python3 tools/validate_foundation.py
python3 -m unittest discover -s tools/tests

while IFS= read -r package; do
    name="$(basename "${package}")"
    if [[ "${name}" == "runtime" ]]; then
        continue
    fi
    wasm-tools component wit "${package}" --json > "${OUTPUT}/wit/platform-${name}.json"
done < <(find "${ROOT}/wit/platform" -mindepth 1 -maxdepth 1 -type d | sort)

python3 tools/stage_runtime_wit.py "${OUTPUT}/runtime-wit"
wasm-tools component wit "${OUTPUT}/runtime-wit" --json > "${OUTPUT}/wit/platform-runtime.json"

while IFS= read -r package; do
    relative="${package#"${ROOT}/"}"
    artifact="${relative//\//-}"
    staged="${OUTPUT}/example-wit/${artifact}"
    python3 tools/stage_runtime_wit.py "${staged}" --source "${package}"
    wasm-tools component wit "${staged}" --json > "${OUTPUT}/wit/${artifact}.json"
done < <(find "${ROOT}/examples" -type d -name wit | sort)

buf lint api/proto
buf build api/proto --as-file-descriptor-set -o "${OUTPUT}/proto/latent-api.bin"

cargo check -p latent-rpc --all-targets --all-features --locked
cargo test -p latent-rpc --locked
cargo check -p latent-component-bindings --locked
cargo check -p latent-component-bindings --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example echo-capsule --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example oversized-log-capsule --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example containment-capsule --target wasm32-wasip2 --locked
python3 tools/build_echo_capsule.py --verify-reproducible
cargo build -p latent-toolchain-smoke --example oversized-log-capsule \
    --target wasm32-unknown-unknown --release --locked
OVERSIZED_LOG_CORE="${TARGET_ROOT}/wasm32-unknown-unknown/release/examples/oversized_log_capsule.wasm"
OVERSIZED_LOG_COMPONENT="${TARGET_ROOT}/capsules/oversized-log/oversized-log-capsule.wasm"
mkdir -p "$(dirname "${OVERSIZED_LOG_COMPONENT}")"
wasm-tools component new "${OVERSIZED_LOG_CORE}" -o "${OVERSIZED_LOG_COMPONENT}"
wasm-tools validate "${OVERSIZED_LOG_COMPONENT}"

cargo build -p latent-toolchain-smoke --example containment-capsule \
    --target wasm32-unknown-unknown --release --locked
CONTAINMENT_CORE="${TARGET_ROOT}/wasm32-unknown-unknown/release/examples/containment_capsule.wasm"
CONTAINMENT_COMPONENT="${TARGET_ROOT}/capsules/containment/containment-capsule.wasm"
mkdir -p "$(dirname "${CONTAINMENT_COMPONENT}")"
wasm-tools component new "${CONTAINMENT_CORE}" -o "${CONTAINMENT_COMPONENT}"
wasm-tools validate "${CONTAINMENT_COMPONENT}"

LSF_ECHO_COMPONENT="${TARGET_ROOT}/capsules/echo/echo-capsule.wasm" \
LSF_ECHO_CAPSULE="${TARGET_ROOT}/capsules/echo/capsule.json" \
LSF_OVERSIZED_LOG_COMPONENT="${OVERSIZED_LOG_COMPONENT}" \
    cargo test -p latent-wasmtime --test echo_backend --locked -- --ignored --nocapture

LSF_CONTAINMENT_COMPONENT="${CONTAINMENT_COMPONENT}" \
    cargo test -p latent-wasmtime --test containment_backend --locked -- \
        --ignored --nocapture --test-threads=1
