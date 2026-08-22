# Capsule Development

> **Document role:** Design guide for future capsule authors. The runtime and packaging flow are not yet fully implemented.

## Capsule shape

A capsule project:

1. defines or consumes versioned WIT packages;
2. implements exported interfaces in a supported guest language;
3. declares only the platform imports it requires;
4. compiles to a WebAssembly Component Model binary;
5. packages immutable metadata and supply-chain evidence.

Expected release assets include:

```text
component.wasm
capsule manifest
WIT package and lock graph
SBOM
build provenance
signature or local trust declaration
```

## Design rules

A portable capsule should:

- create no background thread or listener;
- make no assumption that process-local state survives a call;
- avoid unrestricted filesystem, environment, socket, process, and secret access;
- express every external dependency through an imported WIT contract;
- use stable idempotency identities for side-effecting operations;
- use asynchronous calls or durable workflow suspension for long waits;
- use blob capabilities for large values;
- declare domain errors explicitly;
- keep platform failures separate from domain errors.

## Export design

Exports form the service's domain contract. Prefer:

- explicit input and output records;
- versioned package names;
- bounded payloads or blob references;
- domain-specific error variants;
- clear idempotency and retry semantics;
- operations whose deadlines and side effects can be reasoned about.

Do not encode fabric infrastructure failures as arbitrary domain strings.

## Import design

Imports declare needed external capabilities. Importing an interface does not grant it. At activation time, the runtime intersects:

```text
requested import ∩ deployment grant ∩ principal authorization
```

An absent grant should result in an explicit platform denial, not ambient host access.

## State

Choose the smallest state model that fits:

- stateless invocation;
- transactional keyed state;
- entity-key routing;
- explicit durable workflow state machine.

Do not treat guest linear memory as durable state.

## Effects

Represent external operations as effect intents when durability and recovery are required. Include deterministic effect identity and a stable idempotency key. Do not assume that a transport retry is safe merely because the first response was lost.

## Long-running work

Ordinary async waiting may retain logical activation state while releasing a compute worker. Work that must survive node or process loss should be an explicit durable workflow that can persist a continuation and release the entire cell.

## Build and packaging status

The current repository validates interface definitions and compile-smoke projections. It does not yet provide the final `latent` CLI packaging and deployment implementation described by the architecture.

The [`examples/echo-contract`](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/examples/echo-contract) directory demonstrates contract shape without implying a working production runtime.

## Review checklist

Before proposing a capsule-facing contract, verify:

- WIT is the authoritative source;
- contract and implementation versions are separated;
- domain and platform errors remain distinct;
- every import has policy and resource implications;
- state and external-effect semantics are explicit;
- large values avoid repeated copying;
- child calls inherit bounded budgets;
- compatibility tests cover the intended evolution path.

## Canonical sources

- [Creating a capsule](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/component-development/creating-a-capsule.md)
- [Contracts and bindings](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/contracts-and-bindings.md)
- [State and effects](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/state-and-effects.md)
- [Security architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/security.md)
