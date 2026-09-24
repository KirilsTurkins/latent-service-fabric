# Validation

Use this page to choose checks for a change to LSF and understand what their
results establish. The reviewed suite inventory and CI workflows determine the
checks for the current source; historical acceptance reports retain their own
tested revisions and environments.

## Entry point

Install the exact prerequisites in the [toolchain guide](docs/development/toolchain.md),
then run the normal Linux validation entry point:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

This checks formatting, the Rust workspace, Clippy, tests, contracts and SDKs.
Cargo commands use the committed lockfile. Generators write to `target/` or Cargo
`OUT_DIR`; they must not overwrite handwritten contract sources. Formatting is
checked with `cargo fmt --all --check`.

For focused work, start with [the local test runner](docs/development/local-tests.md).
It plans a registered suite or case, reports prerequisites, prepares inputs only
when explicitly requested, and executes without an implicit build. Its inventory
is shared with CI. A focused pass does not replace other checks selected by a
change to shared code, schemas or workflows.

Normal validation does not select the ignored 100,000-entry metadata and durable
catalog probes, full resource soaks, native profiling or release VM campaigns.
Those require explicit commands and suitable resources.

## What is validated

| Area | Coverage and reference |
| --- | --- |
| Toolchains and source | Exact compiler/dependency pins, locked builds, formatting, Clippy, generated-binding drift and source layout |
| Contracts | Protobuf lint/descriptors, WIT parsing and generated host/guest bindings, JSON Schema validation and bounded manifest decoding |
| Runtime ownership | Admission, tenant fairness, cancellation/deadlines, fixed cell capacity, affine leases, fresh guest state, budget accounting, cleanup and quarantine |
| Guest execution | Real Component Model fixtures, dynamic typed dispatch, capability calls, declared/platform errors, traps, memory/fuel limits, post-return failure and recovery |
| Storage and routing | Durable publication and deployment, integrity checks, supported-format rejection, caller preconditions, exact receipts, bounded pagination, restart and pinned routes |
| Package security | Package/evidence association, publisher and builder trust, current admission, revocation, compiler isolation and authenticated native cache ownership |
| Management and operation | Real CLI/node workflows, authenticated invocation/status/cancellation, audit, rollout/canary/rollback and bounded shutdown |
| Providers and web delivery | Capability authority, shared pools, resource closure, HTTP/static/Angular delivery, browser boundaries and owned asynchronous waits |
| External SDKs | Six-language profile semantics, wire validation and controlled native transport tests; separately maintained real-node workflows |
| Documentation | Markdown links/anchors, accessible local SVGs, generated website content, examples and browser journeys |

The detailed source of test selection is the
[suite inventory](docs/testing/ci-suite-inventory.md). The
[CI lanes](docs/testing/ci-lanes.md) and
[Cargo recipes](docs/testing/ci-cargo-recipes.md) explain execution ownership and
shared build inputs. See [testing invariants](docs/testing/invariants.md) when
adding coverage; tests must retain failure evidence and verify resource cleanup.

## Runtime regression commands

After installing prerequisites, these focused targets exercise core behavior
without selecting the expensive ignored probes:

```bash
cargo test -p latent-manifest --all-targets --locked
cargo test -p latent-core -p latent-executor -p latent-node --all-targets --locked
cargo test -p latent-node --test activation_lifecycle --locked
cargo test -p latent-scheduler --all-targets --locked
cargo test -p latent-wire --all-targets --locked
cargo test -p latent-artifacts -p latent-control-store --lib --locked
cargo test -p latentd --lib --locked
cargo test -p latentd --test standalone_node --test standalone_command --locked
cargo test -p latent --all-targets --locked
cargo test -p latentd --test catalog_scale --locked
```

Some integration cases require explicitly prepared components or binaries. Use
the registered runner's plan before selecting a case; missing prerequisites must
fail clearly instead of silently skipping the case or rebuilding in its timing
window. Linux-only tests establish Linux behavior; a Windows skip is not a pass
for filesystem synchronization, process supervision or compiler isolation.

For the fixed cell pool, tests check concurrent acquisition, bounded queues,
cancellation, stale/foreign leases, drop races and quarantine. The pool stores
slot identities and generation counters while idle; it does not allocate guest
stores, threads or sockets per dormant service.

## Package and delivery validation

These targets cover package, policy, storage, native-image, audit, delivery and
operator boundaries:

```bash
cargo test -p latent-packaging -p latent-signing -p latent-policy --lib --all-features --locked
cargo test -p latent-artifacts -p latent-control-store -p latent-audit -p latent-rollout --lib --all-features --locked
cargo test -p latent-telemetry -p latent-wire -p latentd --lib --all-features --locked
cargo test -p latent --all-targets --all-features --locked
cargo test -p latent-wire --test management_service --all-features --locked
cargo test -p latent-wasmtime --test native_aot_cache --all-features --locked
```

Native AOT cases require the Linux sandbox/compiler prerequisites in
[trusted AOT](docs/runtime/trusted-aot.md). For the separate-process CLI, registry
and node schedule, follow the
[operator workflow](docs/development/standalone-quickstart.md#bounded-phase-2-operator-workflow).
It explicitly prepares current binaries, a pinned TLS registry and fresh signed
fixtures before execution. The runner owns its disposable processes and registry;
it does not mount node catalogs into the CLI.

That workflow checks transfer, independent admission, deployment receipt
recovery, attributed invocation, staged promotion, rollback, audit and restart.
Synthetic signed fixtures test the security protocol; the separately maintained
[observed-build checks](docs/reference/build-provenance.md) establish actual
builder-input capture.

## Guest and client checks

Build the maintained echo fixture and optionally check two clean builds:

```bash
make echo-capsule
make echo-capsule-reproducibility
```

The fixture's component interface, generated manifest and actual digest are
validated. Its unsigned local-build status grants no publisher authority. The
same-host reproducibility check does not claim byte identity across toolchains
or platforms. [Guest SDK checks](docs/component-development/guest-sdk.md) add
signed admission, typed capabilities, resource ownership and real node execution.

Run maintained external client validation with:

```bash
make sdks
cargo test -p latent-sdk --locked
```

The [SDK profile](sdk/profile/README.md) shares selected wire vectors, unsigned
integer boundaries, identity/presence, cancellation, response ownership and
recovery semantics across Rust, C, TypeScript, Go, Java and C#. Native transport
tests cover bounded connections, failures, deadlines and shutdown. Semantic test
doubles and controlled peers establish different boundaries from an actual node;
the [provider workflow](docs/testing/sdk-provider-workflow.md) covers the latter.
Compiler identities are checked before compilation. Follow each SDK's own build
instructions for its generated artifacts and cleanup.

## Website and documentation

Follow [website development](docs/development/website.md) for installation, local
builds, navigation, examples and browser checks. Documentation links must resolve
within their selected source/version. SVGs must be accessible, local-only XML
with a title, description and viewBox; see [the visual standard](docs/svg-style.md).

Automated checks can detect broken links, example drift and interaction failures.
They cannot establish that a newcomer understands a guide. The maintainer's
[guide review](docs/development/phase3-guide-review.md) remains a separate human
review and must not be marked accepted by an automated or assistant audit.

## CI jobs

[CI profiles](docs/development/ci-profiles.md) select documentation or full
validation from the complete change. Approved prose/SVG-only changes receive
focused checks. Code, build inputs, evidence and workflow changes retain full
validation. `CI result` checks every selected job's result. Superseded runs for
the same ref are cancelled.

Full CI covers Rust formatting/tests/Clippy, MSRV, repository contracts, durable
catalog acceptance, SDKs, the website and the dependent OCI TLS integration.
Maintained fixtures and observed-build artifacts connect the relevant jobs.
[Dependency caches](docs/development/ci-caching.md) reuse build work without
skipping checks or treating a previous receipt as fresh evidence.

The durable catalog job's expensive 100,000-release publication/reopen step runs
only with manual `run_catalog_scale: true`; its default is false. Ordinary jobs
retain small integrity, restart, routing and probe-supervision regressions.

## Explicit measurement and release campaigns

The [measurement guide](docs/testing/phase-1-measurements.md) defines scale,
soak and benchmark campaigns. The normal contracts gate runs a small collector
smoke profile to check process ownership and result schemas. It cannot satisfy
full measurement acceptance. Full workloads use explicit commands:

```bash
python3 tools/run_phase1_measurements.py --profile full --kind scale
python3 tools/run_phase1_measurements.py --profile full --kind soak
python3 tools/run_phase1_measurements.py --profile full --kind benchmark
```

Scale reaches 100,000 durable releases/deployments. Soak uses three independent
processes with 100,000 measured calls each. Benchmark uses seven independent
release-build processes. Review the guide's prerequisites and resource limits
before running them. Container/hosted observations keep their recorded
environment and do not become native-host measurements.

The [native release gate](docs/development/native-release-gate.md) separately
requires exact build inputs, real VM installation/reboot/upgrade acceptance and
publisher approval. Ordinary CI alone does not authorize release publication.

## Historical evidence and scope

The [engineering records](docs/development/engineering-records.md) index previous
acceptance decisions. Historical spike collectors and their executable surface
have been retired. Receipts, raw archives, checksums and integrity/replay
validators remain so past claims can be checked. Reproducing such a workload
requires its recorded source revision, not today's development checkout.

A passing check establishes the behavior exercised by its inputs on its recorded
host. It does not establish unsupported platforms, hostile multitenant isolation,
cluster behavior, production SLOs or a completed release gate. Current regression
results, retained performance measurements and human acceptance have distinct
purposes; report each at its actual scope.
