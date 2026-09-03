#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

cargo fmt --all --check
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked --keep-going

cargo test --locked --all-targets --all-features \
  -p latent-telemetry \
  -p latent-node \
  -p latent-testkit \
  -p latent-wasmtime \
  -p latentd

# Build the generated contracts and both Phase 0 component fixtures used by the
# real executable test. This also proves the observability changes did not fork
# the retained Phase 0 composition.
tools/validate_contracts.sh

# The test is ignored in generic `cargo test` because it requires the external
# Wasm/Buf toolchain prepared above; this gate runs it deliberately.
cargo test --locked -p latentd --test phase0_spike_e2e \
  cases::executable_covers_success_failures_and_same_runtime_post_failure_recovery \
  -- --ignored --exact --nocapture
