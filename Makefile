.PHONY: check fmt fmt-check clippy schemas tree

check:
	cargo check --workspace --all-targets

fmt:
	cargo fmt --all

fmt-check:
	cargo fmt --all --check

clippy:
	cargo clippy --workspace --all-targets --all-features

schemas:
	python3 tools/validate_repository.py

tree:
	find . -type f | sort
