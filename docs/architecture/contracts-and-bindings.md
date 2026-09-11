# Contracts and bindings

Phase 1 validates local component metadata and dispatches supported exported
contracts/functions through the [generic Wasmtime backend](../runtime/wasmtime.md).
It binds only declared context, log and clock imports. SDK interface projections
compile, while general SDK transports remain unimplemented. Binding-graph
compilation, provider-to-provider calls, remote/inline modes and automatic
compatibility migration below are design contracts for later phases, not
available Phase 1 execution modes.

## Contract authority

WIT is authoritative for capsule-visible types, functions, resources, futures, streams, imports, and exports. Language SDK surfaces are generated or handwritten projections and must not change semantics.

## Version identity

A release has separate identities for:

- implementation semantic version,
- release content digest,
- exported contract versions,
- imported contract requirements,
- minimum fabric version.

Implementation version and contract version are not interchangeable.

## Planned binding graph

A binding connects one consumer import to one provider export or host capability:

```text
consumer revision + imported contract + caller policy
    → binding
    → host capability | local provider | remote provider | derived composition
```

## Planned physical modes

- `host`: import is supplied by the capability broker.
- `inline`: provider is composed into the same activation.
- `isolated-local`: provider runs as a separate activation on the same node.
- `remote`: provider runs on another node.
- `auto`: runtime selects a permitted mode.

## Inline eligibility

Inline composition requires compatible trust, state, transaction, budget, and observability semantics. A deployment may forbid inline mode even when technically possible.

## Error semantics

Domain errors remain declared by WIT. Fabric errors use the platform-error envelope. Generated clients must expose both layers and must not make isolated or remote calls appear infallible.

## Compatibility direction

Compatibility checks consider removed functions, changed parameter/result types, changed variant cases, resource semantics, async behavior, and transitive package dependencies. Breaking contracts require a new major contract version and explicit migration or parallel routing.

Current preparation checks agreement between the supplied manifest/contract
metadata and actual component imports, exports and supported value signatures.
It does not supply a general WIT-version compatibility analyzer. WIT package
versions remain distinct from workspace and SDK package release versions.
