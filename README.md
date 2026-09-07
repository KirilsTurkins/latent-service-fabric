# Latent Service Fabric

Latent Service Fabric (LSF) is a component-native execution-fabric engineering
project. Its Phase 0 spike establishes a bounded local feasibility proof for
executing independently deployable service capsules without assigning persistent
processes, sockets, threads, heaps, or connection pools to idle services.

A deployed service is represented by immutable code, contracts, policy, state metadata, and routing metadata. Resources are allocated only when an invocation becomes an activation. Activations execute in a fixed pool of reusable sandboxed cells.

> Phase 1 is in progress. The executable Phase 0 echo runtime now has maintained manifest validation, budget/cancellation primitives, durable local catalogs and routing, bounded admission, and fair scheduling implementations alongside it. A standalone Phase 1 node, public service adapters, and operator CLI remain pending. The retained August 30 native-Linux Phase 0 full-gate receipt authorizes that work; it does not establish production readiness or completion of Phase 1.

## Core invariant

```text
resident resources = fixed node runtime + active activations + bounded shared caches
```

The number of operating-system processes, threads, sockets, and execution cells is node-defined and must not scale with the number of deployed services.

## Authoritative interface layers

- **WIT** defines capsule exports, platform capabilities, and component-to-component contracts.
- **Protobuf** defines control-plane, node-management, trigger-management, and generic invocation APIs.
- **JSON Schema** defines declarative capsule, deployment, binding, policy, trigger, and route documents.
- **Rust traits** define the internal architectural seams between runtime subsystems.
- **Language SDK surfaces** expose implementation-neutral client and guest contracts.

## Repository map

```text
apps/                 Binary entry points and the explicit latentd Phase 0 spike mode
crates/               Rust interfaces, Phase 0 runtime, and implemented Phase 1 foundations
wit/                  WIT packages for platform capabilities
api/proto/            Protobuf service definitions
schemas/              JSON Schemas for declarative resources
sdk/                  Cross-language interface-only SDK surfaces
examples/             Contract and deployment examples
adr/                   Accepted architecture decisions
rfcs/                  Future design proposals
research/              Experimental tracks kept outside the production core
docs/                  Architecture, protocol, operations, and security documentation
tests/                 Cross-phase test specifications; executable tests also live with crates/apps/tools
benchmarks/            Benchmark definitions and checked-in Phase 0 evidence
tools/                 Pinned validation, generation, spike, benchmark, and gate tooling
```

## Intended binaries

- `latentd`: data-plane node runtime. Its only current behaviors are the finite local `phase0-spike invoke-once` harness and its `verify-recovery` containment proof.
- `latent-control`: clustered control-plane application placeholder.
- `latent`: future build, package, deployment, inspection, invocation, and benchmark CLI placeholder.

The `latentd` spike has no management API, public invocation listener, persistent catalog, deployment surface, or production operations contract.

## Available Phase 1 foundations

These implementations are usable through Rust APIs and focused tests; composing
them into the standalone node is still tracked by
[#14](https://github.com/KirilsTurkins/latent-service-fabric/issues/14).

| Feature | Implemented surface and documentation |
| --- | --- |
| Locked build and generated contracts | Protobuf/Tonic and Component Model bindings, SDK checks, deterministic test utilities; [build foundation](docs/development/build-foundation.md) |
| Manifest decoding and validation | Bounded schema-backed JSON codecs, canonicalization, and stateless Phase 1 semantic validation; [manifest codec](docs/protocol/manifest-codec.md) |
| Resource accounting | Effective deadlines, concurrent budget consumption/reservations, terminal reconciliation, and cancellation primitives; [resource budgets](docs/runtime/resource-budgets.md) |
| Local release storage | Exclusive directory ownership, immutable digest verification, bounded listing/indexes, durable publication and recovery; [release catalog](docs/development/local-release-catalog.md) |
| Deployment and routing | Atomic caller version preconditions and mutation receipts, bounded tenant/service pages, immutable route generations, deterministic resolution, pinned revisions, and restart recovery; [deployment routing](docs/deployment-routing.md) |
| Admission and quotas | Tenant/trust/queue capacity, bounded input, deadline and overload checks, compatible cell selection, and affine quota permits; [admission control](docs/admission-control.md) |
| Fair scheduling | Fixed class pools, bounded tenant-fair queues, priority/deadline/aging order, shared cancellation, and owned cell/quota disposition; [scheduling](docs/scheduling.md) |

Generic Wasmtime dispatch, complete activation
orchestration, clock capabilities, invocation/management services, shared
telemetry, the standalone node, CLI, and the Phase 1 gate remain open work. See
[the roadmap](docs/roadmap.md) for issue links and phase boundaries.

## Phase 0 result

The Phase 0 spike proves a deliberately narrow local feasibility slice:

1. build one Rust echo Component Model guest through generated WIT bindings;
2. load and invoke it through real Wasmtime Component Model bindings;
3. lease and reclaim one generic execution cell with a bounded queue;
4. contain declared domain errors, trap, timeout, cancellation, and memory
   pressure failures; and
5. record bounded activation-owned state and fixed runtime topology for the
   measured lifecycle.

![Phase 0 scope boundary: one local component moves through preparation, a fixed cell pool, and fresh activation state; public APIs, routing, durable state, and clustering remain outside the measured evidence.](docs/assets/phase0-scope-boundary.svg)

It does **not** prove routing, admission, deployment management, production
trust/security, durable state/effects, remote invocation, cluster operation,
production SLOs, arbitrary-duration leak freedom, or the 100,000 dormant-service
invariant. The retained matched resource soak is current, single-host
observational evidence and participates in the authorized full-gate receipt;
the authorization does not extend the conclusions beyond this boundary. See
[`docs/phase-0-completion.md`](docs/phase-0-completion.md) for its evidence
ledger, current authorization status, and Phase 1 handoff.

See [`docs/architecture/overview.md`](docs/architecture/overview.md) and
[`docs/testing/invariants.md`](docs/testing/invariants.md) for the proven
boundary and future invariants. Documentation SVGs follow the shared
[`SVG convention`](docs/svg-style.md).

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

Run the complete local Phase 0 executable demonstration with:

```bash
make phase0-spike-demo
```

The command validates contracts, builds the real guest and runtime, exercises success and containment failures only through the `latentd` executable path, includes a single-process trap-to-success recovery proof, and finishes with one successful echo result. See [`docs/phase-0-spike.md`](docs/phase-0-spike.md) for the CLI, JSON schema, exit codes, cleanup proof, and limitations.

Run the full Phase 0 completion gate with:

```bash
make phase0-gate
```

It runs the complete clean-checkout validation, executable spike, and fresh
baseline sequence, then writes a machine-readable receipt under
`target/phase0-gate/`. The retained [August 30 receipt](benchmarks/phase0/receipts/native-linux-2026-08-30-b932a935/gate-summary.json)
records the current `pass` / `authorized` result and its checked execution
identity. The [August 29 receipt](benchmarks/phase0/receipts/native-linux-2026-08-29-54d02679/gate-summary.json)
remains immutable historical evidence.
Use `make phase0-gate-smoke` for the deterministic CI-sized sequence; it
records the same receipt format without presenting smoke coverage as
authorization.

Generated bindings, parsed WIT output, Protobuf descriptors, and SDK compiler artifacts are isolated under Cargo `OUT_DIR` or `target/contracts/`; handwritten contract sources are never overwritten. See [`VALIDATION.md`](VALIDATION.md) for the checks performed.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
