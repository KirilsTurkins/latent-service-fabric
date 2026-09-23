# Latent Service Fabric

Latent Service Fabric (LSF) is a component-native execution-fabric engineering
project. Its standalone runtime runs independently deployable stateless service
capsules on a standalone Linux node without assigning persistent processes,
sockets, threads, guest heaps, or connection pools to idle services.

A deployed service is represented by immutable code, contracts, policy, deployment metadata, and routing metadata. Execution resources are allocated when an invocation becomes an activation. Activations execute in a fixed pool of reusable sandboxed cells; bounded catalog metadata remains resident independently of execution.

The development branch includes capability providers, six external client SDKs,
shared HTTP ingress, static-site delivery and the supported Angular SSR profile.
Standalone configuration exposes the providers listed in its reference;
additional provider integrations use the documented trusted Rust embedding.
See [current delivery](docs/phase-2-delivery.md) for supported workflows.

The project is in alpha. The next release remains on hold pending completed
capsule authoring in all six languages, the maintainer's guide review, and
explicit publication approval. Contributors track the remaining acceptance in
[the gate review](docs/phase-3-gate-review.md).

Read the [documentation website](https://kirilsturkins.github.io/latent-service-fabric/)
for published alpha and development guides. The site identifies the source and
supported profile of its content; repository documentation can be newer than
the deployed snapshot. Start with the [runtime concepts guide](docs/learn/runtime-identities.md)
for the source-reviewed learning path.

## Core invariant

```text
resident state = fixed node runtime + bounded catalog metadata + active activations + bounded shared caches
```

The number of operating-system processes, threads, sockets, and execution cells is node-defined and must not scale with the number of deployed services.

[![Build a package, sign and admit it, then invoke a capsule or serve a website through the node.](docs/assets/package-delivery.svg)](docs/assets/package-delivery.svg)

Open the diagram at full size to read its labels. Follow
[Run your first node](docs/start/first-node.md) to try a complete local service,
then [create your own capsule](docs/component-development/creating-a-capsule.md).

## Authoritative interface layers

- **WIT** defines capsule exports, platform capabilities, and component-to-component contracts.
- **Protobuf** defines control-plane, node-management, trigger-management, and generic invocation APIs.
- **JSON Schema** defines declarative capsule, deployment, binding, policy, trigger, and route documents.
- **Rust traits** define the internal architectural seams between runtime subsystems.
- **Language SDK surfaces** expose implementation-neutral client and guest contracts.

## Repository map

```text
apps/                 Standalone latentd node, operator CLI, and control-plane placeholder
crates/               Rust interfaces and maintained runtime/control-plane subsystems
wit/                  WIT packages for platform capabilities
api/proto/            Protobuf service definitions
schemas/              JSON Schemas for declarative resources
sdk/                  External client interfaces, Rust guest SDK and C guest conformance
examples/             Contract and deployment examples
adr/                   Accepted architecture decisions
rfcs/                  Future design proposals
research/              Experimental tracks kept outside the production core
docs/                  Architecture, protocol, operations, and security documentation
tests/                 Cross-phase test specifications; executable tests also live with crates/apps/tools
benchmarks/            Benchmark definitions, historical measurements and compact Phase 2 gate evidence
tools/                 Pinned validation, generation, benchmark, and retained-evidence tooling
```

## Binaries

For the native prebuilt distribution contract, start with
[native standalone installation](docs/installation.md). It separates verified
offline bundles, rootless local evaluation and persistent systemd servers from
application development and contributor builds. The page explicitly records
pending release/VM gates; the historical `0.1.0-alpha.3` release remains source-only.

- `latentd`: standalone Linux node through `check-config` and `serve --config PATH`. Obsolete catalogs require [fresh state](docs/reference/publication-catalog.md#supported-storage-and-fresh-state).
- `latent-control`: clustered control-plane application placeholder.
- `latent`: bounded local package build/inspect/verification and OCI transfer; authenticated release lifecycle, managed deployment receipts, rollout/canary/rollback, audit, invocation/cancellation/status, routing and node commands.

See [standalone node configuration and operation](docs/reference/standalone-node.md)
for loopback authentication, readiness, durable restart, and bounded shutdown.
The [operator CLI reference](docs/reference/operator-cli.md) and
[scriptable echo quickstart](docs/development/standalone-quickstart.md) cover the
local invocation workflow. The [Package and deployment operations](docs/phase-2-operator-workflows.md)
cover package evidence, separate registry credentials, managed preconditions and
finite operation recovery. The client never silently retries a mutation or replaces
a stale precondition.

## Runtime and client features

These implementations are usable through Rust APIs, focused tests, and the
configured standalone node's supported RPC surface.

| Feature | Implemented surface and documentation |
| --- | --- |
| Locked build and generated contracts | Protobuf/Tonic and Component Model bindings, SDK checks, deterministic test utilities; [build foundation](docs/development/build-foundation.md) |
| SDK invocation contracts | Optional caller identity, cancellation/status by known ID, and executable fixtures across six languages; [SDK contract](sdk/README.md) |
| Guest SDK | Typed Rust capability helpers, generated C ownership fixtures and signed-package runtime conformance; [guest workflow](docs/component-development/guest-sdk.md) |
| Manifest decoding and validation | Bounded schema-backed JSON codecs, canonicalization, and stateless semantic validation; [manifest codec](docs/protocol/manifest-codec.md) |
| Resource accounting | Effective deadlines, concurrent budget consumption/reservations, terminal reconciliation, and cancellation primitives; [resource budgets](docs/runtime/resource-budgets.md) |
| Local release storage | Exclusive directory ownership, immutable digest verification, bounded listing/indexes, durable publication and recovery; [release catalog](docs/development/local-release-catalog.md) |
| Deployment and routing | Atomic caller version preconditions and mutation receipts, bounded tenant/service pages, immutable route generations, deterministic resolution, pinned revisions, and restart recovery; [deployment routing](docs/deployment-routing.md) |
| Admission and quotas | Tenant/trust/queue capacity, bounded input, deadline and overload checks, compatible cell selection, and affine quota permits; [admission control](docs/admission-control.md) |
| Fair scheduling | Fixed class pools, bounded tenant-fair queues, priority/deadline/aging order, shared cancellation, and owned cell/quota disposition; [scheduling](docs/scheduling.md) |
| Generic component execution | Dynamic WIT export dispatch, bounded canonical values, shared preparation, fresh stores, non-cooperative interruption, and cleanup proof; [Wasmtime backend](docs/runtime/wasmtime.md) |
| Activation capabilities | Filtered context, injectable clocks, live shared budgets, and correlated structured log acceptance; [capabilities](docs/runtime/capabilities.md) |
| Activation lifecycle | Pinned resolution, admission/scheduling, affine preparation, bounded status/journal, scoped cancellation, terminal accounting, and unconditional cleanup; [lifecycle](docs/activation-lifecycle.md) |
| Telemetry and inventory | Shared bounded export, payload-free lifecycle observation, redacted guest logs, fixed-dimension metrics, and bounded node resource snapshots; [telemetry](docs/telemetry.md) |
| Invocation service | Generated Invoke/Cancel/GetActivation adapters, scoped local authentication, manager-owned execution and retained status; [invocation service](docs/protocol/invocation-service.md) |
| Management services | Typed release uploads, atomic versioned deployments, tenant-scoped indexed reads/routes, and operator-authorized node inventory through generated RPCs; [management services](docs/reference/management-services.md) |
| Standalone node | Versioned local configuration, Linux loopback RPC and optional [shared HTTP/TLS application ingress](docs/reference/http-ingress.md), fixed runtime/control workers, measured pressure/readiness, durable restart and verified shutdown; [standalone node](docs/reference/standalone-node.md) |
| Operator CLI | Private explicit profiles, bounded local preflight, one RPC per command, exact versions/identity, structured output and exit codes, and generated echo package inputs; [operator CLI](docs/reference/operator-cli.md) |
| Bounded conformance | Real CLI/node scenarios, selected adapter/RPC parity, owned child resource probes and validated diagnostic reports; [selected profile](docs/testing/phase-1-conformance.md) |
| Full measurements and comparison | Fixed-topology scale through 100,000 registrations, three mixed soaks, seven independent benchmarks and seven historical/current pairs; [full report](benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md), [controlled comparison](benchmarks/phase1/paired/2026-09-08-container-linux-e7e06f7/REPORT.md) |
| Performance extension | Verified artifact identity, shared bounded cold preparation, prepared-cache accounting, precise deadlines, request/codec ownership, configurable engine profiles, catalog memory/persistence, and indexed queue cancellation; [results and tradeoffs](docs/phase-1-extension-completion.md) |
| Docker and Kubernetes comparisons | Actual container and ClusterIP Service deployments, warm requests, first response, startup and memory measurements with replayable evidence; [Docker](docs/testing/docker-comparison.md), [Kubernetes](docs/testing/kubernetes-comparison.md) |

The [completion review](docs/phase-1-completion.md) maps the delivered behavior to
all Phase 1 acceptance criteria and records measurement limits. See
[the roadmap](docs/roadmap.md) for issue links and future phase boundaries.

The infrastructure comparisons completed 9,926 full offers per platform. Native
services had lower warm request latency; LSF used less application memory at
8 and 32 services. The reports retain cold-start boundaries, resource-limit
differences, and the Docker Desktop/WSL2 environment. They do not establish
production cluster capacity or a universal millisecond request budget.

## Package delivery and operations

| Feature | Implemented surface and documentation |
| --- | --- |
| Package and distribution | Deterministic content identities and bounded authenticated registry transfer; [packaging](docs/component-development/packaging.md), [OCI distribution](docs/reference/oci-registry.md) |
| Supply-chain verification | Publisher trust, build provenance, and package SBOM verification; [publisher trust](docs/reference/publisher-trust.md), [provenance](docs/reference/build-provenance.md), [SBOMs](docs/component-development/sbom.md) |
| Trusted admission and lifecycle | Verified catalog admission, current eligibility, durable idempotent publication/revocation/retirement/evidence renewal; [admission](docs/reference/package-admission.md), [release lifecycle](docs/reference/release-lifecycle.md) |
| Isolated compilation and native cache | Bounded compiler children and authenticated persistent native images with private keys and explicit cache ownership; [standalone configuration](docs/reference/standalone-node.md) |
| Durable administrative audit | Bounded private journal, explicit mutation acknowledgements, tenant/operator query authorization, restart coverage and retained response ownership; [audit](docs/phase-2-audit.md) |
| Canary observations | Attributable bounded outcome windows with explicit missing samples and incomplete coverage, integrated into the existing activation owner; [canary observations](docs/phase-2-canary-observation.md) |
| Manual rollout coordination | Atomic route/state publication, exact revision and cohort conflicts, bounded receipts and restart recovery, pause/resume/abort; [rollouts](docs/phase-2-rollouts.md) |
| Controlled canary promotion | Explicit policy, full-window candidate evaluation, sealed exact-cohort evidence, current eligibility and atomic next-stage publication; [canary promotion](docs/phase-2-canary-promotion.md) |
| Atomic rollback | Plan-bound original target, current eligibility and reverse compatibility, fresh publication generation and exact operation recovery; [rollback](docs/phase-2-rollback.md) |
| Operator workflows | Local package build/inspect/verification, OCI transfer, release lifecycle, managed deployment identities, rollout controls and typed audit queries; [CLI](docs/reference/operator-cli.md), [workflow and recovery contract](docs/phase-2-operator-workflows.md) |

Local verification and copied canary observations do not authorize execution or
promotion. Managed deployments bind a caller-retained operation ID, exact object
generation and global catalog state version; receipt lookup is finite and Unknown
does not prove a mutation never ran. The [completion report](docs/phase-2-completion.md)
maps all eighteen delivery tickets and records validation, failed attempts and
the finite scope of the gate decision.

HTTP ingress, static websites, the supported Angular renderer and six native
client transports are implemented on development. See the [current architecture](docs/architecture/overview.md)
for provider configuration and deployment boundaries. Durable service state,
transactional effects and clustering are not implemented.

## Earlier measurements

The [initial completion record](docs/phase-0-completion.md),
[standalone acceptance report](docs/phase-1-completion.md) and
[delivery acceptance report](docs/phase-2-completion.md) retain their original
measurements and limitations. They describe their tested sources, rather than
the current product boundary. Current diagrams and concepts are in the
[architecture overview](docs/architecture/overview.md).

## Build and validation

The build baseline pins Rust, Component Model, Protobuf, schema, and SDK tools. After installing the prerequisites documented in [`docs/development/toolchain.md`](docs/development/toolchain.md), validate a clean checkout with:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

This runs the normal source, contract, SDK, and workspace checks. Expensive
ignored tests require explicit selection. The durable 100,000-release catalog
probe runs only when requested with the CI workflow's `run_catalog_scale` input
or its documented local command; native-Linux calibration and resource soaks
are also separate explicit work. See [validation tiers](VALIDATION.md).

Pull requests use [CI profiles](docs/development/ci-profiles.md) to select the
relevant checks. Approved Markdown/SVG-only changes run focused documentation
validation; code and mixed changes retain full validation. Full jobs can reuse
[dependency caches](docs/development/ci-caching.md) while still running all
selected checks.

Phase 0 collection commands are intentionally no longer part of current validation. Historical receipts, archives, validators, and aggregation logic remain available for integrity/replay checks; reproducing the original workloads requires checking out the source revision recorded by that evidence.

Generated bindings, parsed WIT output, Protobuf descriptors, and SDK compiler artifacts are isolated under Cargo `OUT_DIR` or `target/contracts/`; handwritten contract sources are never overwritten. See [`VALIDATION.md`](VALIDATION.md) for the checks performed.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
