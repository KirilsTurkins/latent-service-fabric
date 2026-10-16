# Workspace package architecture

Use this guide to find the implementation owner before changing a Rust package.
The [package index](../../crates/README.md) links all 53 workspace members,
including applications, SDKs and tools outside `crates/`. Each package README
maps its public surface, modules, execution/ownership flow, dependency and feature
gates, source tests and related specifications.

The index also covers the two independently locked Rust projects outside the
root workspace: the native VM fixture generator and Rust shadow-stack source
transform. Their manifests select separate builds; neither is an additional
production execution backend.

These pages describe Development. The [release changes guide](../start/development-changes.md)
separates it from the published toolkit. Interface scaffolds and optional research
contracts are identified explicitly; a manifest value or generated service does
not establish an installed implementation.

## Follow the operation's owner

| Change | Start here | Adjacent boundary to inspect |
| --- | --- | --- |
| Identity, deadline, budget or lifecycle vocabulary | [latent-core](../../crates/latent-core/README.md) | Admission and original resource owners; wire projections |
| Manifest/schema validation | [latent-manifest](../../crates/latent-manifest/README.md) | Authoritative schemas, packaging and runtime compatibility |
| WIT interface or generated resource identity | [latent-component-bindings](../../crates/latent-component-bindings/README.md) | WIT authority, host adapter and guest SDK |
| RPC schema and generated services | [latent-rpc](../../crates/latent-rpc/README.md) | Protobuf manifest, concrete wire adapter and clients |
| Structural compatibility | [latent-contracts](../../crates/latent-contracts/README.md) | Full component/WIT inspection in packaging |
| Package layout, SBOM or supplied-file validation | [latent-packaging](../../crates/latent-packaging/README.md) | Artifact identities, signing and registry transfer |
| Publication storage and release eligibility | [latent-artifacts](../../crates/latent-artifacts/README.md) | Current supply-chain authority and catalog pins |
| Cryptographic evidence or admission policy | [latent-signing](../../crates/latent-signing/README.md), [latent-policy](../../crates/latent-policy/README.md) | Exact subjects, current trust/time and final acceptance fences |
| Invocation lifecycle or child calls | [latent-node](../../crates/latent-node/README.md) | Admission, scheduler, backend, journal and descendant accounting |
| Execution, interruption or code reuse | [latent-executor](../../crates/latent-executor/README.md), [latent-wasmtime](../../crates/latent-wasmtime/README.md) | Preparation identity, fresh Store state and cleanup |
| Capability acceptance or provider resources | [latent-capabilities](../../crates/latent-capabilities/README.md) | Installed provider, policy, audit and actual I/O owner |
| HTTP adaptation or application delivery | [latent-ingress](../../crates/latent-ingress/README.md) | Listener, exact trigger selection and browser boundary |
| Transaction storage and recovery | [latent-state](../../crates/latent-state/README.md) | Original protected worker/view, namespace history and native capacity |
| Atomic command completion | [latent-commit](../../crates/latent-commit/README.md) | State/result/outbox/inbox envelope and physical retirement |
| Deferred dispatch and uncertainty | [latent-effects](../../crates/latent-effects/README.md) | Current effect authority, qualified provider and durable transitions |
| Deployment, binding or rollout mutation | [latent-control-store](../../crates/latent-control-store/README.md), [latent-rollout](../../crates/latent-rollout/README.md) | One route publication owner, response ownership and audit |
| Startup, listeners or shutdown | [latentd](../../apps/latentd/README.md) | Configuration validation and shared composition |
| Operator/client behavior | [latent](../../apps/latent/README.md), [latent-sdk](../../sdk/rust/README.md) | Original operation identity, bounded transport and outcome recovery |
| Guest helper/resource lifecycle | [latent-guest](../../sdk/rust-guest/README.md) | Exact generated WIT profile and actual Wasm fixture |

## Three end-to-end flows

### Publish and select code

Explicit authoring inputs pass through packaging without guest execution.
Registry transfer preserves exact bytes and evidence association. Publisher and
builder verification feed current supply-chain admission; the artifact catalog
retains the publication association separately from immutable content. The
deployment catalog compiles routes and checked bindings against that association.

An invocation pins one catalog generation for resolution and admission policy.
Retained code or route metadata still needs live publication, policy and provider
checks before the corresponding operation starts. See
[publication/runtime ownership](../reference/publication-runtime.md) and
[contracts and bindings](../architecture/contracts-and-bindings.md).

### Execute one activation

The configured listener authenticates a bounded request. `latent-wire` or the
HTTP adapter validates it and calls the local activation manager. The manager
owns request identity, cancellation, journal and deadline while composing
admission, scheduling, preparation and backend execution.

`latent-admission` reserves quota. Ordinary requests prepare immutable code
readiness before `latent-scheduler` assigns a node-owned generic cell; after
assignment, the backend materializes that readiness and creates a fresh Store.
Nested calls reserve their child cell before preparation so they cannot queue
behind a parent that retains the capacity they need. Transaction input
canonicalization can require readiness before command admission.
Broker sessions and provider calls retain the original activation's authority
and accounting. A local service call follows a separate child lifecycle.

An asynchronous wait yields execution time while retaining the Store, cell and
accepted resource owners. Terminal handling requires actual backend/provider
retirement and an explicit reusable/quarantine disposition before capacity is
reused. A transport timeout alone cannot supply that proof. See
[activation lifecycle](../protocol/activation-lifecycle.md),
[asynchronous I/O](../runtime/async-host-io.md) and
[local child calls](../runtime/local-service-invocation.md).

### Commit a command and dispatch an effect

The opt-in Development transaction composition installs one protected state
engine and fixed storage workers. A selected command gets current namespace and
publication authority, an original command identity and bounded optimistic state
access. Guest completion hands staged values/intents back to the host.

`latent-commit` prepares one atomic state/result/outbox/inbox envelope.
`latent-state` applies expected originals and the final host acceptance fence on
the same engine. `latent-effects` later drives durable indexed backlog through a
qualified provider using fresh current authority and the original effect identity.
Provider uncertainty, audit uncertainty and durable command outcome remain
separate facts. Recovery keeps the original physical owner and paused-state
requirements; it does not recreate permission from historical receipts.

See [state and effects](../architecture/state-and-effects.md),
[installed transaction adapters](installed-transaction-rpc.md) and
[remaining recovery qualification](../testing/installed-transaction-recovery.md).
These implementations do not imply that all native/application/packaged
acceptance gates have passed.

## Choose features and targets deliberately

The root [Cargo manifest](../../Cargo.toml) defines workspace membership and
shared dependencies. Package manifests own optional, target-specific, dev and
build edges. README dependency lists identify normal workspace edges; they are
not a substitute for Cargo's complete selected feature graph.

- `latent-testkit` defaults to its node-dependent `runtime` feature. Upstream
  foundations use `latent-core/test-support` or neutral `latent-test-process`
  directly; clocks-only consumers can disable testkit defaults. This avoids
  pulling the node/provider/state path back into its foundations.
- `latent-component-bindings` generates host versus guest bindings by target.
  Its activation and transaction guest selections cannot both be enabled on
  wasm32. `latent-guest/transaction` selects the transaction profile.
- `latent-vault` is Linux x86-64 gated. `latent-guest` and the Angular adapter
  expose guest APIs on wasm32. An empty successful build on another target does
  not qualify operational behavior.
- Development clock/test-host, outbound-stream and measurement features require
  their explicit fixture/profile. Enabling them is not a production grant or
  replacement for current admission owners.

Use [selected toolchains](toolchain.md) and
[generated input ownership](build-foundation.md). WIT and Protobuf are
authoritative; generated Rust belongs in `OUT_DIR`. Do not commit generated
bindings or introduce another generator to repair a resource-type mismatch.

## Inspect and run the owning tests

From the repository root, inspect metadata first:

```sh
python3 tools/test.py list --output json
python3 tools/test.py explain --suite latent-core.lib.latent-core
```

Each package README supplies a real registered suite ID where one exists.
`list`, `explain` and `plan` inspect selection metadata without compiling or
executing tests. Follow [the local test workflow](local-tests.md) for preparation,
source-matched artifact discovery, checks and selected execution. The suite's
recipe owns its fixtures and platform prerequisites.

Source-level tests, controlled RPC peers, portable guest execution, native
provider integration and resource qualification establish different boundaries.
Do not infer real-node behavior from an interface-only package or portable test
host. No-test scaffolds and compile-only surfaces need consuming integration
evidence. Benchmark/scale/soak tools remain explicitly selected work.

## Keep package documentation current

When changing a package's API or architecture, update its README in the same
change. Explain the operation's owner, status, lifecycle, failure/uncertainty
behavior, adjacent crates and affected feature/target gates. Link source modules
and central architecture/ABI/protocol guides instead of copying another version
of the specification or toolchain table.

Update [the index](../../crates/README.md) when membership or a package's role
changes. Validate links and the website with the
[documentation workflow](website.md) and [contribution checks](../../CONTRIBUTING.md).
Frozen release documentation and retained measurements keep their original scope.
