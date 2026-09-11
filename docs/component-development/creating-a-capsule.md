# Creating a capsule

A capsule project defines a versioned WIT world, implements its exported interfaces in a supported guest language, declares only the platform imports it requires, compiles to a Component Model binary, and packages immutable metadata.

## Phase 1 assets and workflow

The completed Phase 1 workflow publishes locally trusted component bytes with a
validated capsule manifest and typed contract metadata. A deployment manifest
selects the release and its routes. Follow the executable
[standalone quickstart](../development/standalone-quickstart.md) for the maintained
echo component and the [management reference](../reference/management-services.md)
for publication validation.

The [echo fixture](../../examples/echo-contract/README.md) includes a Rust guest,
pinned build tooling and reproducibility checks. Its generated package is
executable on the standalone node; the checked-in `publish-release.json` is only
a schema-shape example with placeholder digests.

## Phase 2 packaging target

The supply-chain package described below is the Phase 2 target. OCI distribution,
signature verification, SBOM handling and provenance policy are not implemented
by the Phase 1 local publication workflow.

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
- Domain errors are explicit WIT variants.
- Platform failures remain separate.

Phase 1 provides activation context, clocks, resource budgets and structured
logging. Calls execute within finite activation budgets; persistent guest state
and background work are unavailable. General capabilities, including blob
storage, belong to Phase 3. Stable idempotency for state/effects and durable
workflow suspension belong to later phases; see the [roadmap](../roadmap.md).
