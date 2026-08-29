# Latent Service Fabric

Latent Service Fabric (LSF) is a component-native execution-fabric engineering
project. Its Phase 0 spike establishes a bounded local feasibility proof for
executing independently deployable service capsules without assigning persistent
processes, sockets, threads, heaps, or connection pools to idle services.

A deployed service is represented by immutable code, contracts, policy, state metadata, and routing metadata. Resources are allocated only when an invocation becomes an activation. Activations execute in a fixed pool of reusable sandboxed cells.

> Phase 0 has a narrow, non-production executable spike and passing retained
> #39 resource-soak evidence for its recorded native-Linux configuration. Its
> completion gate is **blocked**: Phase 1 is not authorized until a clean
> checkout produces an `authorized` `make phase0-gate` receipt for the current
> execution identity. Most repository surfaces remain architecture and API
> scaffolding; the spike does not establish Phase 1 API compatibility or
> production readiness.

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
crates/               Rust architectural interfaces, data models, and Phase 0 runtime pieces
wit/                  WIT packages for platform capabilities
api/proto/            Protobuf service definitions
schemas/              JSON Schemas for declarative resources
sdk/                  Cross-language interface-only SDK surfaces
examples/             Contract and deployment examples
adr/                   Accepted architecture decisions
rfcs/                  Future design proposals
research/              Experimental tracks kept outside the production core
docs/                  Architecture, protocol, operations, and security documentation
tests/                 Conformance, isolation, chaos, and leak-test specifications
benchmarks/            Benchmark definitions and checked-in Phase 0 evidence
tools/                 Pinned validation, generation, spike, benchmark, and gate tooling
```

## Intended binaries

- `latentd`: data-plane node runtime. Its only current behaviors are the finite local `phase0-spike invoke-once` harness and its `verify-recovery` containment proof.
- `latent-control`: clustered control-plane application placeholder.
- `latent`: future build, package, deployment, inspection, invocation, and benchmark CLI placeholder.

The `latentd` spike has no management API, public invocation listener, persistent catalog, deployment surface, or production operations contract.

## Phase 0 result

The Phase 0 spike proves a deliberately narrow local feasibility slice:

1. build one Rust echo Component Model guest through generated WIT bindings;
2. load and invoke it through real Wasmtime Component Model bindings;
3. lease and reclaim one generic execution cell with a bounded queue;
4. contain declared domain errors, trap, timeout, cancellation, and memory
   pressure failures; and
5. record bounded activation-owned state and fixed runtime topology for the
   measured lifecycle.

It does **not** prove routing, admission, deployment management, production
trust/security, durable state/effects, remote invocation, cluster operation,
production SLOs, arbitrary-duration leak freedom, or the 100,000
dormant-service invariant. The retained matched resource soak completes issue
#39 for its recorded configuration; it is single-host observational evidence,
not Phase 0 or Phase 1 authorization. See
[`docs/phase-0-completion.md`](docs/phase-0-completion.md) for its evidence
ledger, gate receipt, and Phase 1 handoff.

See [`docs/architecture/overview.md`](docs/architecture/overview.md) and
[`docs/testing/invariants.md`](docs/testing/invariants.md) for the proven
boundary and future invariants.

## Build and validation

The Phase 0 build baseline pins Rust, Component Model, Protobuf, schema, and SDK tools. After installing the prerequisites documented in [`docs/development/toolchain.md`](docs/development/toolchain.md), validate a clean checkout with:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

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
`target/phase0-gate/`. The retained #39 calibration and soak pass for their
recorded configuration, but they must also match the current execution identity
and fresh baseline. Phase 1 remains blocked unless the full receipt is
`authorized`. Use `make phase0-gate-smoke` for the deterministic CI-sized
sequence; it records a receipt without presenting smoke coverage as
authorization.

Generated bindings, parsed WIT output, Protobuf descriptors, and SDK compiler artifacts are isolated under Cargo `OUT_DIR` or `target/contracts/`; handwritten contract sources are never overwritten. See [`VALIDATION.md`](VALIDATION.md) for the checks performed.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
