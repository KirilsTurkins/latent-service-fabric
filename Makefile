CARGO ?= cargo
PYTHON ?= python3

.PHONY: check rpc-bindings component-bindings guest-bindings echo-capsule echo-capsule-reproducibility phase0-spike-demo phase0-calibration phase0-gate phase0-gate-smoke phase1-foundation fmt fmt-check clippy test schemas repository-tests contracts sdks validate tree

check:
	$(CARGO) check --workspace --all-targets --all-features --locked

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
