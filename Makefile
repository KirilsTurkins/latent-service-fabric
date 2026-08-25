CARGO ?= cargo
PYTHON ?= python3

.PHONY: check guest-bindings echo-capsule echo-capsule-reproducibility phase0-spike-demo fmt fmt-check clippy test schemas repository-tests contracts sdks validate tree

check:
	$(CARGO) check --workspace --all-targets --all-features --locked

guest-bindings:
	$(CARGO) check -p latent-toolchain-smoke --target wasm32-wasip2 --locked
	$(CARGO) check -p latent-toolchain-smoke --example echo-capsule --target wasm32-wasip2 --locked

echo-capsule:
	$(PYTHON) tools/build_echo_capsule.py

echo-capsule-reproducibility:
	$(PYTHON) tools/build_echo_capsule.py --verify-reproducible

phase0-spike-demo:
	tools/run_phase0_spike.sh

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

repository-tests:
	$(PYTHON) -m unittest discover -s tools/tests

contracts:
	tools/validate_contracts.sh

sdks:
	tools/validate_sdks.sh

validate: fmt-check check clippy test contracts sdks

tree:
	find . -type f \
		-not -path './.git/*' \
		-not -path './target/*' \
		-not -path '*/node_modules/*' \
		| sort
