#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "${ROOT}"
profile="${1:-smoke}"
source tools/phase0_build_environment.sh
phase0_reject_inherited_build_overrides
phase0_reject_hidden_cargo_configuration
case "${profile}" in
  smoke)
    # Keep all four retained smoke executables within the existing evidence
    # budget. This command-local setting follows the inherited-override guard;
    # the full native recipe and release guest build remain unchanged.
    CARGO_PROFILE_DEV_DEBUG=0 cargo build -p latent -p latentd -p latent-optimization-bench --bins --locked
    ;;
  full) phase0_release_cargo build -p latent -p latentd -p latent-optimization-bench --bins --release --locked ;;
  *) printf '%s\n' 'profile must be smoke or full' >&2; exit 2 ;;
esac
cargo build -p latent-toolchain-smoke --example optimization-capsule \
    --target wasm32-unknown-unknown --release --locked
target_root="${CARGO_TARGET_DIR:-${ROOT}/target}"
mkdir -p "${target_root}/capsules/optimization"
wasm-tools component new \
    "${target_root}/wasm32-unknown-unknown/release/examples/optimization_capsule.wasm" \
    -o "${target_root}/capsules/optimization/optimization-capsule.wasm"
wasm-tools validate "${target_root}/capsules/optimization/optimization-capsule.wasm"
wasm-tools component wit "${target_root}/capsules/optimization/optimization-capsule.wasm"
