#!/usr/bin/env bash
# Feature-specific allocator observation, deliberately separate from --all-features.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
OUTPUT="${1:-${CARGO_TARGET_DIR:-target}/contracts/native-stack-custody}"
WITNESS="native_stacks::tests::stack_custody_allocation::original_metadata_charge_survives_actual_stack_context_backing_deallocation"

if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    printf '%s\n' 'stack custody witness requires Linux x86_64' >&2
    exit 1
fi
mkdir -p "${OUTPUT}"

for profile in ordinary combined; do
    features=development-stack-custody-witness
    if [[ "${profile}" == combined ]]; then
        features+=,development-rust-http-combined
    fi
    command=(cargo test --locked -p latent-wasmtime --lib --features "${features}")
    # Listing builds the exact feature closure first. A zero-test success caused
    # by accidentally selecting the other global allocator must not pass.
    "${command[@]}" -- --list --format terse --color never > "${OUTPUT}/${profile}.list"
    grep -Fx "${WITNESS}: test" "${OUTPUT}/${profile}.list"
    if [[ "${profile}" == combined ]]; then
        grep -E '^native_stacks::tests::combined::.+: test$' "${OUTPUT}/${profile}.list"
    fi
    # Compilation is already complete; bound the actual blocking observation.
    timeout --kill-after=10s 180s "${command[@]}" -- \
        native_stacks::tests:: --test-threads=1 --format pretty --color never \
        | tee "${OUTPUT}/${profile}.log"
    grep -Fx "test ${WITNESS} ... ok" "${OUTPUT}/${profile}.log"
    if [[ "${profile}" == combined ]]; then
        grep -E '^test native_stacks::tests::combined::.+ \.\.\. ok$' "${OUTPUT}/${profile}.log"
    fi
done
