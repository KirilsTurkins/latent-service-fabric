<!-- LSF-WIKI-MANAGED -->
# Contracts and APIs

LSF keeps external contracts separate from internal implementation seams. A
language SDK or runtime adapter must not silently change the semantics of its
authoritative layer.

| Layer | Authority | Current role |
|---|---|---|
| WIT | Capsule exports and platform imports | Phase 0 builds a real echo Component Model through generated bindings. |
| Protobuf | Control-plane and generic invocation contracts | Checked-in contract surface; not yet the Phase 0 public runtime API. |
| JSON Schema | Declarative capsule/deployment/binding/policy/trigger/route documents | Checked and validated as repository contracts. |
| Rust traits | Internal subsystem seams | Separate pool, execution, artifact, routing, policy, and other boundaries. |
| SDKs | Language-facing projections | Rust, Go, TypeScript, Java, .NET, and C surfaces are compiled/checked. |

## WIT in the Phase 0 spike

The echo guest has a WIT export and imports the context and logging
capabilities. It returns normal text or a declared domain-error variant. The
host validates the generated component interface before invoking it through
Wasmtime.

That proves one real typed guest/host boundary. It does not make the
spike-specific JSON command output a stable future SDK or invocation API.

## Error separation

Domain errors are declared by the service contract and are not platform
failures. Trap, deadline, cancellation, resource exhaustion, invalid input,
and cleanup failures are represented through the platform error boundary.
Clients must preserve both layers.

## What remains later work

The generic invocation, cancellation, and retained activation-status APIs are
Phase 1 contract work. Their existence in Protobuf or SDK source must not be
confused with an implemented public node service until the matching runtime
and evidence are delivered.

## Canonical sources

- [API surface map](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/api-surface.md)
- [WIT packages](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/wit)
- [Protobuf APIs](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/api/proto)
- [JSON Schemas](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/schemas)
- [SDK sources](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/sdk)
