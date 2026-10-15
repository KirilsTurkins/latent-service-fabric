# Validation

Use this page to select checks for an LSF change and interpret their results.
Current selection comes from the reviewed test catalogue, command contracts and
workflows. Historical discovery counts, performance samples and acceptance
receipts keep their original source and environment; they are not today's test
inventory or proof of execution.

## Choose an execution boundary

Install the [pinned toolchain](docs/development/toolchain.md) for the selected
owner. The repository's native runtime/process profiles target Linux x86_64 with
the declared filesystem, sandbox and service prerequisites. The separate
[Windows portable capsule tests](docs/component-development/portable-tests.md)
run already compiled components under their supported subset; they do not
qualify Linux storage, isolated compilation, process accounting or a full node.

| Change or question | Maintained entry point |
| --- | --- |
| One Rust suite/case or a local failure | [Local test runner](docs/development/local-tests.md): list, plan, prepare, check, run and reproduce |
| Which checks does a change require? | [CI profiles](docs/development/ci-profiles.md), [suite inventory](docs/testing/ci-suite-inventory.md) and [execution lanes](docs/testing/ci-lanes.md) |
| Async timing, cancellation or resource races | [Deterministic tests](docs/development/deterministic-tests.md) and [testing invariants](docs/testing/invariants.md) |
| Test/fixture/child-process ownership | [Owned processes](docs/development/owned-test-processes.md), [AOT inputs](docs/development/aot-test-inputs.md) and [Cargo recipes](docs/testing/ci-cargo-recipes.md) |
| Docs, MDX, website or examples | [Website validation](docs/development/website.md) and [guide review](docs/development/phase3-guide-review.md) |
| Native/package/platform acceptance | [Native release gate](docs/development/native-release-gate.md) and [packaged developer qualification](docs/development/packaged-developer-qualification.md) |

## Select, prepare and execute

Start with read-only planning from the repository root:

```bash
python3 tools/test.py list --output json
python3 tools/test.py explain --suite latent-core.lib.latent-core
python3 tools/test.py plan --suite latent-core.lib.latent-core
python3 tools/test.py plan --suite process.angular-renderer
```

These commands read definitions and file presence. They do not compile, discover
executable tests, install tools or contact services. Inspect the recipe, exact
case selection, platform, resource class, prerequisites and execution support.
A suite's boundary label does not imply a narrow build: the current core library
uses `core-host`, while many other library suites still use the workspace recipe.
Presence of an input is not validation of its bytes or proof that a test passed.

For an installed Linux toolchain, this explicitly prepares and runs the core
library selection:

```bash
python3 tools/test.py prepare --suite latent-core.lib.latent-core --inventory target/local-tests/core.jsonl
python3 tools/test.py check --suite latent-core.lib.latent-core --inventory target/local-tests/core.jsonl
python3 tools/test.py run --suite latent-core.lib.latent-core --inventory target/local-tests/core.jsonl
```

Use `--case EXACT_NAME` consistently to select one case. `prepare` may build and
prepare registered fixtures; `check` validates inputs without executing tests.
`run` performs owned exact discovery and execution without an implicit build or
installation. Missing prerequisites, unsupported selections, zero/partial case
sets, unexpected ignores and failed cleanup cannot become a successful skip.
Some listed provider/custom selections still require the maintained owner named
by their plan rather than a bare libtest fallback.

Use a fresh owned inventory after source, lock, recipe or fixture changes.
Never select the newest executable from `target/`, copy another checkout's
inventory or treat a restored cache as test-result evidence. Compatible Cargo
artifacts and immutable prepared copies are consumed on their producing checkout;
mutable catalogs, compiler authority, provider state and resource counters remain
private to the actual test owner.

The [local runner guide](docs/development/local-tests.md#angularprovider-failure-reproduction)
describes redacted `latent.test-run.v1` diagnostics and `reproduce`. Exact replay
requires the recorded clean checkout and prepared byte identities. An explicitly
allowed changed-checkout rerun is labelled as such and retains the original
selection/fault. Reproduction never retries a failure until it passes.

## Timing, cancellation and physical ownership

Use committed readiness and the actual queue/lease/buffer state, not sleeps,
yield counts or an accepted cancellation request. Manual `TestClock`, Tokio time
and native/OS clocks are separate domains. Advancing one does not control another
or prove native retirement. Real watchdogs bound deadlocks; they are not readiness
witnesses and do not replace the subsystem's original deadline.

Low-level helpers live in `latent-core`'s opt-in `test-support` feature. The
neutral `latent-test-process` crate owns real child/resource helpers;
`latent-testkit` re-exports the same types for higher-level harnesses. Preserve
the workspace dependency DAG rather than importing the runtime harness into its
own dependencies. The [deterministic guide](docs/development/deterministic-tests.md)
owns the helper contracts and focused regression commands.

A dropped waiter or successful child exit is not physical cleanup proof. Join
actual owners and check retained resources. Selected Python process runners use
the Linux subreaper contract, finite total deadlines, private fixtures and
identity-bound readiness/retirement. Unsupported accounting is unavailable,
not fabricated zero usage. Fault controls must fail as intended; they cannot
substitute for the corresponding successful product run.

## Runtime, state and application coverage

Each row identifies owners and required evidence, not a declaration that every
profile or acceptance gate has passed at the current head.

| Boundary | Coverage and qualification entry point |
| --- | --- |
| Runtime ownership | [Invariants](docs/testing/invariants.md): admission, fairness, fixed cells, fresh Stores, budgets, cancellation, cleanup and quarantine |
| Contracts and source | [Contract lanes](docs/testing/ci-lanes.md): WIT/Protobuf/schema validation, generated bindings, repository checks and the complete Python suite |
| Transactions and recovery | [State/effects](docs/architecture/state-and-effects.md), [engine qualification](docs/testing/transaction-store-engine.md) and [installed recovery](docs/testing/installed-transaction-recovery.md): model/engine, atomic command outcomes, OCC, fresh queries, inbox/outbox, retention, epochs and explicit reconciliation |
| Installed native/application state | [Installed runtime](docs/development/installed-transaction-rpc.md), [Java qualification](docs/testing/java-transaction-qualification.md) and [transaction clients](docs/development/transaction-clients.md): authenticated signed components, current result/dispatch authority, HTTP delivery and terminal/pending recovery programmes |
| Providers and browser delivery | [Provider/renderer lanes](docs/testing/ci-lanes.md), [standard HTTP controls](docs/testing/standard-http-conformance.md) and [browser application](docs/testing/sdk-browser-application.md): real services/components, negative controls, ownership, static/Angular delivery and hydration |
| Guest authoring | [Guest SDKs](docs/component-development/guest-sdk.md): six separate compiled language profiles, signed admission, actual execution and resource retirement |
| External clients | [SDK profile](sdk/profile/README.md) and [provider workflow](docs/testing/sdk-provider-workflow.md): six native transports, shared wire vectors, original identity/recovery, cancellation and response ownership |
| Security | [Security baseline](docs/development/security-baseline.md): separately selected advisory, secret, source/workflow and canary coverage |

A model schedule, compiler capture, controlled peer, portable guest, embedded
engine and signed live-node/browser programme establish different boundaries.
In particular, Phase 4's native/application/packaged gates and the ADR-0062
[restore identity variance](adr/0062-host-own-serializable-transactions-and-durable-outcomes.md#implementation-status-and-restore-identity)
remain explicit. Build/discovery or a small engine fixture cannot close them.

## Package and delivery validation

Package/policy/artifact/catalog/audit owners test exact evidence association,
current admission/revocation, durable receipts, caller preconditions, route pins,
pagination and restart. Provider and renderer integrations additionally require
their real service/component preparation and cleanup owners. Use the registered
plan and [AOT preparation guide](docs/development/aot-test-inputs.md) rather than
copying a raw Cargo filter that bypasses those prerequisites.

The [bounded operator workflow](docs/development/standalone-quickstart.md#bounded-phase-2-operator-workflow)
prepares current CLI/node binaries, a pinned TLS registry and signed fixtures,
then checks transfer, independent admission, deployment/rollout/rollback,
original-operation recovery, audit and restart. Synthetic signing fixtures prove
their protocol scope; [observed build provenance](docs/reference/build-provenance.md)
has its own input-capture evidence. A successful local package build grants no
publisher or execution authority.

## CI profiles and required results

The [classifier](tools/ci_profile.py) reads the complete Git change and actual
workspace dependency graph. Profiles are:

| Profile | Selected obligations |
| --- | --- |
| `docs` | Approved prose/SVG/known issue forms; docs and website validation |
| `website` | Reviewed website/MDX inputs; docs and full website types/unit/build/browser checks |
| `fast` | An entirely eligible reverse-dependent source closure; docs, website, selected host correctness and selected MSRV checks |
| `full` | Runtime-sensitive, shared/build/manifest/evidence, unknown or unavailable-history changes; the full job set plus the selected host correctness job |

The host-only decision is graph-derived, not a permanent promise about a crate.
Current state/core changes select full validation; an isolated workflows change
can select `fast`. A host pass is additional feedback when full CI is selected.
Do not replace the classifier's package list with an old five-package example.

The full `rust` matrix has checks, tests, qualification, provider,
renderer-public, renderer-angular, publications and angular-t1 variants. Contracts
have Python, bindings, runtime, standalone, SDK-provider, measurement-smoke and
optimization-smoke variants. Each producing runner owns fresh native inputs;
inventories and mutable fixtures stay with their producing jobs. Dependency
caches may reuse compilation; execution and qualification remain fresh results.
Workspace ordinary tests, exact custom harnesses, separate doctests and signing
compatibility retain distinct result checks. [Execution lanes](docs/testing/ci-lanes.md)
and [performance records](docs/development/ci-performance.md) own the layout.

`CI result` independently checks the expected jobs from the selected profile.
Missing, failed, canceled or unexpectedly skipped jobs fail it. Superseded runs
are canceled. The separate security aggregate and branch/release review remain
independent. Cache reuse and shorter elapsed time cannot waive cases, limits,
negative controls, cleanup or qualification.

## Updating tests and command contracts

Rust targets/cases and explicit ignores live in [the catalogue](tools/ci/suites.json)
and additive [suite fragments](tools/ci/suites.d/). Workflow structure, ordered
commands, delegated owners and exact Python cases live in [command contracts](tools/ci/contracts/).
A renamed, newly ignored, unregistered or zero-test selection must fail visibly.
The [contract guide](docs/testing/ci-command-contracts.md) explains scoped proposals
and review; validation never silently regenerates or approves expectations.

```bash
python3 tools/ci_coverage.py
python3 tools/validate_docs.py
```

The coverage receipt observes selected source and reviewed contracts, not an
executed product suite. Follow [website development](docs/development/website.md)
for examples, immutable versions, both production mounts, rendered links and
browser/accessibility journeys. SVGs follow [the visual standard](docs/svg-style.md).
Automated checks do not replace the separate human guide review.

## Broad Linux validation and explicit campaigns

With the complete pinned Linux prerequisites installed, the existing broad
Makefile aggregate remains available:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

[The Makefile](Makefile) expands this to formatting, locked workspace checking,
Clippy, workspace tests, contract validation and SDK checks. It is not a synonym
for every Actions matrix, website/browser, packaged or native-release programme.
Contract preparation rewrites its generated output, so do not run competing
fixture writers against the same target root. Generators use `target/` or Cargo
`OUT_DIR`, never handwritten contract sources.

Normal checks do not run the ignored 100,000-release catalog campaign, full
scale/soak/profiling, manual Phase 3 resource matrix or release VM programmes.
CI's `run_catalog_scale` and `run_phase3_resources` inputs default to false.
Use the [measurement guide](docs/testing/phase-1-measurements.md),
[resource acceptance](docs/testing/phase3-resource-acceptance.md) and
[native release gate](docs/development/native-release-gate.md) for explicit
selection and suitable resources. Smoke checks establish collector/schema and
ownership behavior, not the complete measured campaign.

The [engineering records](docs/development/engineering-records.md) retain original
sources, failed attempts and accepted results. Record source/dirty state,
toolchain/recipe, host/filesystem, prepared identities, exact cases and actual
outcomes. Keep discovery, execution, physical retirement and acceptance separate.
Unavailable or unrun work is not a pass; a historical receipt never qualifies a
later source, unsupported platform, cluster behavior, production SLO or release.
