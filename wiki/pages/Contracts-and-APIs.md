# Contracts and APIs

> **Document role:** Navigation and interpretation. The checked-in WIT, Protobuf, JSON Schema, Rust, and SDK files are authoritative.

## Contract authority

| Layer | Authority and purpose |
|---|---|
| WIT | Capsule-visible exports, imports, functions, resources, futures, streams, and platform capabilities |
| Protobuf | Control-plane, node-management, trigger-management, route, audit, and generic invocation APIs |
| JSON Schema | Declarative capsule, deployment, binding, policy, trigger, and route-snapshot resources |
| Rust traits | Internal architectural seams between runtime subsystems |
| SDK surfaces | Language-facing projections that must preserve the authoritative semantics |

No generated or handwritten SDK may silently change the meaning of its underlying contract.

## Guest-facing WIT packages

The API map currently includes packages for context, structured logging, clocks, randomness, blobs, transactional state, durable event intents, outbound HTTP, secrets, timers, telemetry, service-to-service invocation, and the aggregate capsule world.

Guest code should request only the imports it needs. Every import is later intersected with deployment grants and caller policy.

## Protobuf services

The control and management API includes services for:

- releases and contracts;
- capabilities and audits;
- deployments and bindings;
- triggers and policies;
- nodes and route snapshots;
- generic invocation, cancellation, and activation status.

Protobuf does not replace WIT for component-level domain contracts. It provides management and generic platform APIs.

## Declarative schemas

Schemas define the portable shape of:

- capsule manifests;
- deployments;
- bindings;
- policies;
- triggers;
- compiled route snapshots.

Declarative resources must be validated before they reach implementation-specific reconciliation logic.

## Internal Rust seams

The workspace separates artifact, contract, policy, routing, admission, scheduling, activation, execution, capability, blob, identity, trigger, ingress, commit, state, effect, workflow, wire, remote-call, node, control-store, telemetry, audit, and testkit concerns.

The trait graph is intended to keep implementations replaceable and dependencies acyclic.

## Version identity

A release has several distinct identities:

- implementation semantic version;
- immutable content digest;
- exported contract versions;
- imported contract requirements;
- minimum compatible fabric version.

Implementation version and contract version are not interchangeable.

## Bindings

A binding resolves a consumer import to a host capability or provider:

```text
consumer revision + imported contract + caller policy
    → binding
    → host capability | local provider | remote provider | derived composition
```

Physical modes:

- `host`: supplied by the capability broker;
- `inline`: composed into the same activation;
- `isolated-local`: separate activation on the same node;
- `remote`: activation on another node;
- `auto`: runtime chooses among policy-permitted modes.

Inline composition requires compatible trust, state, transaction, budget, and observability semantics.

## Errors

Contracts expose two error layers:

1. **Domain errors**, declared in WIT by the service contract.
2. **Platform errors**, carried in a stable infrastructure envelope.

Clients must not erase the platform-error layer or make isolated and remote calls appear infallible.

## Compatibility

Compatibility analysis considers removed functions, changed parameter or result types, variant cases, resource semantics, asynchronous behavior, and transitive package dependencies.

Breaking contracts require a new major contract version and explicit migration or parallel routing.

## Canonical sources

- [API surface map](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/api-surface.md)
- [Contracts and bindings architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/contracts-and-bindings.md)
- [WIT contracts](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/wit)
- [Protobuf APIs](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/api/proto)
- [JSON Schemas](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/schemas)
- [Rust crates](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/crates)
- [Language SDKs](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/sdk)
- [Platform error model](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/platform-errors.md)
