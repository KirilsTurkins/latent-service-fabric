# Creating a capsule

A capsule project defines a versioned WIT world, implements its exported interfaces in a supported guest language, declares only the platform imports it requires, compiles to a Component Model binary, and packages immutable metadata.

## Required assets

```text
component.wasm
capsule manifest
WIT package and lock graph
SBOM
build provenance
signature or local trust declaration
```

## Design rules

- No background threads or listeners.
- No assumption that process-local state survives a call.
- No unrestricted filesystem, environment, network, or secret access.
- Every external dependency is an imported WIT contract.
- Side-effecting operations use stable idempotency keys.
- Long waits use async calls or durable workflow suspension.
- Large values use the blob capability rather than repeated copies.
- Domain errors are explicit WIT variants.
- Platform failures remain separate.

The `examples/echo-contract` directory demonstrates the shape without providing a runtime implementation.
