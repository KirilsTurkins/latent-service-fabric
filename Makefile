CARGO ?= cargo
PYTHON ?= python3

.PHONY: check help rpc-bindings component-bindings guest-bindings echo-capsule echo-capsule-reproducibility phase0-spike-demo phase0-calibration phase0-gate phase0-gate-smoke phase1-foundation fmt fmt-check clippy test schemas repository-tests contracts sdks validate tree

check:
	$(CARGO) check --workspace --all-targets --all-features --locked

help:
	@printf '%s\n' \
		'LSF contributor commands' \
		'' \
		'Validation and formatting:' \
		'  check                         Compile the Rust workspace and all targets.' \
		'  fmt                           Format all Rust workspace sources.' \
		'  fmt-check                     Check Rust formatting without modifying sources.' \
		'  clippy                        Run Clippy across the Rust workspace.' \
		'  test                          Run Rust workspace tests.' \
		'  schemas                       Validate repository and foundation schemas/contracts.' \
		'  repository-tests              Run repository-local Python unit tests.' \
		'  contracts                     Validate contracts and bounded integration fixtures.' \
		'  sdks                          Validate all maintained SDK contract surfaces.' \
		'  phase1-foundation             Run the retained Phase 1 Rust/contracts validation aggregate.' \
		'  validate                      Run the normal clean-checkout validation entry point.' \
		'' \
		'Bindings and generated fixtures:' \
		'  rpc-bindings                  Check generated RPC bindings.' \
		'  component-bindings            Check host and wasm32-wasip2 component bindings.' \
		'  guest-bindings                Check guest bindings and the echo guest example.' \
		'  echo-capsule                  Build the maintained echo capsule fixture (manual generated build).' \
		'  echo-capsule-reproducibility  Verify two clean echo builds are byte-identical (manual fixture check).' \
		'' \
		'Retained Phase 0 evidence commands (historical/manual):' \
		'  phase0-spike-demo             Run the retained Phase 0 executable spike demo.' \
		'  phase0-calibration            Run retained native Phase 0 calibration.' \
		'  phase0-gate                   Run the retained full Phase 0 authorization gate.' \
		'  phase0-gate-smoke             Run the deterministic retained Phase 0 smoke gate.' \
		'' \
		'Utility:' \
		'  tree                          List repository files while excluding common generated trees.'

rpc-bindings:
	$(CARGO) check -p latent-rpc --all-targets --all-features --locked

component-bindings:
	$(CARGO) check -p latent-component-bindings --locked
	$(CARGO) check -p latent-component-bindings --target wasm32-wasip2 --locked

guest-bindings: component-bindings
	$(CARGO) check -p latent-toolchain-smoke --target wasm32-wasip2 --locked
	$(CARGO) check -p latent-toolchain-smoke --example echo-capsule --target wasm32-wasip2 --locked

echo-capsule:
	$(PYTHON) tools/build_echo_capsule.py

echo-capsule-reproducibility:
	$(PYTHON) tools/build_echo_capsule.py --verify-reproducible

phase0-spike-demo:
	tools/run_phase0_spike.sh

phase0-calibration:
	tools/run_phase0_calibration.sh

phase0-gate:
	tools/run_phase0_gate.sh full

phase0-gate-smoke:
	tools/run_phase0_gate.sh smoke

fmt:
	$(CARGO) fmt --all

fmt-check:
	$(CARGO) fmt --all --check

clippy:
	$(CARGO) clippy --workspace --all-targets --all-features --locked

test:
	$(CARGO) test --workspace --all-targets --all-features --locked

schemas:
	$(PYTHON) tools/validate_repository.py
	$(PYTHON) tools/validate_foundation.py

repository-tests:
	$(PYTHON) -m unittest discover -s tools/tests

contracts:
	tools/validate_contracts.sh

sdks:
	tools/validate_sdks.sh

phase1-foundation: fmt-check check clippy test contracts

validate: phase1-foundation sdks

tree:
	find . -type f \
		-not -path './.git/*' \
		-not -path './target/*' \
		-not -path '*/node_modules/*' \
		| sort
