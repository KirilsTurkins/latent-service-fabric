.DEFAULT_GOAL := help
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

# These targets share Cargo/generated-fixture roots. Parallelism inside an owning
# runner remains unchanged; independent Make recipes must not race those writers.
.NOTPARALLEL:

PYTHON ?= python3
NODE ?= node
BOOTSTRAP_NPM ?= npm
FORMAT ?= human
WORKSPACE_ROOT ?= target/make
WORKSPACE_INVENTORY = $(WORKSPACE_ROOT)/workspace.jsonl
AOT_INPUTS = $(WORKSPACE_ROOT)/aot
TEST_REPORTS = $(WORKSPACE_ROOT)/test-results
WEBSITE_NPM = $(NODE) website/toolchain/node_modules/npm/bin/npm-cli.js --prefix website

# Keep scalar selectors/paths as single shell arguments, including apostrophes.
quote = '$(subst ','"'"',$(1))'
require = $(if $(strip $($(1))),,$(error $(1) is required for $@; see make help))
selection = --suite $(call quote,$(SUITE)) $(if $(strip $(CASE)),--case $(call quote,$(CASE))) $(if $(strip $(INVENTORY)),--inventory $(call quote,$(INVENTORY))) --output $(call quote,$(FORMAT))

.PHONY: help tree toolchain-check schemas docs ci-contracts validate-source \
 fmt fmt-check check bindings rpc-bindings component-bindings guest-bindings \
 check-production clippy check-msrv test-deterministic check-rust \
 test-list test-explain test-plan test-check test-prepare test-run test-reproduce \
 workspace-prepare aot-prepare workspace-discover test repository-tests \
 contracts contracts-python contracts-bindings contracts-runtime \
 contracts-standalone contracts-sdk-provider contracts-measurements sdks \
 echo-capsule echo-capsule-reproducibility validate-preflight validate \
 website-prepare website-toolchain-check website-check website-test \
 website-build website-build-root website-test-build website-browser-install website-validate

##@ Start here
help: ## Show commands; no build, installation or test execution.
	@awk 'BEGIN { print "LSF contributor commands (GNU Make + Bash)" } /^##@ / { print "\n" substr($$0, 5) } /^[a-zA-Z][a-zA-Z0-9_ -]*:.*## / { split($$0, parts, ":"); sub(/^.*## /, "", $$0); count = split(parts[1], names, " "); for (i = 1; i <= count; i++) printf "  %-35s %s\n", names[i], $$0 }' Makefile
	@printf '\n%s\n%s\n%s\n%s\n' 'Focused tests: SUITE=<registered-id> [CASE=<exact-name>] INVENTORY=<owned.jsonl> [FORMAT=json]' 'Reproduction: REPORT=<latent.test-run.v1.json> INVENTORY=<owned.jsonl>' 'Broad checks: WORKSPACE_ROOT=target/make/<fresh-run>; clean tracked Linux checkout required.' 'See docs/development/make-commands.md and VALIDATION.md for prerequisites and limits.'

tree: ## List tracked source paths, excluding ignored/untracked output.
	@git ls-files

toolchain-check: ## Check the full pinned SDK toolchain; never install it.
	$(PYTHON) tools/check_tool_versions.py

##@ Source and documentation
schemas: ## Validate repository, generated-source ownership and foundation contracts.
	$(PYTHON) tools/validate_repository.py
	$(PYTHON) tools/validate_foundation.py

docs: ## Validate Markdown, links, anchors, SVGs and application command examples.
	$(PYTHON) tools/validate_docs.py

ci-contracts: ## Check reviewed command/case coverage and immutable workflow action pins.
	$(PYTHON) tools/ci_coverage.py
	$(PYTHON) tools/validate_workflow_actions.py

validate-source: schemas docs ci-contracts ## Run source/documentation/CI contracts without a Rust build.

##@ Rust checks (shared CI recipes; pinned Cargo on PATH)
fmt: ## Format Rust sources explicitly.
	cargo fmt --all

fmt-check: ## Check Rust formatting without modifying sources.
	$(PYTHON) tools/ci_cargo.py run format

check: ## Check the locked workspace, all targets and all features.
	$(PYTHON) tools/ci_cargo.py run workspace-check

bindings: ## Check the complete shared RPC/host/guest binding recipe.
	$(PYTHON) tools/ci_cargo.py run bindings

rpc-bindings: ## Check generated RPC bindings independently.
	cargo check -p latent-rpc --all-targets --all-features --locked

component-bindings: ## Check host and wasm32-wasip2 component bindings independently.
	cargo check -p latent-component-bindings --locked
	cargo check -p latent-component-bindings --target wasm32-wasip2 --locked

guest-bindings: component-bindings ## Check the guest toolchain and maintained echo guest bindings.
	cargo check -p latent-toolchain-smoke --target wasm32-wasip2 --locked
	cargo check -p latent-toolchain-smoke --example echo-capsule --target wasm32-wasip2 --locked

check-production: ## Check applications and compiler without workspace dev-feature unification.
	$(PYTHON) tools/ci_cargo.py run production

clippy: ## Run workspace Clippy and the selected warnings-as-errors policy.
	$(PYTHON) tools/ci_cargo.py run clippy

check-msrv: ## Check with the declared MSRV already installed; never install a compiler.
	$(PYTHON) tools/ci_cargo.py run msrv

test-deterministic: ## Run the shared deterministic helper/race/compatibility/example recipe.
	$(PYTHON) tools/check_testkit_dependencies.py
	$(PYTHON) tools/ci_cargo.py run deterministic

check-rust: fmt-check check bindings check-production clippy test-deterministic ## Run Rust build/lint/helper checks; excludes ordinary workspace execution.

##@ One registered suite/case (no implicit preparation in check/run)
test-list: ## List the current shared catalogue; metadata only.
	@$(PYTHON) tools/test.py list --output $(call quote,$(FORMAT))

test-explain test-plan: ## Inspect SUITE and optional exact CASE; metadata only.
	$(call require,SUITE)
	@$(PYTHON) tools/test.py $(@:test-%=%) $(selection)

test-check: ## Check SUITE inputs; INVENTORY is optional for needs-preparation diagnostics.
	$(call require,SUITE)
	@$(PYTHON) tools/test.py check $(selection)

test-prepare test-run: ## Explicitly prepare or execute SUITE; require the same owned INVENTORY.
	$(call require,SUITE)
	$(call require,INVENTORY)
	@$(PYTHON) tools/test.py $(@:test-%=%) $(selection)

test-reproduce: ## Replay REPORT with its owned INVENTORY; no changed-checkout override.
	$(call require,REPORT)
	$(call require,INVENTORY)
	@$(PYTHON) tools/test.py reproduce $(call quote,$(REPORT)) --inventory $(call quote,$(INVENTORY)) --output $(call quote,$(FORMAT))

##@ Complete prepared workspace tests (Linux x86_64)
workspace-prepare: ## Explicitly build workspace binaries/harnesses and a fresh Cargo inventory.
	$(call require,WORKSPACE_ROOT)
	$(PYTHON) tools/ci_cargo.py run prepare --inventory $(call quote,$(WORKSPACE_INVENTORY))

aot-prepare: ## Prepare AOT inputs, or validate existing immutable inputs; never overwrite them.
	$(call require,WORKSPACE_ROOT)
	@if [[ -e $(call quote,$(AOT_INPUTS)) ]]; then \
	  $(PYTHON) tools/aot_test_inputs.py validate --manifest $(call quote,$(AOT_INPUTS)/manifest.json); \
	else \
	  $(PYTHON) tools/aot_test_inputs.py prepare --inventory $(call quote,$(WORKSPACE_INVENTORY)) --output $(call quote,$(AOT_INPUTS)); \
	fi

workspace-discover: ## Authenticate complete discovery from prepared inputs; no build or test run.
	$(call require,WORKSPACE_ROOT)
	@source_commit="$$(git rev-parse --verify HEAD)"; \
	GITHUB_SHA="$$source_commit" $(PYTHON) tools/ci_suite_discovery.py --inventory $(call quote,$(WORKSPACE_INVENTORY)) --receipt $(call quote,$(WORKSPACE_ROOT)/discovery.json)

test: ## Execute prepared workspace/custom harnesses, doctests and signing checks; retain fresh logs.
	$(call require,WORKSPACE_ROOT)
	@selectors="$$($(PYTHON) tools/aot_test_inputs.py environment --manifest $(call quote,$(AOT_INPUTS)/manifest.json))"; \
	while IFS='=' read -r key value; do \
	  case "$$key" in LSF_AOT_*) export "$$key=$$value" ;; esac; \
	done <<< "$$selectors"; \
	mkdir -p $(call quote,$(WORKSPACE_ROOT)); \
	mkdir $(call quote,$(TEST_REPORTS)); \
	source_commit="$$(git rev-parse --verify HEAD)"; \
	GITHUB_SHA="$$source_commit" $(PYTHON) tools/ci_suite_discovery.py --inventory $(call quote,$(WORKSPACE_INVENTORY)) --receipt $(call quote,$(TEST_REPORTS)/discovery.json); \
	$(PYTHON) tools/ci_cargo.py run workspace-tests 2>&1 | tee $(call quote,$(TEST_REPORTS)/workspace-tests.log); \
	$(PYTHON) tools/ci_suite_discovery.py --execution-log $(call quote,$(TEST_REPORTS)/workspace-tests.log); \
	$(PYTHON) tools/ci_cargo.py run doctests 2>&1 | tee $(call quote,$(TEST_REPORTS)/doctests.log); \
	$(PYTHON) tools/ci_suite_discovery.py --recipe explicit-doctests --execution-log $(call quote,$(TEST_REPORTS)/doctests.log); \
	$(PYTHON) tools/ci_cargo.py run signing-compatibility 2>&1 | tee $(call quote,$(TEST_REPORTS)/signing-compatibility.log); \
	$(PYTHON) tools/ci_suite_discovery.py --recipe signing-compatibility --execution-log $(call quote,$(TEST_REPORTS)/signing-compatibility.log)

##@ Contracts, clients and fixtures (explicit preparation may build/install inputs)
repository-tests: ## Run the complete Python suite with its declared Linux prerequisites.
	$(PYTHON) -m unittest discover -s tools/tests

contracts: ## Run all maintained contract lanes; owns shared generated fixtures.
	bash tools/validate_contracts.sh all

contracts-python contracts-bindings contracts-runtime contracts-standalone contracts-sdk-provider contracts-measurements: ## Run one named contract lane; no implicit lane widening.
	bash tools/validate_contracts.sh $(@:contracts-%=%)

sdks: ## Run the six external-client SDK validators; separate from guest qualification.
	bash tools/validate_sdks.sh

echo-capsule: ## Explicitly build the maintained echo fixture.
	$(PYTHON) tools/build_echo_capsule.py

echo-capsule-reproducibility: ## Require byte identity from two isolated clean echo builds.
	$(PYTHON) tools/build_echo_capsule.py --verify-reproducible

validate-preflight:
	$(call require,WORKSPACE_ROOT)
	@if [[ -e $(call quote,$(TEST_REPORTS)) ]]; then printf '%s\n' 'Test reports already exist; select a fresh WORKSPACE_ROOT under target/.' >&2; exit 2; fi
	@state="$$(git status --porcelain --untracked-files=no)"; \
	if [[ -n "$$state" ]]; then printf '%s\n' 'Broad AOT validation requires a clean tracked checkout; use focused test targets while editing.' >&2; exit 2; fi

validate: validate-preflight validate-source check-rust contracts sdks workspace-prepare aot-prepare test ## Run the broad clean-checkout Linux aggregate; excludes website and release campaigns.

##@ Website (prepared repository npm; no implicit installs in validation)
website-prepare: ## Explicitly prepare pinned npm and install locked website dependencies.
	$(PYTHON) website/toolchain/prepare.py
	$(BOOTSTRAP_NPM) ci --prefix website/toolchain --ignore-scripts --no-audit --no-fund
	$(NODE) website/scripts/check-package-manager.mjs
	PATH="$(CURDIR)/website/toolchain/node_modules/.bin:$$PATH" $(WEBSITE_NPM) ci --ignore-scripts --no-audit --no-fund

website-toolchain-check:
	$(NODE) website/scripts/check-package-manager.mjs

website-check: website-toolchain-check ## Check website sources and TypeScript without a production build.
	PATH="$(CURDIR)/website/toolchain/node_modules/.bin:$$PATH" $(WEBSITE_NPM) run check

website-test: website-toolchain-check ## Run website unit tests without installing dependencies.
	PATH="$(CURDIR)/website/toolchain/node_modules/.bin:$$PATH" $(WEBSITE_NPM) test

website-build: website-toolchain-check ## Build the project-mount production site.
	PATH="$(CURDIR)/website/toolchain/node_modules/.bin:$$PATH" $(WEBSITE_NPM) run build

website-build-root: website-toolchain-check ## Build the root-mount production site.
	PATH="$(CURDIR)/website/toolchain/node_modules/.bin:$$PATH" $(WEBSITE_NPM) run build:root

website-test-build: website-toolchain-check ## Check both built sites and browser journeys; no implicit build/browser install.
	PATH="$(CURDIR)/website/toolchain/node_modules/.bin:$$PATH" $(WEBSITE_NPM) run test:build

website-browser-install: website-toolchain-check ## Explicitly install the pinned browser used by website checks.
	PATH="$(CURDIR)/website/toolchain/node_modules/.bin:$$PATH" $(WEBSITE_NPM) run browser:install

website-validate: website-check website-test website-build website-build-root website-test-build ## Run website source/unit/both-mount/build/browser validation after preparation.
