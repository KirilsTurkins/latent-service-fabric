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

wasm-tools parse crates/latent-wasmtime/src/values/types.wat \
    -o "${OUTPUT}/wit/value-types.wasm"
cmp "${OUTPUT}/wit/value-types.wasm" crates/latent-wasmtime/src/values/types.wasm
wasm-tools validate "${OUTPUT}/wit/value-types.wasm"

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
buf build api/proto --as-file-descriptor-set --exclude-source-info \
    -o "${OUTPUT}/proto/latent-api.json"
python3 tools/validate_phase1_descriptor.py "${OUTPUT}/proto/latent-api.json"

cargo check -p latent-rpc --all-targets --all-features --locked
cargo test -p latent-rpc --locked
cargo check -p latent-component-bindings --locked
cargo check -p latent-component-bindings --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example echo-capsule --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example oversized-log-capsule --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example containment-capsule --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example generic-capsule --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example capabilities-capsule --target wasm32-wasip2 --locked
python3 tools/reset_validation_echo.py --target-root "${TARGET_ROOT}"
python3 tools/build_provenance.py --verify-reproducible \
    --repository https://github.com/KirilsTurkins/latent-service-fabric \
    --output-dir "${TARGET_ROOT}/capsules/echo-provenance" \
    --legacy-output-dir "${TARGET_ROOT}/capsules/echo"
python3 tools/validate_package_smoke.py
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

cargo build -p latent-toolchain-smoke --example generic-capsule \
    --target wasm32-unknown-unknown --release --locked
GENERIC_CORE="${TARGET_ROOT}/wasm32-unknown-unknown/release/examples/generic_capsule.wasm"
GENERIC_COMPONENT="${TARGET_ROOT}/capsules/generic/generic-capsule.wasm"
GENERIC_FIXTURES="${TARGET_ROOT}/capsules/generic/adversarial"
mkdir -p "${GENERIC_FIXTURES}"
wasm-tools component new "${GENERIC_CORE}" -o "${GENERIC_COMPONENT}"
wasm-tools validate "${GENERIC_COMPONENT}"
wasm-tools component wit tools/toolchain-smoke/examples/generic_capsule --json \
    > "${OUTPUT}/wit/generic-fixture.json"
for fixture in "${ROOT}"/crates/latent-wasmtime/tests/fixtures/*.wat; do
    name="$(basename "${fixture}" .wat)"
    wasm-tools parse "${fixture}" -o "${GENERIC_FIXTURES}/${name}.wasm"
    wasm-tools validate "${GENERIC_FIXTURES}/${name}.wasm"
done

cargo build -p latent-toolchain-smoke --example capabilities-capsule \
    --target wasm32-unknown-unknown --release --locked
CAPABILITIES_CORE="${TARGET_ROOT}/wasm32-unknown-unknown/release/examples/capabilities_capsule.wasm"
CAPABILITIES_COMPONENT="${TARGET_ROOT}/capsules/capabilities/capabilities-capsule.wasm"
mkdir -p "$(dirname "${CAPABILITIES_COMPONENT}")"
wasm-tools component new "${CAPABILITIES_CORE}" -o "${CAPABILITIES_COMPONENT}"
wasm-tools validate "${CAPABILITIES_COMPONENT}"
python3 tools/stage_runtime_wit.py "${OUTPUT}/capabilities-wit" \
    --source tools/toolchain-smoke/examples/capabilities_capsule
wasm-tools component wit "${OUTPUT}/capabilities-wit" --json \
    > "${OUTPUT}/wit/capabilities-fixture.json"
CAPABILITIES_FIXTURES="${ROOT}/crates/latent-wasmtime/tests/capabilities_backend/fixtures"
while read -r family contract; do
    wat="${OUTPUT}/wit/denied-${family}.wat"
    component="$(dirname "${CAPABILITIES_COMPONENT}")/denied-${family}.wasm"
    sed "s|tests:denied/host@0.1.0|${contract}|" \
        "${CAPABILITIES_FIXTURES}/denied-import.wat" > "${wat}"
    wasm-tools parse "${wat}" -o "${component}"
    wasm-tools validate "${component}"
done < "${CAPABILITIES_FIXTURES}/denied-imports.txt"

ENGINE_MEMORY_COMPONENT="${TARGET_ROOT}/capsules/engine-memory/engine-memory-capsule.wasm"
mkdir -p "$(dirname "${ENGINE_MEMORY_COMPONENT}")"
wasm-tools parse tools/toolchain-smoke/examples/engine_memory/component.wat \
    -o "${ENGINE_MEMORY_COMPONENT}"
wasm-tools validate "${ENGINE_MEMORY_COMPONENT}"
wasm-tools component wit "${ENGINE_MEMORY_COMPONENT}" --json \
    > "${OUTPUT}/wit/engine-memory-component.json"

LSF_ECHO_COMPONENT="${TARGET_ROOT}/capsules/echo/echo-capsule.wasm" \
LSF_ECHO_CAPSULE="${TARGET_ROOT}/capsules/echo/capsule.json" \
LSF_OVERSIZED_LOG_COMPONENT="${OVERSIZED_LOG_COMPONENT}" \
    cargo test -p latent-wasmtime --test echo_backend --locked -- --ignored --nocapture

LSF_CONTAINMENT_COMPONENT="${CONTAINMENT_COMPONENT}" \
    cargo test -p latent-wasmtime --test containment_backend --locked -- \
        --ignored --nocapture --test-threads=1

LSF_GENERIC_COMPONENT="${GENERIC_COMPONENT}" \
LSF_GENERIC_FIXTURES="${GENERIC_FIXTURES}" \
LSF_ENGINE_MEMORY_COMPONENT="${ENGINE_MEMORY_COMPONENT}" \
LSF_ECHO_COMPONENT="${TARGET_ROOT}/capsules/echo/echo-capsule.wasm" \
    cargo test -p latent-wasmtime --test generic_backend --locked -- \
        --ignored --nocapture --test-threads=1

LSF_CAPABILITIES_COMPONENT="${CAPABILITIES_COMPONENT}" \
    cargo test -p latent-wasmtime --test capabilities_backend --locked -- \
        --ignored --nocapture --test-threads=1

# Two real node invocations across a durable restart; no scale workload.
LSF_ECHO_COMPONENT="${TARGET_ROOT}/capsules/echo/echo-capsule.wasm" \
LSF_ECHO_CAPSULE="${TARGET_ROOT}/capsules/echo/capsule.json" \
    cargo test -p latentd --test standalone_node --locked -- \
        --ignored --nocapture --test-threads=1

# A tiny generic component verifies one running and one queued owner at shutdown.
SHUTDOWN_COMPONENT="${TARGET_ROOT}/capsules/standalone-shutdown/spin.wasm"
mkdir -p "$(dirname "${SHUTDOWN_COMPONENT}")"
wasm-tools parse apps/latentd/tests/standalone_shutdown/spin.wat -o "${SHUTDOWN_COMPONENT}"
wasm-tools validate "${SHUTDOWN_COMPONENT}"
LSF_SHUTDOWN_COMPONENT="${SHUTDOWN_COMPONENT}" \
    cargo test -p latentd --test standalone_shutdown --locked -- \
        --ignored --nocapture --test-threads=1

# Small real CLI/node workflows, including explicit cancellation; no scale workload.
cargo build -p latent -p latentd --locked
LSF_LATENTD_BIN="${TARGET_ROOT}/debug/latentd" \
LSF_ECHO_COMPONENT="${TARGET_ROOT}/capsules/echo/echo-capsule.wasm" \
LSF_GENERIC_COMPONENT="${GENERIC_COMPONENT}" \
LSF_GENERIC_FIXTURES="${GENERIC_FIXTURES}" \
    cargo test -p latent --test standalone_cli --locked -- \
        --ignored --nocapture --test-threads=1

# Two actual RPC Invokes prove input disposal and same-cell reuse after handoff.
LSF_GENERIC_COMPONENT="${GENERIC_COMPONENT}" \
    cargo test -p latentd --lib --locked -- \
        standalone::measurements::comparison::ownership_supervision::transferred_backend_input_retires_before_same_cell_reuse \
        --exact --ignored --nocapture --test-threads=1

# Selected Phase 1 evidence: hard64 attempted Invokes, no scale/soak/calibration.
python3 tools/run_phase1_conformance.py --target-root "${TARGET_ROOT}"

# Separate tiny collector validation. Full100k profiles remain explicit opt-ins.
python3 tools/run_phase1_measurements.py --profile smoke --target-root "${TARGET_ROOT}"
