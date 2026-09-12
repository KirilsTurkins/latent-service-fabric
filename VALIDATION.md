# Validation baseline

Updated on **2026-09-13** for completed Phases 1 and 2 and the Phase 1 performance extension,
the retained Phase 0 evidence, generated build
foundation, Phase 1 manifest validation, resource budgets/cancellation, durable
release and deployment catalogs, immutable local routing, admission, scheduling,
generic execution, activation capabilities/lifecycle, invocation and management
service adapters, standalone Linux node composition, Phase 2 package/OCI policy,
authenticated native caching, audit, staged rollout/canary/rollback and operator
workflows, and explicit heavy
validation gates. These commands describe validation coverage; the
[Phase 1 completion review](docs/phase-1-completion.md) and
[extension report](docs/phase-1-extension-completion.md) record the completed
decisions. The [September 7 audit](docs/development/feature-audit-2026-09-07.md)
is an earlier snapshot. The [Phase 2 completion review](docs/phase-2-completion.md)
records the collective gate decision and its retained evidence. Phase 3 providers
remain planned. Historical Phase 0/1 receipts below retain their recorded source
identities and do not validate newly added Phase 2 paths.

## Entry point

After installing the exact prerequisites in [`docs/development/toolchain.md`](docs/development/toolchain.md), a clean checkout is validated with:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

The command is intentionally non-mutating for authoritative sources. Formatting is checked with `cargo fmt --all --check`; generated bindings, descriptors, and capsule artifacts are written below `target/` or Cargo `OUT_DIR`.

Normal validation runs unit/integration regressions and contract/SDK checks.
It does not select the ignored 100,000-entry metadata index probe or the
durable 100,000-release catalog probe, or run native profiling, calibration,
or resource soaks. An eight-entry index fixture checks normal capacity
accounting without selecting the large probes. Heavy execution and durable scale evidence
require the explicit commands below.

## Phase 0 completion sequence

The clean-checkout Phase 0 sequence is:

```bash
make phase0-gate
```

It runs formatting, workspace build/lint/test, and SDK validation once, then the
real executable spike and containment suite and a new full executable baseline.
The outer gate no longer adds a third contract and repository-test pass before
the standalone spike and baseline runners perform their retained fixture gates.
It then writes a machine-readable `latent.phase0.gate.v3` receipt below
`target/phase0-gate/` after independently rebuilding the retained calibration,
profile, and soak aggregates from their raw artifacts and validating the fresh
baseline against them. A full command fails if the receipt is not `authorized`;
it never reports an incomplete or synthetic archive as a pass.

The retained [August 30 native-Linux receipt](benchmarks/phase0/receipts/native-linux-2026-08-30-b932a935/gate-summary.json)
records the fresh clean-checkout result: `pass`, `authorized`, and zero
blockers. It independently regenerates the current calibration, profile, and
soak inputs and binds them to the fresh baseline through one canonical
execution-evidence identity. Phase 1 is authorized to build on those runtime
invariants. The receipt remains explicitly non-production and non-Phase-1-API
compatible; the [August 29 receipt](benchmarks/phase0/receipts/native-linux-2026-08-29-54d02679/gate-summary.json)
is preserved as historical evidence only.

`make phase0-gate-smoke` runs the same code/contract/executable sequence with
the deterministic smoke baseline. It records the receipt for CI but does not
turn a smoke run into Phase 1 authorization; its output reports smoke
validation and authorization as separate states.

| Command | Baseline | Successful exit establishes | Authorizes Phase 1? |
| --- | --- | --- | --- |
| `make phase0-gate` | full | A current full receipt is `authorized`. | Yes, and only if the receipt says `authorized`. |
| `make phase0-gate-smoke` | deterministic smoke | Deterministic validation coverage completed. | No; a `blocked` receipt can accompany a successful smoke run. |

The full gate evaluates clean-worktree status with
`git status --porcelain --untracked-files=all`. Its own output below the root
`target/` directory is ignored; other untracked files can block authorization.
Run it from an isolated clone or worktree when local build output is present.

## What is validated

- The committed root `Cargo.lock` contains the selected direct dependency versions and is consumed unchanged by every Cargo command with `--locked`; CI does not generate or substitute a dependency graph.
- The pinned Rust toolchain, MSRV, target, direct dependency versions, Python requirements, and CI tool versions remain synchronized.
- Every Rust workspace target compiles, passes Clippy, and runs its tests using the committed lockfile.
- The fixed execution-cell pool tests cover startup-fixed capacity, concurrent acquisition limits, bounded FIFO rejection, duplicate activations and returns, modified and foreign lease identities, explicit cancellation, deterministic deadline expiry with an injected wall clock, queued-future drop before release, explicit and drop-triggered quarantine, unaccepted handoff reclamation, token-sequence exhaustion, and barrier-controlled multi-threaded release/cancellation and release/task-abort races.
- Manifest tests cover schema-backed decoding, document/depth/collection bounds, duplicate-key rejection, exact JSON numbers, canonicalization, Rust round trips, and unsupported Phase 1 semantic combinations.
- Budget and cancellation tests cover effective deadlines, concurrent consumption/reservations, final accounting, unsupported dimensions, cancellation-versus-terminal races, and registry cleanup.
- `activation_lifecycle` composes real admission and scheduling with tiny controlled catalog/artifact/backend fixtures. It checks immediate identity, lineage and tenant scope, bounded terminal retention, pinned routing keys/revisions, ordered terminal outcomes, cancellation/drop/panic cleanup across stages, and concurrent identity/terminal races. The tests use five-second completion watchdogs and verify affine preparation, cell, quota, and registration cleanup; see [local lifecycle](docs/activation-lifecycle.md).
- Release-catalog tests cover immutable publication, component digest verification, metadata syntax/semantic validation, bounded indexes/listing/recovery, exclusive ownership, interrupted writes, indeterminate durability, retry, and reopen behavior. Root-initialization tests inject failures at every ancestor synchronization, verify complete retry ordering for existing and relative paths, and preserve a tiny published release across failed open and restart. An isolated process verifies that working-directory changes cannot redirect a handle away from its locked catalog. Tiny integrity fixtures cover valid-JSON metadata changes, damaged or mismatched versioned completion records, byte-preserving legacy rejection, interrupted staging and verification before index adoption, including the pending-publication mutation gate.
- Deployment/routing tests cover tenant/namespace isolation, deterministic revisions/weighting, pinned snapshots, concurrent publication, integrity and size bounds, initialization durability, restart recovery, and bounded resource/memory regressions. Versioned mutations test atomic caller preconditions, competing writers, delete/recreate, exact receipts and persisted object stamps. Tiny scoped-pagination fixtures count selected/cloned records, verify no artifact fetches, and cover byte boundaries, continuation order, token scope and expiry. Supervised isolated processes change working directories after open and during suspended initialization, verifying that the original locked root receives its initialization marker and mutations while a second live catalog remains unchanged.
- An integration test implements `CellPool` outside `latent-scheduler` using only the original required trait methods, mints an affine lease through `CellLease::new`, and proves that the issuer-retained `CellLeaseLifecycle` capability can disposition or observe abandonment without access to `FixedCellPool` internals.
- The runtime WIT world is staged with all platform dependencies; every platform and example WIT package is parsed by `wasm-tools`; generated Wasmtime host bindings and `wit-bindgen` guest bindings compile.
- The Rust echo guest returns normal input unchanged and its shared implementation tests cover `empty-message`, `message-too-large`, the exact 65,536-byte boundary, UTF-8 byte accounting, and bounded activation-ID logging data.
- The executable echo guest is built as a self-contained `wasm32-unknown-unknown` core with generated WIT bindings and wrapped with `wasm-tools component new`. The separate `wasm32-wasip2` build checks binding compatibility. `wasm-tools validate` accepts the executable component, and its extracted root world must import exactly `latent:context/context@0.1.0` and `latent:log/log@0.1.0` and export exactly `examples:echo/api@0.1.0`.
- The extracted component interface contains the exported `echo` function and both declared domain-error variants. Any ambient WASI import, missing import, or unexpected export fails validation.
- Two isolated clean echo builds must be byte-identical. A generated capsule manifest, build receipt, and SHA-256 file record stable metadata, local-build trust, the documented reproducibility boundary, and the computed component digest beneath `target/capsules/echo/`.
- The generic Wasmtime suite builds a separate maintained Rust component and tiny WAT adversarial components. It checks dynamic contract/function selection, canonical scalar/composite values, declared versus nested errors, missing imports/exports and unsupported types, pre-store input rejection, bounded output, fresh guest state, short fuel/deadline/cancellation/memory containment, post-return failure, recovery, and explicit cleanup. These small fixtures are ordinary contract regressions; they do not run a resource soak or establish the Phase 1 gate. See [generic execution](docs/runtime/wasmtime.md).
- The capability suite builds a separate Rust/WIT component importing only context, logging, and monotonic/wall clocks. It checks filtered context and pinned identity across cell reuse, live shared fuel/memory/log accounting, injected clock adjustments and monotonic clamping, complete escaped record byte limits, reserved/invalid fields, and failed-sink reservation refunds. Each small invocation has a five-second watchdog and cleanup checks. See [activation capabilities](docs/runtime/capabilities.md).
- Shared telemetry tests use tiny bounded queues and local sinks to check redaction, correlated distinct outcomes, finalized consumption, pinned revisions, monotonic duration, overlapping activation-ID incarnations, failed/full exporters, and bounded shutdown. Node integrations cover lifecycle/drop observations and inventory sources without catalog enumeration. See [telemetry and inventory](docs/telemetry.md).
- `invocation_service` calls generated Invoke/Cancel/GetActivation methods against a real manager, admission controller, and scheduler. Bounded fixtures cover principal and lineage validation, pending/retained status, scoped cancellation, drop/deadline cleanup, outcome accounting, absent/pinned receipts, redaction, and cell/ID reuse. See [invocation service](docs/protocol/invocation-service.md).
- `management_service` uses generated Tonic clients over an in-memory duplex transport and real local catalogs. Tiny fixtures publish typed contract metadata, deploy the published release, verify atomic version receipts and scoped pagination, inspect complete tenant route projections, and require a trusted node operator for inventory. Rejections cover authentication, tenant mismatches, output authority claims, byte limits, stale tokens/generations, and unsupported clustered methods. Catalog and conversion unit tests cover precharged allocation limits, lossless observations, scoped digest integrity, and bounded error redaction. See [management services](docs/reference/management-services.md).
- All Protobuf files pass Buf lint and generate a deterministic file-descriptor set.
- JSON Schemas pass Draft 2020-12 meta-schema validation, and checked-in capsule, deployment, release-publish, binding, policy, trigger, and compiled-route examples validate against their corresponding schemas.
- Rust, Go, TypeScript, Java, .NET, and C SDK interfaces compile and execute small fake-client identity/cancellation fixtures. They cover status/cancellation before invoke completion, transport failures, lost-response status recovery, optional identity and lineage; see the [SDK contract](sdk/README.md#executable-contract-fixtures). These are contract tests, not implemented transport coverage.
- SDK compiler identities are verified before compilation, including Eclipse Temurin 21.0.11+10 and Zig 0.16.0 with its Clang 21.1.0 frontend targeting `x86_64-linux-gnu`; the runner-provided C compiler is not used.
- Generated directories are excluded from repository traversal without excluding malformed authoritative source files.
- Source-controlled SVGs are parsed as accessible, local-only XML: each requires a
  descriptive title and description, `role="img"`, a `viewBox`, and no active,
  remote, or embedded content. The shared visual standard is
  [docs/svg-style.md](docs/svg-style.md).
- Deterministic test IDs, manual time, temporary workspaces, and a current-thread future executor are covered by Rust unit tests.
- The Phase 0 gate receipt rejects omitted, duplicate, unexpected, or failed baseline checks; missing required terminal scenarios; a dirty executable shutdown/topology result; malformed, unsafe, incomplete, or altered raw archives; unverified calibration/profile measurements; weakened optimization guardrails; free-form optimization decisions; stale execution evidence; and incomplete resource evidence represented as an authorization.

## Phase 2 focused validation

Use the pinned prerequisites and committed lockfile. These focused commands
exercise implemented package, policy, storage, native-image, audit, delivery and
operator boundaries without selecting catalog scale or performance campaigns:

```bash
cargo test -p latent-packaging -p latent-signing -p latent-policy --lib --all-features --locked
cargo test -p latent-artifacts -p latent-control-store -p latent-audit -p latent-rollout --lib --all-features --locked
cargo test -p latent-telemetry -p latent-wire -p latentd --lib --all-features --locked
cargo test -p latent --all-targets --all-features --locked
cargo test -p latent-wire --test management_service --all-features --locked
cargo test -p latent-wasmtime --test native_aot_cache --all-features --locked
```

Native AOT integration requires the documented Linux x86_64 sandbox and compiler
prerequisites in [trusted AOT](docs/runtime/trusted-aot.md); unsupported hosts do
not establish successful isolation or native loading.

The tests cover exact package/evidence association, publisher/builder policy and
runtime compatibility, lifecycle cutover and denied recovery, authority-free raw
cache pressure, authenticated native receipt/image ownership, durable audit
query/control leases, exact rollout and managed deployment transactions, canary
loss and attribution, rollback target validation, and CLI response association.
Ordinary Rust/SDK/schema checks remain required; no single listed target replaces
the workspace or contract checks.

For the actual separate-process CLI, registry and node schedule, follow the
[bounded operator workflow](docs/development/standalone-quickstart.md#bounded-phase-2-operator-workflow).
It explicitly builds current binaries, fetches the pinned TLS registry image,
and selects only the ignored `export_operator_workflow_fixture` test into a new
directory. Run the workflow immediately with that fresh signed fixture. The
runner itself builds nothing, never mounts node catalogs into the CLI and owns
its disposable process/registry resources. It rejects stale fixtures and missing
prerequisites.

That schedule checks two compatible packages, exact OCI/evidence transfer,
independent node admission, deployment receipt replay/lookup, actual attributed
invocation, manual and canary stages, explicit rollback, audit pagination,
interrupted-result inspection and restart. Its bounded
`latent.operator.workflow-test.v1` result is integration evidence, not a benchmark
or a completion receipt. Its fresh publisher and builder signatures bind
synthetic test observations; they do not establish an actual production build.
Observed-build provenance has its separate maintained integration.

The [Phase 2 completion review](docs/phase-2-completion.md) combines those
dependency checks with three real native-currentness tests: proof-age expiry,
policy expiry and publisher revocation each deny retained preparation, final
start and persistent-cache reopen without another compile or load. The separate
[offline schedule](docs/testing/phase-2-offline-validation.md) records a failed
new registry pull, successful eligible local execution, then denial after local
revocation while the registry remains stopped.

The fixed [resource profile](docs/testing/phase-2-resource-profile.md) retains
32 signed releases, 16 deployments, two warmed portable images, 32 successful
Invokes and 12 OS samples, with transient ownership returning to zero and actual
worker joins/process reap. Its final collector and validator checks passed
35/35. The [compact evidence set](benchmarks/phase2/2026-09-13/README.md) preserves
source and binary identities, finite limits, failed/superseded attempts and the
WSL2 host boundary. This is no new 100k-scale or production SLO claim; historical
Phase 1 scale/soak reports retain their original measurement scope.

## Echo fixture commands

Build and validate one generated fixture:

```bash
make echo-capsule
```

Run the two-build digest stability check explicitly:

```bash
make echo-capsule-reproducibility
```

The artifact remains generated rather than checked in. The generated `capsule.json` starts from the checked-in contract example but replaces its placeholder digest with the actual `sha256:` content digest and marks the artifact as an unsigned local clean build.

## Fixed cell-pool command

Run the focused scheduler test target explicitly:

```bash
cargo test -p latent-scheduler --all-targets --locked
```

The pool itself creates no runtime, operating-system thread, listener, socket, connection, component instance, store, or memory. Queued acquisition and deadline timers execute on the caller-provided shared Tokio runtime.

## Phase 1 focused regression commands

After installing the pinned toolchain, these commands exercise the implemented
foundations without selecting expensive ignored acceptance probes:

```bash
cargo test -p latent-manifest --all-targets --locked
cargo test -p latent-core -p latent-executor -p latent-node --all-targets --locked
cargo test -p latent-node --test activation_lifecycle --locked
cargo test -p latent-wire --all-targets --locked
cargo test -p latent-artifacts -p latent-control-store --lib --locked
cargo test -p latentd --lib --locked
cargo test -p latentd --test standalone_node --test standalone_command --locked
cargo test -p latent --all-targets --locked
cargo test -p latentd --test catalog_scale --locked
```

The CLI's ordinary tests cover local command processes, strict inputs/profiles,
exact receipts, deadline/drop ownership, error categories, and response bounds.
`make contracts` also builds both binaries and runs two supervised CLI/node
workflows with the generated echo/generic fixtures: ten total guest activations,
small publication/pagination cases, durable restart, declared errors, trap,
deadline, explicit Cancel, local Ctrl-C, output-file failure, and clean shutdown.
Those fixture tests require explicit `LSF_LATENTD_BIN`, `LSF_ECHO_COMPONENT`,
`LSF_GENERIC_COMPONENT`, and `LSF_GENERIC_FIXTURES`; they never silently build or
skip a missing prerequisite. See the [CLI reference](docs/reference/operator-cli.md)
and [scriptable quickstart](docs/development/standalone-quickstart.md).

The final command runs catalog-probe supervision tests. The durable
100,000-release publication/reopen probe requires `--ignored` and its exact test
name; see [the catalog acceptance instructions](docs/development/local-release-catalog.md).
That probe is also available through manual dispatch of `CI` with
`run_catalog_scale: true` (default `false`). Ordinary pull requests, pushes,
and default dispatches run catalog recovery/routing/supervision regressions
without the heavy probe.

The `latentd` library tests cover bounded configuration, command/status output,
pressure parsing and transport ownership. On Linux, `standalone_node` opens a
real loopback listener and checks authentication, inventory and empty restart.
Its separately ignored component case publishes a tiny real echo release,
deploys and invokes it across durable restart, and checks actual cleanup. After
building the maintained echo fixture, select that bounded case with:

```bash
LSF_ECHO_COMPONENT=target/capsules/echo/echo-capsule.wasm \
  cargo test -p latentd --test standalone_node --locked -- --include-ignored
```

The ordinary `standalone_command` target runs real node processes through invalid
configuration, corrupt catalog, SIGTERM and Ctrl-C scenarios. The contracts gate
also builds the tiny generic `standalone_shutdown/spin.wat` fixture and runs the
ignored `standalone_shutdown` target with `LSF_SHUTDOWN_COMPONENT`. That test
observes one running guest and one queued activation, then checks their actual
cleanup after a 20 ms drain interval. It uses two activations and an external
watchdog; no Phase 0 payload controls are involved.

The integration children have finite supervision deadlines. These commands do
not select the catalog scale probe or a resource soak. See
[standalone operation and shutdown evidence](docs/reference/standalone-node.md).

## Phase 1 measurement collectors

The contracts gate also runs the separate tiny scale/soak/benchmark collector
smoke profile. It validates collection, process ownership and result schemas;
it cannot satisfy full measurement acceptance. See the
[measurement guide](docs/testing/phase-1-measurements.md) for exact work counts,
resource limits, artifacts and comparison rules.

With maintained fixtures built, full workloads are explicit:

```bash
python3 tools/run_phase1_measurements.py --profile full --kind scale
python3 tools/run_phase1_measurements.py --profile full --kind soak
python3 tools/run_phase1_measurements.py --profile full --kind benchmark
```

Scale observes 100, 1,000, 10,000 and 100,000 durable releases/deployments.
Soak uses three independent processes with 100,000 measured calls each.
Benchmark uses seven independent release-build processes. The
[manual workflow](.github/workflows/phase1-measurements.yml) defaults to smoke
and retains available failure diagnostics. Container/hosted results retain
their environment; they are not silently promoted to native comparison data.

The [controlled comparison](docs/testing/phase-1-controlled-comparison.md) separately
runs historical and current semantic Echo workloads in alternating process pairs.
Its [explicit workflow](.github/workflows/phase1-controlled-comparison.yml) defaults
to smoke. Full mode uses seven pairs of 40 warmup and 400 measured calls per arm;
it does not repeat scale or soak workloads or replace the retained native reference.

## Native-Linux Phase 0 calibration

The deterministic smoke profile and normal validation suite protect correctness.
The native-Linux calibration is a heavier explicit benchmark command and is not
part of normal shared CI:

~~~bash
tools/run_phase0_calibration.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  --published-source-ref <durable-branch-or-tag> \
  /var/tmp/phase0-evidence/calibration
~~~

It runs the complete Phase 0 full profile at least seven times from one clean,
pushed source commit/tree and retains raw output outside the source tree,
invariant results, host provenance, and an aggregate report. The runner
requires a durable remote ref, verifies commit/tree reachability from that
ref, and records both the declared ref and resolved ref head. A missing
fixture, failed hard invariant, missing or unexpected invariant name, or
duplicate invariant name invalidates the calibration; it is never filtered
based on timing or resource values.

The checked-in [August 30 aggregate](benchmarks/phase0/calibration/native-linux-2026-08-30-52ac4754/aggregate.json)
is the seven-run calibration input verified by the authorized receipt. The
August 29 aggregate remains historical. Hosted CI must not treat either
package's machine-specific microbenchmark bands as a pass/fail gate. See
[docs/phase-0-baselines.md](docs/phase-0-baselines.md) for comparison and rerun
rules.

## Native-Linux Phase 0 hot-path profiling

Issue 40 provides a separate, manual evidence command for symbolized CPU and
allocation/copy profiling. It is intentionally excluded from shared CI and
requires a clean native-Linux host or VM plus the open-source `perf`,
`heaptrack`, and `heaptrack_print` utilities:

~~~bash
tools/run_phase0_hot_path_profiles.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  --published-source-ref <durable-branch-or-tag> \
  --calibration-aggregate /var/tmp/phase0-evidence/calibration/aggregate.json \
  /var/tmp/phase0-evidence/profiling
~~~

The command refuses WSL, detected containers, unclean source, missing tools,
source-tree mismatch, a stale or malformed calibration, missing raw profile
artifacts, and failed Phase 0 hard invariants. The calibration must be a fresh
seven-or-more-run native-Linux aggregate whose sibling raw runs regenerate the
same record for the declared published commit/tree; the runner has no fallback
to the historical checked-in aggregate. It retains the exact commands, `perf.data`, symbolized `perf`
reports, Heaptrack data/reports, full baseline raw output, host context, and a
bounded worker/cell, allocator, and COW experiment matrix. Heaptrack allocation
attribution uses the leaf-nearest non-plumbing owner frame; a category with no
direct sample is reported as not observed at profiler resolution, not as a
zero-cost result. The aggregation test is deterministic and may run in CI; the
host-sensitive profile command may not. See [docs/phase-0-hot-path-profiling.md](docs/phase-0-hot-path-profiling.md)
for the evidence interpretation, adoption rule, and Phase 1 handoff.

The retained August 30
[`native-linux-2026-08-30-52ac4754`](benchmarks/phase0/profiling/native-linux-2026-08-30-52ac4754/README.md)
package is the v5 profile input verified by the authorized receipt. It covers
all eight required workloads and candidates, retains the complete invariant
proof, and makes no production or cross-machine performance claim. The August
29 package remains historical archive-regression evidence.

## Native-Linux long-running resource soak

The issue 39 resource plateau probe is also explicit heavyweight work, not a
shared CI job. A replacement or revalidation run must use the final Phase 0
configuration from a clean native Linux host or VM and a durable source
commit/tree:

```bash
tools/run_phase0_resource_soak.sh \
  --published-source-commit <reachable-final-commit> \
  --published-source-tree <reachable-final-tree> \
  --published-source-ref <durable-branch-or-tag> \
  --final-configuration-commit <reachable-final-commit> \
  --calibration /var/tmp/phase0-evidence/calibration/aggregate.json \
  /var/tmp/phase0-evidence/soak
```

It rejects WSL, containers, unavailable process probes, fixture/toolchain
failure, dirty or mismatched source trees, missing raw batch samples, and a
pre-final/test-only invocation. It preserves at least three full raw processes,
each with 1,000 warm-ups excluded from analysis, 100,000 measured fresh-store
activations, all failure/recovery paths, and frequent real capacity/queue
saturation. Its aggregate revalidates every hard check and every batch's
logical-resource baseline, reports rolling ranges/final deltas/Theil-Sen late
slopes/peaks and explicit release/shutdown state, rejects both measured-window
and release-to-shutdown FD growth, and for new archives verifies that the final
measured FD count stays within a post-warm-up baseline while release/shutdown
return within a pre-runtime baseline. It reconciles raw process environment
against before/after host observations and applies #38's calibrated RSS band
for RSS/PSS/private material-growth triage only after CPU, memory, kernel,
virtualization, toolchain, allocator, fixture, and relevant configuration
identity—including prepared-cache enablement, Wasmtime allocator mode, and
initialized-memory COW—are proved matched. A mismatch or missing identity
blocks the comparison and authorization; it is never a reason to raise an
allowance.

The authorizing August 30 final-configuration raw result is
[`native-linux-2026-08-30-52ac4754`](benchmarks/phase0/soak/native-linux-2026-08-30-52ac4754/README.md):
three complete 100,000-activation processes from durable source commit
`52ac47542a05c0a1263f78a14c04a5c2e6b761f3` and tree
`cac3ececdbd0b5734691c30c0283fccff169a5f5`. Its raw hard invariants,
raw/host identity reconciliation, descriptor lifecycle, release/shutdown
topology, and matched-calibration late-window analysis pass. The lossless zstd
archive and its per-file manifest retain all raw process evidence without
duplicating earlier attempts. The package is evidence input, not an
authorization decision by itself; the retained full Phase 0 receipt verifies
it together with every other required input. The August 29 result remains
historical.

## CI jobs

Normal pull requests use two automated workflows. `CI` runs formatting,
workspace compilation, generated binding checks, Clippy, tests, the MSRV check,
repository/contract validation, the reproducible echo component build, and all
SDK surfaces. Its core Rust job also retains the strict `latentd` Clippy policy
that previously lived in an issue-specific workflow. Superseded runs for the
same ref are cancelled.

The `Durable catalog acceptance` job runs ordinary artifact, deployment/routing,
and catalog-probe supervision regressions. Its expensive 100,000-release
publication/reopen step and retained scale logs are enabled only by manual
dispatch with `run_catalog_scale: true`; the default is `false`.

`Phase 0 runtime regression` is path-filtered to execution-relevant sources. It
runs the deterministic executable baseline smoke and then the ignored
`latentd` outcome/recovery matrix against the already-built fixtures. The job
also syntax-checks the retained Phase 0 runners and uploads its raw measurements
and report. It does not repeat the full workspace formatting, compilation,
Clippy, test, MSRV, or SDK matrix.

`Phase 0 full validation` is manual-only. Its `workflow_dispatch` input selects
the full authorization gate or the deterministic smoke gate from a clean,
full-history checkout. The completed Phase 0 reference evidence is no longer
auto-refreshed or committed by a pull-request workflow.

A completed validation failure is evidence that the executable interface
baseline needs investigation; a job that fails before its steps run (for
example, runner or account infrastructure) is not source-validation evidence
and must be rerun.

After a successful contracts job, the workflow prints `build.json` and `sha256.txt` and uploads the generated component, capsule metadata, extracted interface, build receipt, and digest as `phase-0-echo-capsule-${GITHUB_SHA}` for 14 days. This retained artifact is reproducibility evidence for the locally trusted fixture; it is not a signed or distributable release artifact.

## Allocation boundary

Static schema, WIT, Protobuf, and artifact validation uses compiler and validator commands. The complete `tools/validate_contracts.sh` gate also runs real Component Model integration tests: those tests create bounded engines, async runtimes, stores, and execution fixtures, then verify cleanup. They do not start a public node listener. Dormant catalog entries and prepared components do not retain activation stores or instances. The fixed pool stores only node-owned slot identifiers and generation counters while idle; activation and tenant identity exist only in bounded waiters and active leases.

## Scope

Passing ordinary Phase 1 foundation checks validates the implemented manifest,
budget/cancellation, storage, local routing, admission, scheduling, generic
execution, activation capabilities/lifecycle, telemetry, invocation/management
adapters, and standalone behavior covered by the selected tests. The operator
CLI is implemented and covered by its executable integration tests. Finite
startup/restart/shutdown checks alone do not establish long-running reclamation
or heavy dormant-service scale. The completed Phase 1 gate combines its retained
conformance, scale, soak, and benchmark evidence; the extension separately
records optimization results and Docker/Kubernetes comparisons.

Passing the Phase 0 executable baseline establishes source consistency, guest behavior,
component-interface validity, fixed cell-pool accounting, real Wasmtime
invocation/containment, and same-boundary build reproducibility. A baseline
does not by itself authorize Phase 1: the retained August 30 full receipt also
verified conclusive calibration, profiling, and long-running resource evidence
and therefore authorized the handoff. It never
establishes production APIs, cross-platform byte identity, generic dispatch,
production security, dormant-service density, cluster behavior, or production
SLOs.
